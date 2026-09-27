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

Engines: the same search exists in Python (Solver below) and in C
(tools/orphan_solver.c, built with `make build-solver`). --engine auto uses C
when it is built. The step budget (DEFAULT_BUDGET / --budget) is passed to the
C solver at run time — no rebuild needed after changing it.

Usage:
    python3 tools/orphan_checker.py levels/level_041.json
    python3 tools/orphan_checker.py 41 --write          # store result in metadata
    python3 tools/orphan_checker.py --write             # all levels, in parallel
    python3 tools/orphan_checker.py levels/level_041.json --cell 3,4
    python3 tools/orphan_checker.py levels/level_041.json --mode isolated
    python3 tools/orphan_checker.py 41 --engine py      # force the Python search
"""
import argparse
import functools
import glob
import json
import os
import subprocess
import sys
import time
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.config as config

# search steps allowed per tile; the first tile past it stops the check
# (orphan_unresolved = that tile, level status: 'limit achieved')
DEFAULT_BUDGET = 10_000_000

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

    def __init__(self, level: Level, domains, node_budget=300_000, unpowered=None,
                 on_progress=None):
        self.lv = level
        self.domains = domains  # list[list[pattern]] per cell
        self.node_budget = node_budget
        self.nodes = 0
        self.unpowered = unpowered  # cell idx that must end up NOT connected to any battery
        self.on_progress = on_progress  # called with the step count every 1000 steps

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
            # the candidate must stay unpowered, so no power path may pass through it
            if self.unpowered is not None and self.unpowered in (a, b):
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
                b = lv.neighbors[a][d]
                if b is None:
                    continue
                if edge_possible(a, d):
                    dsu.union(a, b)
                # definite edges include the candidate's own (real) connections
                if sure and side_state(a, d) is True and side_state(b, OPP[d]) is True:
                    sure.union(a, b)
        battery_roots = {dsu.find(b) for b in lv.batteries}
        if not all(dsu.find(t) in battery_roots for t in lv.targets):
            return False
        if not self._directional_reach(assigned):
            return False
        if sure:
            o = sure.find(self.unpowered)
            if any(sure.find(b) == o for b in lv.batteries):
                return False  # candidate is already provably powered
        return True

    def _directional_reach(self, assigned):
        """Stronger relaxation: power travels cell to cell; entering a cell
        from side e it can only leave through side x if one of the cell's
        remaining rotations opens both e and x (a straight pipe can't turn,
        a corner must turn, a lamp/battery is a dead end). Every lamp must
        still be reachable this way, avoiding the tile that must stay unpowered."""
        lv, O = self.lv, self.unpowered
        pats = lambda i: (assigned[i],) if i in assigned else self.domains[i]
        seen, reached, stack = set(), set(lv.batteries), []
        def enter(n, e):
            if n is None or n == O or (n, e) in seen:
                return
            if any(p[e] for p in pats(n)):
                seen.add((n, e))
                stack.append((n, e))
        for b in lv.batteries:
            for d in (U, R, D, L):
                if any(p[d] for p in pats(b)):
                    enter(lv.neighbors[b][d], OPP[d])
        while stack:
            n, e = stack.pop()
            reached.add(n)
            P = pats(n)
            for x in (U, R, D, L):
                if x != e and any(p[e] and p[x] for p in P):
                    enter(lv.neighbors[n][x], OPP[x])
        return all(t in reached for t in lv.targets)

    def solve(self, forced=None):
        """forced: dict idx -> pattern (already decided, e.g. the candidate O)."""
        lv = self.lv
        assigned = dict(forced) if forced else {}
        order = [i for i in range(lv.n) if i not in assigned]

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
            if self.on_progress and self.nodes % 1000 == 0:
                self.on_progress(self.nodes)
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
               mode='unpowered', verbose=False, on_progress=None):
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
        solver = Solver(level, domains, node_budget=node_budget, unpowered=cell_idx,
                        on_progress=on_progress)
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

        solver = Solver(level, domains, node_budget=node_budget, on_progress=on_progress)
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


# ── C engine: tools/orphan_solver (same search, compiled) ────────────────────

SOLVER_BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orphan_solver')


def c_engine_available():
    """True once `make build-solver` has produced tools/orphan_solver."""
    return os.path.isfile(SOLVER_BIN) and os.access(SOLVER_BIN, os.X_OK)


def resolve_engine(engine):
    """'auto' -> 'c' when the C solver is built, else 'py'."""
    if engine == 'auto':
        return 'c' if c_engine_available() else 'py'
    return engine


def _mask(pattern):
    return sum(1 << d for d in (U, R, D, L) if pattern[d])


def _pattern(mask):
    return tuple(bool(mask >> d & 1) for d in (U, R, D, L))


class CSolver:
    """tools/orphan_solver running as a child process for one CheckJob.run().
    try_orphan() mirrors the Python try_orphan() in unpowered mode; the step
    budget is sent with every query, so changing it needs no rebuild."""

    def __init__(self):
        self.proc = subprocess.Popen([SOLVER_BIN], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True, bufsize=1)

    def try_orphan(self, level, cell_idx, node_budget, comp_id, orig_patterns,
                   on_progress=None):
        base = [level.base_domain(i) for i in range(level.n)]
        my_comp = comp_id[cell_idx]
        lines = [f"Q {level.rows} {level.cols} {cell_idx} {node_budget}"]
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


def unused_in(level, assignment, comp_mask, mode):
    """Pipeline cells of the searched component (comp_mask == 0) that a win
    state `assignment` (idx -> pattern) leaves unpowered / isolated."""
    dsu = DSU(level.n)
    deg = [0] * level.n
    for a, pa in assignment.items():
        for d in (R, D):
            b = level.neighbors[a][d]
            if b is not None and b in assignment and pa[d] and assignment[b][OPP[d]]:
                dsu.union(a, b)
                deg[a] += 1
                deg[b] += 1
    powered = {dsu.find(b) for b in level.batteries}
    out = []
    for x in range(level.n):
        i, j = divmod(x, level.cols)
        if comp_mask[x] != 0 or level.type[i][j] != 'pipeline' or level.name[i][j] == 'w':
            continue
        if (deg[x] == 0) if mode == 'isolated' else (dsu.find(x) not in powered):
            out.append(x)
    return out


class CheckJob:
    """A prepared check of one level. `total` candidate tiles; iterate
    `run()` to check them one by one (lets callers show progress / stop)."""

    def __init__(self, level_path, budget=DEFAULT_BUDGET, mode='unpowered', only_cell=None,
                 engine='auto'):
        self.budget, self.mode = budget, mode
        # 'py' | 'c' — the C solver only implements unpowered mode
        self.engine = resolve_engine(engine) if mode == 'unpowered' else 'py'
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

    def run(self, verbose=False, on_progress=None):
        """Yields ((row, col), shape, status), status in 'ok' | 'unused' | 'timeout'.
        on_progress((row, col), steps) is called when a tile starts (steps=0)
        and every 1000 search steps while it is being checked."""
        csolver = CSolver() if self.engine == 'c' else None
        try:
            yield from self._run(verbose, on_progress, csolver)
        finally:
            if csolver:
                csolver.close()

    def _run(self, verbose, on_progress, csolver):
        known_unused = set()   # (row, col) proven by an earlier witness
        for (gi, gj), sub, k, sub_comp, sub_pats in self.candidates:
            shape = sub.name[k // sub.cols][k % sub.cols]
            if (gi, gj) in known_unused:
                yield (gi, gj), shape, 'unused'
                continue
            if on_progress:
                on_progress((gi, gj), 0)
            progress = (lambda n, c=(gi, gj): on_progress(c, n)) if on_progress else None
            if csolver:
                result = csolver.try_orphan(sub, k, self.budget, sub_comp, sub_pats,
                                            on_progress=progress)
            else:
                result = try_orphan(sub, k, self.budget, sub_comp, sub_pats,
                                    mode=self.mode, verbose=verbose, on_progress=progress)
            if result and result != 'TIMEOUT':
                r0, c0 = gi - k // sub.cols, gj - k % sub.cols
                known_unused |= {(r0 + x // sub.cols, c0 + x % sub.cols)
                                 for x in unused_in(sub, result, sub_comp, self.mode)}
            status = 'timeout' if result == 'TIMEOUT' else ('unused' if result else 'ok')
            yield (gi, gj), shape, status
            if status == 'timeout':
                return   # limit achieved: no success is possible any more, stop here


def level_paths(args):
    """Positional args -> level files. '41' -> levels/level_041.json; none -> all levels."""
    levels_dir = os.path.join(ROOT, 'levels')
    if not args:
        return sorted(glob.glob(os.path.join(levels_dir, 'level_*.json')))
    return [os.path.join(levels_dir, f"level_{int(a):03d}.json") if a.isdigit() else a
            for a in args]


def check_file(path, budget=DEFAULT_BUDGET, engine='auto'):
    """Full unpowered-mode check of one level file (for batch runs)."""
    t0 = time.time()
    try:
        mtime = os.path.getmtime(path)
        job = CheckJob(path, budget, engine=engine)
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
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--mode', default='unpowered', choices=['unpowered', 'isolated'])
    ap.add_argument('--engine', default='auto', choices=['auto', 'py', 'c'],
                    help='search engine; auto = C when built (make build-solver), else Python')
    args = ap.parse_args()
    paths = level_paths(args.levels)
    if args.engine == 'c' and not c_engine_available():
        ap.error('C solver not built — run: make build-solver')

    if args.write and (args.cell or args.mode != 'unpowered'):
        ap.error('--write stores full unpowered checks only (no --cell / --mode isolated)')

    if len(paths) > 1:
        if args.cell:
            ap.error('--cell needs a single level')
        import multiprocessing
        t0 = time.time()
        print(f"Checking {len(paths)} levels, {args.jobs} in parallel...")
        with multiprocessing.Pool(args.jobs) as pool:
            for res in pool.imap_unordered(functools.partial(check_file, budget=args.budget,
                                                             engine=args.engine), paths):
                print(store_result(res) if args.write else summarize(res), flush=True)
        print(f"Done in {time.time() - t0:.1f}s")
        return

    path = paths[0]
    t0 = time.time()
    only = tuple(map(int, args.cell.split(','))) if args.cell else None
    job = CheckJob(path, args.budget, args.mode, only, engine=args.engine)
    lv = job.level
    print(f"Engine: {'C (tools/orphan_solver)' if job.engine == 'c' else 'Python'}")
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
