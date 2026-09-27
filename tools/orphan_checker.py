"""
Checks whether a level admits a "degenerate win": a rotation assignment where
every target is connected to a battery (the game's win condition), but some
pipeline tile is not connected to any battery — shown grey in the game.

The whole level is one CP-SAT model (Google OR-Tools): every cell's rotation
is free, chosen from its shape's distinct connector patterns, and any lamp may
be powered by any battery. Cells are NOT split per battery network: a lamp can
borrow power from a neighbouring network, and an earlier per-network search
missed exactly those wins (level 20).

    open[v][d]  side d of cell v is open; the four sides together must equal
                one of the shape's rotations
    act[e]      grid edge e is live: both facing sides open
    pw[v]       cell v is connected to a battery — exactly the reachable set:
                  pw subset of reachable: a powered non-battery needs a live
                      edge to a powered cell of lower rank (no cycle can
                      support itself)
                  reachable subset of pw: a live edge forces both ends equal
    lamps: pw = 1                                     (a win state)

One solve asks for a win state where ANY pipeline tile is unpowered, instead of
one search per tile. Every unpowered pipeline tile in the answer is a real
orphan, so all of them are collected, banned, and the solve repeats.
INFEASIBLE = no tile can ever be left unpowered: the whole "success" proof,
done in one go.

Usage:
    python3 tools/orphan_checker.py levels/level_041.json
    python3 tools/orphan_checker.py 41 --write          # store result in metadata
    python3 tools/orphan_checker.py --write             # all levels, in parallel
"""
import argparse
import functools
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import app.config as config

# seconds one level's solving may take; past it the check reports what it has
# and the remaining tiles stay unresolved (level: 'limit achieved')
DEFAULT_TIME_LIMIT = 120.0
# CP-SAT search threads per level
DEFAULT_WORKERS = 8
# per-level log of every solve: logs/orphans/level_NNN.log
LOG_DIR = os.path.join(ROOT, 'logs', 'orphans')

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

    def rc(self, idx):
        return divmod(idx, self.cols)

    def base_domain(self, idx):
        i, j = divmod(idx, self.cols)
        return DOMAINS[self.name[i][j]]

    def pipeline_cells(self):
        """Cells that could be left unpowered (walls, lamps and batteries can't)."""
        return [v for v in range(self.n)
                if self.type[v // self.cols][v % self.cols] == 'pipeline'
                and self.name[v // self.cols][v % self.cols] != 'w']


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


def patterns_of(cells):
    out = []
    for row in cells:
        for name, rot, _ in row:
            m = [r[:] for r in config.frames[name]]
            for _ in range(int(rot) // 90):
                m = rotate_matrix(m)
            out.append(matrix_to_pattern(m))
    return out


def log_path_for(level_path):
    """logs/orphans/<level>.log"""
    return os.path.join(LOG_DIR, os.path.splitext(os.path.basename(level_path))[0] + '.log')


# ── the model ────────────────────────────────────────────────────────────────

def build_model(level):
    """CP-SAT model of every win state of `level` (all lamps powered).
    Returns (model, pw) — pw[v] is true exactly when v is powered."""
    from ortools.sat.python import cp_model
    m = cp_model.CpModel()
    n = level.n
    open_ = [[m.NewBoolVar(f"o{v}_{d}") for d in range(4)] for v in range(n)]

    for v in range(n):
        i, j = level.rc(v)
        m.AddAllowedAssignments(open_[v],
                                [tuple(int(p[d]) for d in range(4))
                                 for p in DOMAINS[level.name[i][j]]])

    act = {}
    for v in range(n):
        for d in (R, D):                        # each undirected edge once
            u = level.neighbors[v][d]
            if u is None:
                continue
            a = m.NewBoolVar(f"a{v}_{d}")
            m.AddBoolAnd(open_[v][d], open_[u][OPP[d]]).OnlyEnforceIf(a)
            m.AddBoolOr(open_[v][d].Not(), open_[u][OPP[d]].Not()).OnlyEnforceIf(a.Not())
            act[(v, u)] = act[(u, v)] = a

    pw = [m.NewBoolVar(f"p{v}") for v in range(n)]
    lvl = [m.NewIntVar(0, n, f"l{v}") for v in range(n)]
    batteries = set(level.batteries)
    for b in level.batteries:
        m.Add(pw[b] == 1)
        m.Add(lvl[b] == 0)
    for v in range(n):
        if v in batteries:
            continue
        supports = []
        for d in range(4):
            u = level.neighbors[v][d]
            if u is None:
                continue
            sup = m.NewBoolVar(f"s{v}_{d}")     # v is powered through u
            m.AddImplication(sup, act[(v, u)])
            m.AddImplication(sup, pw[u])
            m.Add(lvl[v] == lvl[u] + 1).OnlyEnforceIf(sup)
            m.AddImplication(sup, pw[v])
            supports.append(sup)
        m.AddBoolOr(supports + [pw[v].Not()])
    for (v, u), a in act.items():
        if v < u:
            m.Add(pw[v] == pw[u]).OnlyEnforceIf(a)

    for t in level.targets:
        m.Add(pw[t] == 1)
    return m, pw


class CheckJob:
    """A prepared orphan check of one level.

    `run()` yields ((row, col), shape, status) as results come in:
        'unused'  — the tile can stay unpowered in a win state (a real orphan)
        'ok'      — proven: it never can
        'timeout' — the time limit ran out before that was settled
    Orphans come first, as each solve finds them; the 'ok' tiles all arrive at
    the end, when the final solve proves there are no others."""

    def __init__(self, level_path, time_limit=DEFAULT_TIME_LIMIT, workers=DEFAULT_WORKERS,
                 log_path=None):
        self.level_path = level_path
        self.time_limit = time_limit
        self.workers = workers
        self.log_path = log_path
        self.proved = False
        self.solves = 0
        self.elapsed = 0.0
        self.unused_cells, self.ok_cells = set(), set()

        from generate import level_shapes
        self.shapes = level_shapes(level_path)   # what the result stays valid for
        cells = load_level(level_path, 'meet_map')
        self.level = Level(cells)
        self.candidates = self.level.pipeline_cells()

        # sanity check on the solved map: all lamps powered, no unmatched connectors
        pats = patterns_of(cells)
        dsu = DSU(self.level.n)
        self.dangling = 0
        for a in range(self.level.n):
            for d in (U, R, D, L):
                if not pats[a][d]:
                    continue
                b = self.level.neighbors[a][d]
                if b is None or not pats[b][OPP[d]]:
                    self.dangling += 1
                elif d in (R, D):
                    dsu.union(a, b)
        roots = {dsu.find(x) for x in self.level.batteries}
        self.all_targets_ok = all(dsu.find(t) in roots for t in self.level.targets)

    @property
    def total(self):
        return len(self.candidates)

    def run(self, on_progress=None):
        """on_progress(stage_text) is called as each solve starts."""
        from ortools.sat.python import cp_model
        lv = self.level
        shape = lambda v: lv.name[v // lv.cols][v % lv.cols]
        rc_str = lambda v: f"({lv.rc(v)[0]},{lv.rc(v)[1]})"
        t0 = time.time()
        log = None
        if self.log_path:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            log = open(self.log_path, 'w')
            log.write(f"{os.path.basename(self.level_path)} — "
                      f"{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                      f"{lv.rows}x{lv.cols}, {len(lv.batteries)} batteries, "
                      f"{len(lv.targets)} lamps, {self.total} pipeline tiles\n"
                      f"limit {self.time_limit:g}s, {self.workers} workers\n\n")
        try:
            m, pw = build_model(lv)
            solver = cp_model.CpSolver()
            solver.parameters.num_workers = self.workers
            while True:
                rest = [v for v in self.candidates if v not in self.unused_cells]
                if not rest:
                    self.proved = True
                    break
                # assumption: at least one tile not yet known to be an orphan
                # ends up unpowered; dropping it later retires that witness
                guard = m.NewBoolVar(f"g{self.solves}")
                m.AddBoolOr([pw[v].Not() for v in rest]).OnlyEnforceIf(guard)
                m.ClearAssumptions()
                m.AddAssumption(guard)

                left = self.time_limit - (time.time() - t0)
                if left <= 0:
                    break
                solver.parameters.max_time_in_seconds = left
                self.solves += 1
                if on_progress:
                    on_progress(f"solve {self.solves} · {len(self.unused_cells)} orphans so far")
                st = solver.Solve(m)
                took = time.time() - t0
                if st == cp_model.INFEASIBLE:
                    self.proved = True
                    if log:
                        log.write(f"{took:7.1f}s  solve {self.solves}: proved — no other "
                                  f"tile can be left unpowered\n")
                    break
                if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    if log:
                        log.write(f"{took:7.1f}s  solve {self.solves}: "
                                  f"{solver.StatusName(st)} — time limit\n")
                    break
                found = sorted(v for v in rest if not solver.Value(pw[v]))
                self.unused_cells |= set(found)
                if log:
                    log.write(f"{took:7.1f}s  solve {self.solves}: {len(found)} orphan(s)  "
                              + " ".join(map(rc_str, found)) + "\n")
                    log.flush()
                for v in found:
                    yield lv.rc(v), shape(v), 'unused'
                m.Add(guard == 0)

            rest = [v for v in self.candidates if v not in self.unused_cells]
            if self.proved:
                self.ok_cells = set(rest)
            for v in rest:
                yield lv.rc(v), shape(v), 'ok' if self.proved else 'timeout'
        finally:
            self.elapsed = time.time() - t0
            if log:
                log.write(f"\nfinished in {self.elapsed:.1f}s — {len(self.unused_cells)} "
                          f"orphans, {'proved' if self.proved else 'NOT proved (time limit)'}\n")
                log.close()


# ── levels, batches, CLI ─────────────────────────────────────────────────────

def level_paths(args):
    """Positional args -> level files. '41' -> levels/level_041.json; none -> all levels."""
    levels_dir = os.path.join(ROOT, 'levels')
    if not args:
        return sorted(glob.glob(os.path.join(levels_dir, 'level_*.json')))
    return [os.path.join(levels_dir, f"level_{int(a):03d}.json") if a.isdigit() else a
            for a in args]


def check_file(path, time_limit=DEFAULT_TIME_LIMIT, workers=DEFAULT_WORKERS):
    """Full check of one level file (for batch runs)."""
    try:
        job = CheckJob(path, time_limit, workers, log_path=log_path_for(path))
        unused, timeouts = [], []
        for cell, _shape, status in job.run():
            if status == 'unused':
                unused.append(cell)
            elif status == 'timeout':
                timeouts.append(cell)
        return {'path': path, 'unused': sorted(unused), 'ok': sorted(job.ok_cells),
                'timeouts': timeouts, 'shapes': job.shapes, 'solves': job.solves,
                'elapsed': job.elapsed, 'error': None}
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
        more = " (time limit — there may be more)" if res['timeouts'] else ""
        return (f"{name}: failed — {len(res['unused'])} orphans{more}: "
                f"{fmt(res['unused'])} ({took})")
    if res['timeouts']:
        return f"{name}: limit achieved — not proved in {took}"
    return f"{name}: success ({took})"


def store_result(res):
    """Write a check_file() result into the level's metadata, unless the
    level's tiles changed while it was being checked. Returns a summary line."""
    from generate import write_orphan_check
    if res['error']:
        return summarize(res)
    if not write_orphan_check(res['path'], res['unused'], res['timeouts'],
                              shapes=res.get('shapes')):
        name = os.path.splitext(os.path.basename(res['path']))[0]
        return f"{name}: tiles changed during the check, not saved"
    return summarize(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('levels', nargs='*',
                    help="level files or numbers (41 -> levels/level_041.json); default: all")
    ap.add_argument('--write', action='store_true',
                    help="store the result in each level's metadata (orphan_check)")
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 4) // 4),
                    help='levels checked in parallel (batch mode)')
    ap.add_argument('--time-limit', type=float, default=DEFAULT_TIME_LIMIT,
                    help='seconds one level may take before it counts as unresolved')
    ap.add_argument('--workers', type=int, default=DEFAULT_WORKERS,
                    help='CP-SAT search threads per level')
    ap.add_argument('--verbose', action='store_true', help='also list tiles that are fine')
    args = ap.parse_args()
    paths = level_paths(args.levels)

    if len(paths) > 1:
        import multiprocessing
        t0 = time.time()
        print(f"Checking {len(paths)} levels, {args.jobs} in parallel...")
        with multiprocessing.Pool(args.jobs) as pool:
            for res in pool.imap_unordered(
                    functools.partial(check_file, time_limit=args.time_limit,
                                      workers=args.workers), paths):
                print(store_result(res) if args.write else summarize(res), flush=True)
        print(f"Done in {time.time() - t0:.1f}s")
        return

    path = paths[0]
    job = CheckJob(path, args.time_limit, args.workers, log_path=log_path_for(path))
    lv = job.level
    print(f"Grid {lv.rows}x{lv.cols}, {len(lv.batteries)} batteries, "
          f"{len(lv.targets)} targets, {job.total} pipeline cells")
    print(f"Solved map: all targets powered = {job.all_targets_ok}, "
          f"dangling connectors = {job.dangling}")

    unused, timeouts = [], []
    for (gi, gj), shape, status in job.run():
        if status == 'unused':
            unused.append((gi, gj))
            print(f"cell ({gi},{gj}) [{shape}]: WITNESS FOUND — a valid win state "
                  f"exists where this tile is unpowered")
        elif status == 'timeout':
            timeouts.append((gi, gj))
        elif args.verbose:
            print(f"cell ({gi},{gj}) [{shape}]: can't be left unpowered")

    print(f"\nDone in {job.elapsed:.1f}s, {job.solves} solves. "
          f"Orphans: {len(unused)}. Proved: {job.proved}")
    if args.write:
        print(store_result({'path': path, 'unused': unused, 'ok': sorted(job.ok_cells),
                            'timeouts': timeouts, 'shapes': job.shapes,
                            'elapsed': job.elapsed, 'error': None}))


if __name__ == '__main__':
    main()
