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
import collections
import functools
import glob
import json
import os
import selectors
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
# tiles are cheap — tiles past this many steps are dropped ('orphan_stopped')
AFTER_ORPHAN_BUDGET = 10_000_000
# tiles of one level searched at the same time (one C solver process each)
PARALLEL_TILES = 20
# while a check runs, tiles proven fine are saved to metadata this often (s)
PROGRESS_EVERY = 2.0
# per-level log of every tile: logs/orphans/level_NNN.log
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       'logs', 'orphans')

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
    """tools/orphan_solver as a child process. One query at a time:
    send() a tile, then read_events() as its stdout becomes readable (the
    checker runs up to PARALLEL_TILES of these side by side)."""

    def __init__(self):
        if not c_engine_available():
            raise RuntimeError("C solver not built — run: make build-solver")
        self.proc = subprocess.Popen([SOLVER_BIN], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, bufsize=0)
        self.fd = self.proc.stdout.fileno()
        self._buf = b""

    def send(self, level, cell_idx, budget, found_budget, found, comp_id, orig_patterns):
        """Ask: is there a win state with tile `cell_idx` unpowered? All budgets
        go with every query, so changing them needs no rebuild."""
        base = [level.base_domain(i) for i in range(level.n)]
        my_comp = comp_id[cell_idx]
        lines = [f"Q {level.rows} {level.cols} {cell_idx} {budget} {found_budget} {int(found)}"]
        for k in range(level.n):
            dom = [orig_patterns[k]] if comp_id[k] != my_comp else base[k]
            t = level.type[k // level.cols][k % level.cols]
            code = 1 if t == 'battery' else 2 if t == 'target' else 0
            lines.append(f"{code} {len(dom)} " + " ".join(str(_mask(p)) for p in dom))
        self.proc.stdin.write(("\n".join(lines) + "\n").encode())
        self.proc.stdin.flush()

    def read_events(self):
        """Events available now: ('progress', steps) or ('result', value, steps);
        value: None (no orphan), 'TIMEOUT', 'STOP' or the win state
        {cell index: pattern}."""
        data = os.read(self.fd, 1 << 16)
        if not data:
            raise RuntimeError("orphan_solver exited unexpectedly")
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        events = []
        for line in lines:
            f = line.decode().split()
            if not f:
                continue
            if f[0] == 'P':
                events.append(('progress', int(f[1])))
            elif f[0] == 'R':
                value = {'ok': None, 'timeout': 'TIMEOUT', 'stop': 'STOP'}.get(f[1], 'unused')
                if value == 'unused':
                    value = {i: _pattern(int(m)) for i, m in enumerate(f[3:])}
                events.append(('result', value, int(f[2])))
        return events

    def kill(self):
        try:
            self.proc.kill()
            self.proc.wait(timeout=2)
        except Exception:
            pass

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except Exception:
            self.kill()


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


def log_path_for(level_path):
    """logs/orphans/<level>.log"""
    return os.path.join(LOG_DIR, os.path.splitext(os.path.basename(level_path))[0] + '.log')


class CheckJob:
    """A prepared check of one level. `total` candidate tiles; iterate
    `run()` to get each tile's result as it finishes."""

    def __init__(self, level_path, budget=DEFAULT_BUDGET, only_cell=None,
                 found_budget=AFTER_ORPHAN_BUDGET, parallel=PARALLEL_TILES, log_path=None,
                 resume=True, persist=False):
        """resume:  skip tiles an earlier (unfinished) check already settled —
                    metadata orphan_ok / orphan_cells, valid while the level's
                    tile shapes are unchanged.
        persist: record progress in the level's metadata while running
                    (every PROGRESS_EVERY seconds), so a stopped check resumes."""
        from generate import level_shapes, parse_cells
        self.budget = budget
        self.found_budget = found_budget
        self.parallel = max(1, parallel)
        self.level_path = level_path
        self.log_path = log_path
        self.persist = persist
        self.shapes = level_shapes(level_path)   # what the result is valid for
        self.prior_ok, self.prior_unused = set(), set()
        if resume:
            meta = json.load(open(level_path)).get('metadata', {})
            self.prior_ok = set(parse_cells(meta.get('orphan_ok')))
            self.prior_unused = set(parse_cells(meta.get('orphan_cells')))
        self.ok_cells, self.unused_cells = set(), set()   # filled by run()
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
        """Yields ((row, col), shape, status) as tiles finish (not in order);
        status: 'ok' | 'unused' | 'timeout' | 'stopped'.

        Up to `parallel` tiles are searched at once, one C solver each.
          - 'unused'  : the tile can stay unpowered in a win state. Tiles left
                        unpowered in that same win state count as 'unused' too
                        (running ones are cut short).
          - after the first orphan the level is failed: new tiles get
            found_budget, and running tiles past it are dropped as 'stopped'.
          - 'timeout' : a tile hit `budget` with no orphan found: everything
                        stops (level: 'limit achieved').
        on_progress((row, col), steps) is called when a tile starts (steps=0)
        and every 65536 search steps while it runs. With log_path set, every
        tile is written to that log. Tiles settled by an earlier run (resume)
        are yielded first without searching."""
        sel = selectors.DefaultSelector()
        idle, busy, every = [], {}, []   # busy: solver -> [candidate, started, steps]
        pending = collections.deque(self.candidates)
        known_unused, found = set(), False
        t0 = time.time()
        log = None
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            log = open(self.log_path, 'w')
            log.write(f"{os.path.basename(self.level_path)} — {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                      f"tiles {self.total}, parallel {self.parallel}, budget {self.budget:,}, "
                      f"after orphan {self.found_budget:,}\n\n")
        counts = collections.Counter()
        last_save = [time.time()]

        def save_progress(force=False):
            if self.persist and (force or time.time() - last_save[0] >= PROGRESS_EVERY):
                from generate import write_orphan_progress
                write_orphan_progress(self.level_path, self.shapes,
                                      self.ok_cells, self.unused_cells)
                last_save[0] = time.time()

        def spawn():
            s = CSolver()
            sel.register(s.fd, selectors.EVENT_READ, s)
            every.append(s)
            return s

        def retire(s):
            """Kill a solver in the middle of a tile and put a fresh one in its place."""
            sel.unregister(s.fd)
            s.kill()
            every.remove(s)
            idle.append(spawn())

        def done(cand, status, steps, started):
            (gi, gj), sub, k = cand[0], cand[1], cand[2]
            shape = sub.name[k // sub.cols][k % sub.cols]
            counts[status] += 1
            if status == 'ok':
                self.ok_cells.add((gi, gj))
            elif status == 'unused':
                self.unused_cells.add((gi, gj))
            save_progress()
            if log:
                took = f"{time.time() - started:8.1f}s" if started else " (earlier/witness)"
                log.write(f"{time.time() - t0:8.1f}s  ({gi},{gj}) {shape}  {status:8} "
                          f"steps {steps:>15,}  took {took}\n")
                log.flush()
            return (gi, gj), shape, status

        def cut_short(cells, status):
            """Stop running tiles whose cell is in `cells` (a predicate)."""
            for s, (cand, started, steps) in list(busy.items()):
                if cells(cand, steps):
                    del busy[s]
                    retire(s)
                    yield done(cand, status, steps, started)

        try:
            # resume: tiles an earlier check already settled
            for cand in list(pending):
                if cand[0] in self.prior_ok or cand[0] in self.prior_unused:
                    pending.remove(cand)
                    status = 'ok' if cand[0] in self.prior_ok else 'unused'
                    if status == 'unused':
                        known_unused.add(cand[0])
                        found = True
                    yield done(cand, status, 0, None)
            for _ in range(min(self.parallel, max(1, len(pending)))):
                idle.append(spawn())
            while pending or busy:
                while idle and pending:
                    cand = pending.popleft()
                    if cand[0] in known_unused:
                        yield done(cand, 'unused', 0, None)
                        continue
                    (gi, gj), sub, k, sub_comp, sub_pats = cand
                    s = idle.pop()
                    s.send(sub, k, self.budget, self.found_budget, found, sub_comp, sub_pats)
                    busy[s] = [cand, time.time(), 0]
                    if on_progress:
                        on_progress((gi, gj), 0)
                if not busy:
                    continue
                for key, _ in sel.select():
                    s = key.data
                    if s not in busy:
                        continue
                    for ev in s.read_events():
                        cand, started, _steps = busy[s]
                        if ev[0] == 'progress':
                            busy[s][2] = ev[1]
                            if on_progress:
                                on_progress(cand[0], ev[1])
                            if found and ev[1] > self.found_budget:
                                del busy[s]
                                retire(s)
                                yield done(cand, 'stopped', ev[1], started)
                                break
                            continue
                        _, value, steps = ev
                        del busy[s]
                        idle.append(s)
                        if isinstance(value, dict):
                            gi, gj = cand[0]
                            sub, k, sub_comp = cand[1], cand[2], cand[3]
                            r0, c0 = gi - k // sub.cols, gj - k % sub.cols
                            known_unused |= {(r0 + x // sub.cols, c0 + x % sub.cols)
                                             for x in unused_in(sub, value, sub_comp)}
                            yield done(cand, 'unused', steps, started)
                            found = True
                            # tiles proven dead by this win state, and tiles already
                            # too expensive for a failed level, stop right away
                            yield from cut_short(lambda c, n: c[0] in known_unused, 'unused')
                            yield from cut_short(lambda c, n: n > self.found_budget, 'stopped')
                        elif value == 'TIMEOUT' and not found:
                            yield done(cand, 'timeout', steps, started)
                            return   # limit achieved: no success possible, stop everything
                        elif value in ('TIMEOUT', 'STOP'):
                            yield done(cand, 'stopped', steps, started)
                        else:
                            yield done(cand, 'ok', steps, started)
                        break
        finally:
            for s in every:
                if s in busy:
                    s.kill()
                else:
                    s.close()
            sel.close()
            save_progress(force=True)
            if log:
                summary = ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                log.write(f"\nfinished in {time.time() - t0:.1f}s — {summary or 'nothing checked'}\n")
                log.close()


def level_paths(args):
    """Positional args -> level files. '41' -> levels/level_041.json; none -> all levels."""
    levels_dir = os.path.join(ROOT, 'levels')
    if not args:
        return sorted(glob.glob(os.path.join(levels_dir, 'level_*.json')))
    return [os.path.join(levels_dir, f"level_{int(a):03d}.json") if a.isdigit() else a
            for a in args]


def check_file(path, budget=DEFAULT_BUDGET, found_budget=AFTER_ORPHAN_BUDGET,
               parallel=PARALLEL_TILES, fresh=False):
    """Full unpowered-mode check of one level file (for batch runs)."""
    t0 = time.time()
    try:
        job = CheckJob(path, budget, found_budget=found_budget, parallel=parallel,
                       log_path=log_path_for(path), resume=not fresh, persist=True)
        if job.dangling:
            return {'path': path, 'error': 'meet_map has unmatched connectors'}
        unused, timeouts, stopped = [], [], []
        for cell, _shape, status in job.run():
            if status == 'unused':
                unused.append(cell)
            elif status == 'timeout':
                timeouts.append(cell)
            elif status == 'stopped':
                stopped.append(cell)
        return {'path': path, 'unused': sorted(unused), 'ok': sorted(job.ok_cells),
                'timeouts': timeouts, 'stopped': sorted(stopped), 'shapes': job.shapes,
                'elapsed': time.time() - t0, 'error': None}
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
        early = (f" — {len(res['stopped'])} tiles dropped, more may exist"
                 if res.get('stopped') else "")
        return f"{name}: failed — {fmt(res['unused'])}{early} ({took})"
    if res['timeouts']:
        return f"{name}: limit achieved on tile {fmt(res['timeouts'])} — check stopped ({took})"
    return f"{name}: success ({took})"


def store_result(res):
    """Write a check_file() result into the level's metadata, unless the
    level's tiles changed while it was being checked. Returns a one-line summary."""
    from generate import write_orphan_check
    if res['error']:
        return summarize(res)
    if not write_orphan_check(res['path'], res['unused'], res['timeouts'],
                              res.get('stopped', []), res.get('elapsed'),
                              ok=res.get('ok', []), shapes=res.get('shapes')):
        name = os.path.splitext(os.path.basename(res['path']))[0]
        return f"{name}: tiles changed during the check, not saved"
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
                    help='steps allowed per tile once an orphan was found; past it the tile is dropped')
    ap.add_argument('--parallel', type=int, default=PARALLEL_TILES,
                    help='tiles of one level searched at once')
    ap.add_argument('--fresh', action='store_true',
                    help='check every tile again (ignore progress saved by an earlier check)')
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
                                                             found_budget=args.found_budget,
                                                             parallel=args.parallel,
                                                             fresh=args.fresh), paths):
                print(store_result(res) if args.write else summarize(res), flush=True)
        print(f"Done in {time.time() - t0:.1f}s")
        return

    path = paths[0]
    t0 = time.time()
    only = tuple(map(int, args.cell.split(','))) if args.cell else None
    job = CheckJob(path, args.budget, only, found_budget=args.found_budget,
                   parallel=args.parallel, log_path=log_path_for(path),
                   resume=not args.fresh, persist=args.write and not only)
    lv = job.level
    print(f"Grid {lv.rows}x{lv.cols}, "
          f"{len(lv.batteries)} batteries, {len(lv.targets)} targets, "
          f"{lv.n - len(lv.batteries) - len(lv.targets)} pipeline cells")
    print(f"Solved map: all targets powered = {job.all_targets_ok}, "
          f"dangling connectors = {job.dangling}")
    if job.dangling:
        print("meet_map is not tight; per-component check would be unsound. Aborting.")
        sys.exit(1)

    unused, timeouts, stopped = [], [], []
    for (gi, gj), shape, status in job.run():
        if status == 'timeout':
            timeouts.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: search budget exceeded, inconclusive")
        elif status == 'unused':
            unused.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: WITNESS FOUND — a valid win state "
                  f"exists where this tile is unpowered")
        elif status == 'stopped':
            stopped.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: over {args.found_budget} steps after an orphan "
                  f"was found — dropped, not verified")
        elif args.verbose:
            print(f"cell ({gi},{gj}) [{shape}]: can't be left unused")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Degenerate-win witness found: {bool(unused)}")
    if args.write:
        print(store_result({'path': path, 'unused': unused, 'ok': sorted(job.ok_cells),
                            'timeouts': timeouts, 'stopped': stopped, 'shapes': job.shapes,
                            'elapsed': elapsed, 'error': None}))


if __name__ == '__main__':
    main()
