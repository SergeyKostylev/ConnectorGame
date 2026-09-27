"""
Checks whether a level admits a "degenerate win": a rotation assignment where
every target is still connected to a battery (the game's current win
condition), but some pipeline tile is left unused.

    --mode unpowered (default): the tile is not connected to any battery
        (it may still be joined to other dead tiles) — shown grey in game.
    --mode isolated: the tile has zero active connections (stricter).

Not brute force (4^N is intractable). Per candidate tile O:
    - each cell's SHAPE is fixed; only its ROTATION varies, over the
      distinct connector patterns of that shape (a straight pipe has 2).
    - the search runs on O's own component only, cropped to its bounding
      box. This is sound because meet_map is tight (every open connector
      is matched), so solved components never touch each other. Re-routes
      that pass through a neighbouring component are NOT explored.
    - backtracking with MRV ordering; after each step, prune if some target
      can't reach a battery even optimistically (undecided sides assumed
      open), or (unpowered mode) if O is already provably powered.
    - a full assignment found = a real win state with O unused.

Usage:
    python3 tools/orphan_checker.py levels/level_041.json
    python3 tools/orphan_checker.py 41 --write          # store result in metadata
    python3 tools/orphan_checker.py --write             # all levels, in parallel
    python3 tools/orphan_checker.py levels/level_041.json --cell 3,4
    python3 tools/orphan_checker.py levels/level_041.json --mode isolated
"""
import argparse
import functools
import glob
import json
import os
import sys
import time
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.config as config

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


class Solver:
    """Finds a full rotation assignment satisfying target->battery connectivity,
    given a per-cell allowed-domain override (used to force a candidate cell
    into an isolating pattern and forbid its neighbors from matching it)."""

    def __init__(self, level: Level, domains, node_budget=300_000, unpowered=None):
        self.lv = level
        self.domains = domains  # list[list[pattern]] per cell
        self.node_budget = node_budget
        self.nodes = 0
        self.unpowered = unpowered  # cell idx that must end up NOT connected to any battery

    def optimistic_ok(self, assigned):
        """BFS over a graph where an edge is only excluded if it's provably
        impossible (both fixed & mismatched, or one fixed-closed on that
        side and the other side would need to match, or all remaining domain
        options of an unassigned neighbor are closed on that side)."""
        lv = self.lv

        def side_state(idx, d):
            # returns True/False/None (open/closed/unknown) for cell idx's side d
            if idx in assigned:
                return assigned[idx][d]
            dom = self.domains[idx]
            opens = any(p[d] for p in dom)
            closes = any(not p[d] for p in dom)
            if opens and not closes:
                return True
            if closes and not opens:
                return False
            return None  # could be either

        def edge_possible(a, d):
            b = lv.neighbors[a][d]
            if b is None:
                return False
            sa = side_state(a, d)
            sb = side_state(b, OPP[d])
            if sa is False or sb is False:
                return False
            if sa is True and sb is True:
                return True
            return True  # unknown on at least one side -> optimistically possible

        # union-find over optimistic edges (upper bound on connectivity)
        dsu = DSU(lv.n)
        # union-find over definite edges (lower bound on connectivity)
        sure = DSU(lv.n) if self.unpowered is not None else None
        for a in range(lv.n):
            for d in (R, D):  # each undirected edge once
                if edge_possible(a, d):
                    b = lv.neighbors[a][d]
                    dsu.union(a, b)
                    if sure and side_state(a, d) is True and side_state(b, OPP[d]) is True:
                        sure.union(a, b)
        battery_roots = {dsu.find(b) for b in lv.batteries}
        if not all(dsu.find(t) in battery_roots for t in lv.targets):
            return False
        if sure:
            o = sure.find(self.unpowered)
            if any(sure.find(b) == o for b in lv.batteries):
                return False  # candidate is already provably powered
        return True

    def solve(self, forced=None):
        """forced: dict idx -> pattern (already decided, e.g. the candidate O)."""
        lv = self.lv
        assigned = dict(forced) if forced else {}
        order = [i for i in range(lv.n) if i not in assigned]
        # simple static order: farthest-from-nothing first isn't needed; MRV dynamic below.

        if not self.optimistic_ok(assigned):
            return None

        def pick_var():
            best, best_dom = None, None
            for i in order:
                if i in assigned:
                    continue
                dom = self.domains[i]
                if best is None or len(dom) < len(best_dom):
                    best, best_dom = i, dom
            return best

        def backtrack():
            self.nodes += 1
            if self.nodes > self.node_budget:
                raise TimeoutError
            if len(assigned) == lv.n:
                return dict(assigned)
            var = pick_var()
            for pattern in self.domains[var]:
                assigned[var] = pattern
                if self.optimistic_ok(assigned):
                    result = backtrack()
                    if result is not None:
                        return result
                del assigned[var]
            return None

        try:
            return backtrack()
        except TimeoutError:
            return 'TIMEOUT'


def try_orphan(level: Level, cell_idx, node_budget, comp_id, orig_patterns,
               mode='unpowered', verbose=False):
    """Searches for a win state in which cell O is unused.

    mode='unpowered': O is not connected to any battery (it may still be
        joined to other dead tiles) — this is what shows up grey in the game.
    mode='isolated':  O has zero active connections (stricter, faster).

    The search only varies cells of O's own component (as given by the
    source solution) and pins everything else to its solved rotation.
    Any witness found is therefore a real win state; a "no" means no local
    re-routing exists (re-routing through a neighbouring component is not
    explored)."""
    base = [level.base_domain(i) for i in range(level.n)]
    i, j = divmod(cell_idx, level.cols)
    if level.type[i][j] != 'pipeline' or level.name[i][j] == 'w':
        return None  # walls are supposed to have 0 connectors; not a candidate

    my_comp = comp_id[cell_idx]

    if mode == 'unpowered':
        domains = [([orig_patterns[k]] if comp_id[k] != my_comp else list(base[k]))
                   for k in range(level.n)]
        solver = Solver(level, domains, node_budget=node_budget, unpowered=cell_idx)
        result = solver.solve()
        if verbose:
            print(f"    cell {i},{j}: "
                  f"{'TIMEOUT' if result == 'TIMEOUT' else ('FOUND' if result else 'infeasible')} "
                  f"(nodes={solver.nodes})")
        return result

    for pattern in base[cell_idx]:
        # cells outside O's component: pin to their original pattern (safe, see above)
        domains = [([orig_patterns[k]] if comp_id[k] != my_comp else list(base[k]))
                   for k in range(level.n)]
        domains[cell_idx] = [pattern]
        feasible = True
        for d in (U, R, D, L):
            if not pattern[d]:
                continue
            nb = level.neighbors[cell_idx][d]
            if nb is None:
                continue
            side = OPP[d]
            filtered = [p for p in domains[nb] if not p[side]]
            if not filtered:
                feasible = False
                break
            domains[nb] = filtered
        if not feasible:
            continue

        solver = Solver(level, domains, node_budget=node_budget)
        result = solver.solve(forced={cell_idx: pattern})
        if verbose:
            print(f"    cell {i},{j} pattern={pattern}: "
                  f"{'TIMEOUT' if result == 'TIMEOUT' else ('FOUND' if result else 'infeasible')} "
                  f"(nodes={solver.nodes})")
        if result == 'TIMEOUT':
            return 'TIMEOUT'
        if result:
            return result
    return None


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


class CheckJob:
    """A prepared check of one level. `total` candidate tiles; iterate
    `run()` to check them one by one (lets callers show progress / stop)."""

    def __init__(self, level_path, budget=200_000, mode='unpowered', only_cell=None):
        self.budget, self.mode = budget, mode
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

    def run(self, verbose=False):
        """Yields ((row, col), shape, status), status in 'ok' | 'unused' | 'timeout'."""
        for (gi, gj), sub, k, sub_comp, sub_pats in self.candidates:
            result = try_orphan(sub, k, self.budget, sub_comp, sub_pats,
                                mode=self.mode, verbose=verbose)
            status = 'timeout' if result == 'TIMEOUT' else ('unused' if result else 'ok')
            yield (gi, gj), sub.name[k // sub.cols][k % sub.cols], status


def level_paths(args):
    """Positional args -> level files. '41' -> levels/level_041.json; none -> all levels."""
    levels_dir = os.path.join(ROOT, 'levels')
    if not args:
        return sorted(glob.glob(os.path.join(levels_dir, 'level_*.json')))
    return [os.path.join(levels_dir, f"level_{int(a):03d}.json") if a.isdigit() else a
            for a in args]


def check_file(path, budget=200_000):
    """Full unpowered-mode check of one level file (for batch runs)."""
    t0 = time.time()
    try:
        mtime = os.path.getmtime(path)
        job = CheckJob(path, budget)
        if job.dangling:
            return {'path': path, 'error': 'meet_map has unmatched connectors'}
        unused, timeouts = [], []
        for cell, _shape, status in job.run():
            if status == 'unused':
                unused.append(cell)
            elif status == 'timeout':
                timeouts.append(cell)
        return {'path': path, 'mtime': mtime, 'unused': unused, 'timeouts': timeouts,
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
        return f"{name}: failed — {fmt(res['unused'])} ({took})"
    if res['timeouts']:
        return f"{name}: incomplete — gave up at {fmt(res['timeouts'])} ({took})"
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
    ap.add_argument('--budget', type=int, default=200_000)
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--mode', default='unpowered', choices=['unpowered', 'isolated'])
    args = ap.parse_args()
    paths = level_paths(args.levels)

    if args.write and (args.cell or args.mode != 'unpowered'):
        ap.error('--write stores full unpowered checks only (no --cell / --mode isolated)')

    if len(paths) > 1:
        if args.cell:
            ap.error('--cell needs a single level')
        import multiprocessing
        t0 = time.time()
        print(f"Checking {len(paths)} levels, {args.jobs} in parallel...")
        with multiprocessing.Pool(args.jobs) as pool:
            for res in pool.imap_unordered(functools.partial(check_file, budget=args.budget), paths):
                print(store_result(res) if args.write else summarize(res), flush=True)
        print(f"Done in {time.time() - t0:.1f}s")
        return

    path = paths[0]
    t0 = time.time()
    only = tuple(map(int, args.cell.split(','))) if args.cell else None
    job = CheckJob(path, args.budget, args.mode, only)
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
    for (gi, gj), shape, status in job.run(verbose=args.verbose):
        if status == 'timeout':
            timeouts.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: search budget exceeded, inconclusive")
        elif status == 'unused':
            unused.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: WITNESS FOUND — a valid win state "
                  f"exists where this tile is unused ({args.mode})")
        elif args.verbose:
            print(f"cell ({gi},{gj}) [{shape}]: can't be left unused")

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s. Degenerate-win witness found: {bool(unused)}")
    if args.write:
        print(store_result({'path': path, 'mtime': mtime, 'unused': unused,
                            'timeouts': timeouts, 'elapsed': elapsed, 'error': None}))


if __name__ == '__main__':
    main()
