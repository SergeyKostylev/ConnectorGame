"""
Checks whether a level admits a "degenerate win": a rotation assignment where
every target is still connected to a battery (the game's current win
condition), but some pipeline tile is not connected to any battery (it may
still be joined to other dead tiles) — shown grey in the game.

Not brute force (4^N is intractable). Per candidate tile O:
    - each cell's SHAPE is fixed; only its ROTATION varies, over the
      distinct connector patterns of that shape (a straight pipe has 2).
    - the search runs on O's own component only, cropped to its bounding
      box. This is sound because meet_map is tight (every open connector
      is matched), so solved components never touch each other. Re-routes
      that pass through a neighbouring component are NOT explored.
    - backtracking; after each step, prune if some target can't reach a
      battery even optimistically — power may only pass through a cell in
      a way one of its rotations allows (a straight pipe can't turn) and
      never through O — or if O is already provably powered.
    - a full assignment found = a real win state with O unused.

The search itself runs in C: tools/orphan_solver.c, built with
`make build-solver`. This file prepares the levels, drives the solver and
stores results. Step limits per tile, passed to the solver at run time (no
rebuild needed after changing them):
    DEFAULT_BUDGET      (--budget)        until an orphan is found; a tile past
                                          it stops the check: 'limit achieved'
    AFTER_ORPHAN_BUDGET (--found-budget)  after that; a tile past it stops the
                                          check, the level stays 'failed'

Usage:
    python3 tools/orphan_checker.py levels/level_041.json
    python3 tools/orphan_checker.py 41 --write          # store result in metadata
    python3 tools/orphan_checker.py --write             # all levels, in parallel
    python3 tools/orphan_checker.py levels/level_041.json --cell 3,4
"""
import argparse
import functools
import glob
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.config as config

# search steps allowed per tile; the first tile past it stops the check
# (orphan_unresolved = that tile, level status: 'limit achieved')
DEFAULT_BUDGET = 1_000_000_000
# once an orphan is found the level is failed anyway: keep checking only while
# tiles are cheap — the first tile past this many steps stops the check
AFTER_ORPHAN_BUDGET = 10_000_000

U, R, D, L = 0, 1, 2, 3
OPP = {U: D, D: U, L: R, R: L}
DELTA = {U: (-1, 0), D: (1, 0), L: (0, -1), R: (0, 1)}


def rotate_matrix(m):
    transposed = list(zip(*m))
    return [list(row)[::-1] for row in transposed]


def matrix_to_pattern(m):
    # (U, R, D, L) booleans, matching MatrixFrame.has_connector
    return (bool(m[0][1]), bool(m[1][2]), bool(m[2][1]), bool(m[1][0]))


def shape_domains():
    """name -> list of distinct connector patterns reachable by rotation."""
    domains = {}
    for name, base in config.frames.items():
        m = [row[:] for row in base]
        seen = []
        for _ in range(4):
            p = matrix_to_pattern(m)
            if p not in seen:
                seen.append(p)
            m = rotate_matrix(m)
        domains[name] = seen
    return domains


DOMAINS = shape_domains()


def load_level(path, map_key):
    data = json.load(open(path))
    grid = data[map_key]
    cells = []
    for row in grid:
        cells.append([tuple(c.split(':')) for c in row])  # (name, rotation, type)
    return cells


class Level:
    def __init__(self, cells):
        self.rows = len(cells)
        self.cols = len(cells[0])
        self.name = [[cells[i][j][0] for j in range(self.cols)] for i in range(self.rows)]
        self.type = [[cells[i][j][2] for j in range(self.cols)] for i in range(self.rows)]
        self.n = self.rows * self.cols
        self.batteries = [self.idx(i, j) for i in range(self.rows) for j in range(self.cols)
                           if self.type[i][j] == 'battery']
        self.targets = [self.idx(i, j) for i in range(self.rows) for j in range(self.cols)
                         if self.type[i][j] == 'target']
        self.neighbors = [[None, None, None, None] for _ in range(self.n)]  # by direction
        for i in range(self.rows):
            for j in range(self.cols):
                idx = self.idx(i, j)
                for d, (di, dj) in DELTA.items():
                    ni, nj = i + di, j + dj
                    if 0 <= ni < self.rows and 0 <= nj < self.cols:
                        self.neighbors[idx][d] = self.idx(ni, nj)

    def idx(self, i, j):
        return i * self.cols + j

    def base_domain(self, idx):
        i, j = divmod(idx, self.cols)
        return DOMAINS[self.name[i][j]]


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


# ── the search: tools/orphan_solver (C) ──────────────────────────────────────

SOLVER_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orphan_solver')


def c_engine_available():
    """True once `make build-solver` has produced tools/orphan_solver."""
    return os.path.isfile(SOLVER_BIN) and os.access(SOLVER_BIN, os.X_OK)


def _mask(pattern):
    return sum(1 << d for d in (U, R, D, L) if pattern[d])


def _pattern(mask):
    return tuple(bool(mask >> d & 1) for d in (U, R, D, L))


class CSolver:
    """tools/orphan_solver running as a child process for one CheckJob.run().
    try_orphan(): is there a win state with the candidate tile unpowered?
    Returns None (no), 'TIMEOUT' (step budget exceeded, no orphan found yet),
    'STOP' (found_budget exceeded after an orphan was found) or the win state
    as {cell index: pattern}. Both budgets are sent with every query, so
    changing them needs no rebuild."""

    def __init__(self):
        if not c_engine_available():
            raise RuntimeError("C solver not built — run: make build-solver")
        self.proc = subprocess.Popen([SOLVER_BIN], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)

    def try_orphan(self, level, cell_idx, node_budget, found_budget, comp_id, orig_patterns,
                   on_progress=None):
        base = [level.base_domain(i) for i in range(level.n)]
        my_comp = comp_id[cell_idx]
        lines = [f"Q {level.rows} {level.cols} {cell_idx} {node_budget} {found_budget}"]
        for k in range(level.n):
            dom = [orig_patterns[k]] if comp_id[k] != my_comp else base[k]
            t = level.type[k // level.cols][k % level.cols]
            code = 1 if t == 'battery' else 2 if t == 'target' else 0
            lines.append(f"{code} {len(dom)} " + " ".join(str(_mask(p)) for p in dom))
        self.proc.stdin.write("\n".join(lines) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("orphan_solver exited unexpectedly")
            f = line.split()
            if f[0] == 'P':
                if on_progress:
                    on_progress(int(f[1]))
            elif f[0] == 'R':
                if f[1] == 'ok':
                    return None
                if f[1] == 'timeout':
                    return 'TIMEOUT'
                if f[1] == 'stop':
                    return 'STOP'
                return {i: _pattern(int(m)) for i, m in enumerate(f[3:])}

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()


def crop_component(cells, level, comp_id, root):
    """Sub-level holding one component's bounding box; cells of other
    components become analysis-only walls. Valid because every level's
    meet_map is tight (each open connector is matched), so in the solved
    state components never touch each other.
    Returns (sub_level, sub_patterns, offset)."""
    members = [k for k in range(level.n) if comp_id[k] == root]
    rs = [k // level.cols for k in members]
    cs = [k % level.cols for k in members]
    r0, r1, c0, c1 = min(rs), max(rs), min(cs), max(cs)
    grid = []
    for i in range(r0, r1 + 1):
        grid.append([cells[i][j] if comp_id[level.idx(i, j)] == root else ('w', '0', 'pipeline')
                     for j in range(c0, c1 + 1)])
    sub = Level(grid)
    return sub, patterns_of(grid), (r0, c0)


def patterns_of(cells):
    out = []
    for row in cells:
        for name, rot, _ in row:
            m = [r[:] for r in config.frames[name]]
            for _ in range(int(rot) // 90):
                m = rotate_matrix(m)
            out.append(matrix_to_pattern(m))
    return out


def unused_in(level, assignment, comp_mask):
    """Pipeline cells of the searched component (comp_mask == 0) that a win
    state `assignment` (idx -> pattern) leaves unpowered."""
    dsu = DSU(level.n)
    for a, pa in assignment.items():
        for d in (R, D):
            b = level.neighbors[a][d]
            if b is not None and b in assignment and pa[d] and assignment[b][OPP[d]]:
                dsu.union(a, b)
    powered = {dsu.find(b) for b in level.batteries}
    out = []
    for x in range(level.n):
        i, j = divmod(x, level.cols)
        if comp_mask[x] != 0 or level.type[i][j] != 'pipeline' or level.name[i][j] == 'w':
            continue
        if dsu.find(x) not in powered:
            out.append(x)
    return out


class CheckJob:
    """A prepared check of one level. `total` candidate tiles; iterate
    `run()` to check them one by one (lets callers show progress / stop)."""

    def __init__(self, level_path, budget=DEFAULT_BUDGET, only_cell=None,
                 found_budget=AFTER_ORPHAN_BUDGET):
        self.budget = budget
        self.found_budget = found_budget
        cells = load_level(level_path, 'meet_map')
        level = Level(cells)
        self.level = level

        # sanity check on the solved map: all targets powered, no dangling connectors
        pats = patterns_of(cells)
        dsu = DSU(level.n)
        self.dangling = 0
        for a in range(level.n):
            for d in (U, R, D, L):
                if not pats[a][d]:
                    continue
                b = level.neighbors[a][d]
                if b is None or not pats[b][OPP[d]]:
                    self.dangling += 1
                elif d in (R, D):
                    dsu.union(a, b)
        battery_roots = {dsu.find(x) for x in level.batteries}
        self.all_targets_ok = all(dsu.find(t) in battery_roots for t in level.targets)

        # candidates: (global cell, cropped sub-level, index in it, mask, patterns)
        self.candidates = []
        if self.dangling:
            return  # per-component check would be unsound
        comp_id = [dsu.find(x) for x in range(level.n)]
        for root in sorted(set(comp_id)):
            sub, sub_pats, (r0, c0) = crop_component(cells, level, comp_id, root)
            # 0 = cell of this component (searched), anything else = pinned
            sub_comp = [0 if comp_id[level.idx(k // sub.cols + r0, k % sub.cols + c0)] == root
                        else k + 1 for k in range(sub.n)]
            for k in range(sub.n):
                i, j = divmod(k, sub.cols)
                gi, gj = i + r0, j + c0
                if sub_comp[k] != 0 or sub.type[i][j] != 'pipeline' or sub.name[i][j] == 'w':
                    continue
                if only_cell is not None and (gi, gj) != only_cell:
                    continue
                self.candidates.append(((gi, gj), sub, k, sub_comp, sub_pats))

    @property
    def total(self):
        return len(self.candidates)

    def run(self, on_progress=None):
        """Yields ((row, col), shape, status), status in 'ok' | 'unused' | 'timeout'
        | 'stopped' ('timeout' and 'stopped' end the run: 'stopped' = a tile got
        too expensive after an orphan was already found).
        on_progress((row, col), steps) is called when a tile starts (steps=0)
        and every 65536 search steps while it is being checked."""
        csolver = CSolver()
        try:
            yield from self._run(on_progress, csolver)
        finally:
            csolver.close()

    def _run(self, on_progress, csolver):
        known_unused = set()   # (row, col) proven by an earlier witness
        for (gi, gj), sub, k, sub_comp, sub_pats in self.candidates:
            shape = sub.name[k // sub.cols][k % sub.cols]
            if (gi, gj) in known_unused:
                yield (gi, gj), shape, 'unused'
                continue
            if on_progress:
                on_progress((gi, gj), 0)
            progress = (lambda n, c=(gi, gj): on_progress(c, n)) if on_progress else None
            result = csolver.try_orphan(sub, k, self.budget, self.found_budget,
                                        sub_comp, sub_pats, on_progress=progress)
            if result and result not in ('TIMEOUT', 'STOP'):
                r0, c0 = gi - k // sub.cols, gj - k % sub.cols
                known_unused |= {(r0 + x // sub.cols, c0 + x % sub.cols)
                                 for x in unused_in(sub, result, sub_comp)}
            status = {'TIMEOUT': 'timeout', 'STOP': 'stopped'}.get(result) if isinstance(result, str) \
                else ('unused' if result else 'ok')
            yield (gi, gj), shape, status
            if status in ('timeout', 'stopped'):
                return   # limit achieved / level already failed: stop here


def level_paths(args):
    """Positional args -> level files. '41' -> levels/level_041.json; none -> all levels."""
    levels_dir = os.path.join(ROOT, 'levels')
    if not args:
        return sorted(glob.glob(os.path.join(levels_dir, 'level_*.json')))
    return [os.path.join(levels_dir, f"level_{int(a):03d}.json") if a.isdigit() else a
            for a in args]


def check_file(path, budget=DEFAULT_BUDGET, found_budget=AFTER_ORPHAN_BUDGET):
    """Full unpowered-mode check of one level file (for batch runs)."""
    t0 = time.time()
    try:
        mtime = os.path.getmtime(path)
        job = CheckJob(path, budget, found_budget=found_budget)
        if job.dangling:
            return {'path': path, 'error': 'meet_map has unmatched connectors'}
        unused, timeouts, stopped = [], [], False
        for cell, _shape, status in job.run():
            if status == 'unused':
                unused.append(cell)
            elif status == 'timeout':
                timeouts.append(cell)
            elif status == 'stopped':
                stopped = True
        return {'path': path, 'mtime': mtime, 'unused': unused, 'timeouts': timeouts,
                'stopped': stopped, 'elapsed': time.time() - t0, 'error': None}
    except Exception as e:
        return {'path': path, 'error': str(e)}


def summarize(res):
    """One-line summary of a check_file() result."""
    name = os.path.splitext(os.path.basename(res['path']))[0]
    if res['error']:
        return f"{name}: error — {res['error']}"
    fmt = lambda cells: " ".join(f"({r},{c})" for r, c in cells)
    took = f"{res['elapsed']:.1f}s"
    if res['unused']:
        early = " — stopped early, more may exist" if res.get('stopped') else ""
        return f"{name}: failed — {fmt(res['unused'])}{early} ({took})"
    if res['timeouts']:
        return f"{name}: limit achieved on tile {fmt(res['timeouts'])} — check stopped ({took})"
    return f"{name}: success ({took})"


def store_result(res):
    """Write a check_file() result into the level's metadata, unless the file
    changed while it was being checked. Returns a one-line summary."""
    from generate import write_orphan_check
    if res['error']:
        return summarize(res)
    if os.path.getmtime(res['path']) != res['mtime']:
        name = os.path.splitext(os.path.basename(res['path']))[0]
        return f"{name}: changed during the check, not saved"
    write_orphan_check(res['path'], res['unused'], res['timeouts'])
    return summarize(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('levels', nargs='*',
                    help="level files or numbers (41 -> levels/level_041.json); default: all")
    ap.add_argument('--write', action='store_true',
                    help='store the result in each level\'s metadata (orphan_check)')
    ap.add_argument('--jobs', type=int, default=os.cpu_count(),
                    help='levels checked in parallel (batch mode)')
    ap.add_argument('--cell', default=None, help='row,col to test a single cell')
    ap.add_argument('--budget', type=int, default=DEFAULT_BUDGET,
                    help='search steps allowed per tile before it counts as unresolved')
    ap.add_argument('--found-budget', type=int, default=AFTER_ORPHAN_BUDGET,
                    help='steps allowed per tile once an orphan was found; past it the check stops')
    ap.add_argument('--verbose', action='store_true', help='also list tiles that are fine')
    args = ap.parse_args()
    paths = level_paths(args.levels)
    if not c_engine_available():
        ap.error('C solver not built — run: make build-solver')

    if args.write and args.cell:
        ap.error('--write stores full checks only (no --cell)')

    if len(paths) > 1:
        if args.cell:
            ap.error('--cell needs a single level')
        import multiprocessing
        t0 = time.time()
        print(f"Checking {len(paths)} levels, {args.jobs} in parallel...")
        with multiprocessing.Pool(args.jobs) as pool:
            for res in pool.imap_unordered(functools.partial(check_file, budget=args.budget,
                                                             found_budget=args.found_budget), paths):
                print(store_result(res) if args.write else summarize(res), flush=True)
        print(f"Done in {time.time() - t0:.1f}s")
        return

    path = paths[0]
    t0 = time.time()
    only = tuple(map(int, args.cell.split(','))) if args.cell else None
    job = CheckJob(path, args.budget, only, found_budget=args.found_budget)
    lv = job.level
    print(f"Grid {lv.rows}x{lv.cols}, "
          f"{len(lv.batteries)} batteries, {len(lv.targets)} targets, "
          f"{lv.n - len(lv.batteries) - len(lv.targets)} pipeline cells")
    print(f"Solved map: all targets powered = {job.all_targets_ok}, "
          f"dangling connectors = {job.dangling}")
    if job.dangling:
        print("meet_map is not tight; per-component check would be unsound. Aborting.")
        sys.exit(1)

    mtime = os.path.getmtime(path)
    unused, timeouts = [], []
    for (gi, gj), shape, status in job.run():
        if status == 'timeout':
            timeouts.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: search budget exceeded, inconclusive")
        elif status == 'unused':
            unused.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: WITNESS FOUND — a valid win state "
                  f"exists where this tile is unpowered")
        elif status == 'stopped':
            print(f"cell ({gi},{gj}) [{shape}]: over {args.found_budget} steps after an orphan "
                  f"was found — check stopped, more orphans may exist")
        elif args.verbose:
            print(f"cell ({gi},{gj}) [{shape}]: can't be left unused")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Degenerate-win witness found: {bool(unused)}")
    if args.write:
        print(store_result({'path': path, 'mtime': mtime, 'unused': unused,
                            'timeouts': timeouts, 'elapsed': elapsed, 'error': None}))


if __name__ == '__main__':
    main()
