"""
Level generator built on CP-SAT (Google OR-Tools) — the same solver
tools/orphan_checker.py uses to verify levels. Every level it returns is
PROVED orphan-free. It depends on nothing from the V1-V3 generators.

"No orphans" means: for EVERY rotation of the tiles that powers all lamps,
every pipeline tile is powered too. That "for every" can't go into one CP-SAT
model, so two models take turns (counterexample-guided generation, CEGAR):

  1. the generator model proposes a solved level (tile shapes + types);
  2. the orphan checker's model searches that level for a witness: a win state
     with some pipeline tile unpowered — the one closest to the proposal
     (fewest tiles turned), so it points at the actual detour;
  3. no witness (INFEASIBLE) -> proved, done. Otherwise every witness becomes a
     nogood in the generator model (see NOGOOD_MODE) and it proposes again.

Batteries are placed up front (random, spread apart) — letting the solver
place them made the model far too slow. A placement that yields no level within
FIRST_SOLVE_LIMIT, or whose nogoods leave no level, is dropped and a fresh one
is tried, until the time budget runs out.

The generator model:

    e[edge]     grid edge is live: both facing sides have a connector
                (so there are never dangling connectors)
    deg[v]      live edges at v, 1..4 — no walls
    bat[v]      v is a battery — fixed by the placement
    tgt[v]      v is a lamp; bat + tgt == (deg == 1): dead ends are exactly
                the batteries and lamps
    par[v][u]   u is v's parent; a battery has none, every other cell one
    flow[v->u]  cells whose power runs through v into its parent u: v sends
                1 + everything it receives, so parent links can't form a cycle
                and every cell hangs off a battery; a battery receives its
                network's size - 1
    lamps[v->u] same for lamps only: a battery receives its network's lamps
    live edges == cells - B  ->  the parent links are ALL the edges: the level
                is a forest, one tree (network) per battery
    sh[v][s]    v has shape s (i/l/g/t/x) — what the nogoods talk about

Rules (agreed with the user; nothing else is imposed):
    - never a battery connected straight to a lamp
    - single-lamp networks  <= SINGLE_LAMP_SHARE of networks
    - short networks        <= SHORT_NET_SHARE of networks
                               (size < SHORT_NET_RATIO x average size)
    - lamps next to battery <= LAMP_NEAR_SHARE of lamps
                               (battery -> one pipe -> lamp)
  each is a cap plus an objective penalty, so they stay rare, not just legal.
  (Straight-tile rules exist but are off — see STRAIGHT_MAX_SHARE.)

Note — branching is fixed by the counts: in a forest with one battery per
tree,  T-junctions + 2 x crosses == lamps - batteries,  and every other
non-leaf tile is a chain piece (straight or corner). See composition().
"""
import math
import random
import time

from app.models.MatrixFrame import MatrixFrame
import app.config as config

DEFAULT_TARGETS_PCT = 15
DEFAULT_TIME_LIMIT = 120.0      # whole generation, all attempts
DEFAULT_WORKERS = 8
LAMP_TOLERANCE = 0.10           # lamps: +-10 % of the requested count (at least +-1)
FIRST_SOLVE_LIMIT = 3.0         # first proposal for a placement; none -> new placement
GEN_SOLVE_LIMIT = 2.0           # later proposals (hinted with the previous one)
CHECK_SOLVE_LIMIT = 30.0        # one witness search
MAX_WITNESSES = 4               # witnesses (nogoods) collected per proposal
MAX_PROPOSALS = 60              # proposals per model before starting a fresh one

# soft rules: cap + penalty
SINGLE_LAMP_SHARE = 0.25        # networks with exactly one lamp
SHORT_NET_SHARE = 0.20          # networks smaller than SHORT_NET_RATIO x average
SHORT_NET_RATIO = 0.5
LAMP_NEAR_SHARE = 0.10          # lamps one pipe away from their battery
BATTERY_SPACING = 0.6           # min battery distance = this x sqrt(cells / batteries)
# straight-tile rules — OFF: as hard constraints they make the model too slow to
# find any level, and as a penalty they do nothing (the solver returns its first
# levels, long before optimising). Kept for experiments.
STRAIGHT_MAX_SHARE = None       # e.g. 0.35: straight tiles among pipes
MAX_STRAIGHT_RUN = None         # e.g. 2: straights in a row along one line
STRAIGHT_PENALTY = 0            # objective cost of one straight tile

TARGET_DEV_PENALTY = 30         # objective cost of one lamp off the requested count
SOFT_PENALTY = 150              # objective cost of one single-lamp/short net or near lamp
NOISE_MAX = 100                 # random edge weights 0..NOISE_MAX: variety

# which tiles a witness's nogood asks to reshape:
#   'local'  — tiles the witness turned that stay powered, plus powered tiles
#              bordering the unpowered ones (reshaping an unpowered tile
#              rarely removes the detour, so they're left out)
#   'legacy' — every tile the witness turned or left unpowered
NOGOOD_MODE = 'local'
MINIMIZE_WITNESS = True

_DIRS = [config.DURATION_TOP, config.DURATION_RIGHT,
         config.DURATION_BOTTOM, config.DURATION_LEFT]
_DELTA = [(-1, 0), (0, 1), (1, 0), (0, -1)]          # same order as _DIRS
_SHAPES = ['i', 'l', 'g', 't', 'x']


def _connection_lookup():
    """(top, right, bottom, left) connectors -> (shape name, rotation)."""
    lookup = {}
    for name in config.frames:
        for rotation in (0, 90, 180, 270):
            mf = MatrixFrame(name, rotation, 'pipeline')
            key = tuple(mf.has_connector(d) for d in _DIRS)
            lookup.setdefault(key, (name, rotation))
    return lookup


_LOOKUP = _connection_lookup()


def counts(rows, cols, batteries_pct, targets_pct):
    """Battery count and (lo, preferred, hi) lamp counts for the given shares."""
    n = rows * cols
    bats = max(1, round(n * batteries_pct / 100))
    pref = max(1, round(n * targets_pct / 100))
    slack = max(1, round(pref * LAMP_TOLERANCE))
    return bats, (max(1, pref - slack), pref, pref + slack)


def single_lamp_cap(bats, lamps_hi):
    """Most single-lamp networks allowed, and how many the counts force:
    every network has >= 1 lamp, so with L lamps at least 2B - L have one."""
    forced = max(0, 2 * bats - lamps_hi)
    return max(math.floor(SINGLE_LAMP_SHARE * bats), forced), forced


def composition(rows, cols, batteries_pct, targets_pct):
    """What the shares imply, for the launcher preview / the log:
    dict(cells, batteries, lamps, junctions, chains_pct, forced_single, error)."""
    n = rows * cols
    bats, (lo, pref, hi) = counts(rows, cols, batteries_pct, targets_pct)
    junctions = pref - bats                      # as T tiles
    chains = n - bats - pref - max(0, junctions)
    error = None
    if hi < bats:
        error = "lamps must outnumber batteries (each network needs a lamp)"
    elif n - bats - lo < bats:     # each network needs a pipe: no battery-lamp pairs
        error = "too many batteries/lamps for this grid"
    _, forced = single_lamp_cap(bats, hi)
    return dict(cells=n, batteries=bats, lamps=pref, junctions=max(0, junctions),
                chains_pct=100 * max(0, chains) / n, forced_single=forced, error=error)


class _Model:
    """Generator model: one CP-SAT model, nogoods accumulate in it."""

    def __init__(self, rows, cols, bat_cells, targets, rng, workers):
        from ortools.sat.python import cp_model
        self.cp = cp_model
        self.rows, self.cols = rows, cols
        self.workers = workers
        self.rng = rng
        m = self.m = cp_model.CpModel()
        n = rows * cols
        idx = lambda i, j: i * cols + j

        # sides[v][d]: the edge variable on side d of v, None on the border
        self.sides = [[None] * 4 for _ in range(n)]
        nbr = [[] for _ in range(n)]
        edge = {}
        for i in range(rows):
            for j in range(cols):
                v = idx(i, j)
                for d, (di, dj) in enumerate(_DELTA):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < rows and 0 <= nj < cols:
                        u = idx(ni, nj)
                        nbr[v].append(u)
                        if (u, v) not in edge:
                            edge[(v, u)] = edge[(u, v)] = m.NewBoolVar(f"e{v}_{u}")
                        self.sides[v][d] = edge[(v, u)]
        self.edges = [e for key, e in edge.items() if key[0] < key[1]]

        bat = self.bat = [m.NewBoolVar(f"b{v}") for v in range(n)]
        tgt = self.tgt = [m.NewBoolVar(f"t{v}") for v in range(n)]
        par = {(v, u): m.NewBoolVar(f"p{v}_{u}") for v in range(n) for u in nbr[v]}
        flow = {k: m.NewIntVar(0, n - 1, f"f{k[0]}_{k[1]}") for k in par}
        lamps = {k: m.NewIntVar(0, n, f"lf{k[0]}_{k[1]}") for k in par}

        for v in range(n):
            m.Add(bat[v] == int(v in bat_cells))
        bats = len(bat_cells)
        lo, pref, hi = targets
        tsum = sum(tgt)
        m.Add(tsum >= lo)
        m.Add(tsum <= hi)

        size = []            # size[v] - 1 when v is a battery
        net_lamps = []       # lamps of v's network when v is a battery
        for v in range(n):
            deg = sum(e for e in self.sides[v] if e is not None)
            leaf = m.NewBoolVar(f"leaf{v}")
            m.Add(deg == 1).OnlyEnforceIf(leaf)
            m.Add(deg >= 2).OnlyEnforceIf(leaf.Not())
            m.Add(bat[v] + tgt[v] == leaf)
            # one parent unless a battery; everything v collects goes there
            m.Add(sum(par[(v, u)] for u in nbr[v]) + bat[v] == 1)
            for u in nbr[v]:
                m.AddImplication(par[(v, u)], edge[(v, u)])
                m.Add(flow[(v, u)] == 0).OnlyEnforceIf(par[(v, u)].Not())
                m.Add(lamps[(v, u)] == 0).OnlyEnforceIf(par[(v, u)].Not())
            inflow = sum(flow[(u, v)] for u in nbr[v])
            lamp_in = sum(lamps[(u, v)] for u in nbr[v])
            m.Add(sum(flow[(v, u)] for u in nbr[v]) == 1 + inflow).OnlyEnforceIf(bat[v].Not())
            m.Add(sum(lamps[(v, u)] for u in nbr[v]) == tgt[v] + lamp_in).OnlyEnforceIf(bat[v].Not())
            size.append(inflow)
            net_lamps.append(lamp_in)
            # never a battery straight to a lamp
            for u in nbr[v]:
                m.AddBoolOr([edge[(v, u)].Not(), bat[v].Not(), tgt[u].Not()])

        # edge count of a forest with one tree per battery
        m.Add(sum(self.edges) == n - bats)

        # soft rules — each count is only bounded from below: the cap and the
        # penalty push it down to the true value
        single = [m.NewBoolVar(f"single{v}") for v in range(n)]
        short = [m.NewBoolVar(f"short{v}") for v in range(n)]
        short_min = math.ceil(SHORT_NET_RATIO * n / bats)
        for v in range(n):
            m.Add(net_lamps[v] >= 2).OnlyEnforceIf([bat[v], single[v].Not()])
            m.Add(size[v] + 1 >= short_min).OnlyEnforceIf([bat[v], short[v].Not()])
        near = []            # lamp v, its parent u, u's parent a battery
        child_of_bat = []
        for u in range(n):
            qs = []
            for b in nbr[u]:
                q = m.NewBoolVar(f"q{u}_{b}")
                m.Add(q >= par[(u, b)] + bat[b] - 1)
                qs.append(q)
            child_of_bat.append(sum(qs))
        for v in range(n):
            for u in nbr[v]:
                r = m.NewBoolVar(f"near{v}_{u}")
                m.Add(r >= par[(v, u)] + child_of_bat[u] + tgt[v] - 2)
                near.append(r)
        self.single_cap, self.single_forced = single_lamp_cap(bats, hi)
        self.short_cap = math.floor(SHORT_NET_SHARE * bats)
        m.Add(sum(single) <= self.single_cap)
        m.Add(sum(short) <= self.short_cap)
        m.Add(sum(near) * round(1 / LAMP_NEAR_SHARE) <= tsum)

        # shape of every cell, read off its four sides
        self.sh = [{s: m.NewBoolVar(f"sh{v}{s}") for s in _SHAPES} for v in range(n)]
        for v in range(n):
            m.AddExactlyOne(self.sh[v].values())
            for pattern, (name, _) in _LOOKUP.items():
                if name == 'w' or any(pattern[d] and self.sides[v][d] is None
                                      for d in range(4)):
                    continue
                mismatch = [self.sides[v][d].Not() if pattern[d] else self.sides[v][d]
                            for d in range(4) if self.sides[v][d] is not None]
                m.AddBoolOr(mismatch + [self.sh[v][name]])

        # straights: no long runs, a capped share of the pipes
        straight = [self.sh[v]['l'] for v in range(n)]
        if STRAIGHT_MAX_SHARE is not None:
            m.Add(100 * sum(straight) <= round(100 * STRAIGHT_MAX_SHARE) * (n - bats - tsum))
        k = (MAX_STRAIGHT_RUN or rows + cols) + 1
        for i in range(rows if MAX_STRAIGHT_RUN else 0):
            for j in range(cols):
                for di, dj in ((0, 1), (1, 0)):           # along a row / a column
                    run = [(i + di * s_, j + dj * s_) for s_ in range(k)]
                    if not all(0 <= a < rows and 0 <= b < cols for a, b in run):
                        continue
                    cells = [idx(a, b) for a, b in run]
                    # k straights joined along this line = a run that's too long
                    links = [edge[(cells[s_], cells[s_ + 1])].Not() for s_ in range(k - 1)]
                    m.AddBoolOr([straight[c].Not() for c in cells] + links)

        dev = m.NewIntVar(0, n, "tdev")
        m.AddAbsEquality(dev, tsum - pref)
        m.Maximize(sum(rng.randint(0, NOISE_MAX) * e for e in self.edges)
                   - TARGET_DEV_PENALTY * dev
                   - SOFT_PENALTY * (sum(single) + sum(short) + sum(near))
                   - STRAIGHT_PENALTY * sum(straight))
        self._hint = None

    def propose(self, time_limit):
        """((live, batteries), status name): live[v] = the (U, R, D, L)
        connectors of v, batteries = set of battery cells; None when no level
        was found (status 'INFEASIBLE' = none exists, else out of time)."""
        m, cp = self.m, self.cp
        m.ClearHints()
        if self._hint:
            for var, val in self._hint:
                m.AddHint(var, val)
        solver = cp.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit
        solver.parameters.num_workers = self.workers
        solver.parameters.relative_gap_limit = 0.05
        solver.parameters.random_seed = self.rng.randint(0, 2 ** 30)
        st = solver.Solve(m)
        if st not in (cp.OPTIMAL, cp.FEASIBLE):
            return None, solver.StatusName(st)
        self._hint = ([(e, solver.Value(e)) for e in self.edges]
                      + [(b, solver.Value(b)) for b in self.bat])
        n = self.rows * self.cols
        live = [tuple(bool(e is not None and solver.Value(e)) for e in self.sides[v])
                for v in range(n)]
        batteries = {v for v in range(n) if solver.Value(self.bat[v])}
        return (live, batteries), solver.StatusName(st)

    def forbid(self, data_map, cells):
        """At least one of `cells` must differ in shape or type from data_map."""
        lits = []
        for v in cells:
            c = data_map[v // self.cols][v % self.cols]
            if c['type'] == 'battery':
                lits.append(self.bat[v].Not())
            elif c['type'] == 'target':
                lits.append(self.tgt[v].Not())
            else:
                lits.append(self.sh[v][c['name']].Not())
        self.m.AddBoolOr(lits)


def find_witnesses(data_map, time_limit, workers, max_witnesses=MAX_WITNESSES,
                   near=None):
    """Win states of `data_map` that leave some pipeline tile unpowered.

    Returns a list of (patterns, unpowered): patterns[v] is the witness's
    (U, R, D, L) connectors of cell v, unpowered the set of unpowered cells.
    [] = proved orphan-free; None = the time limit ran out before any answer.
    near: the proposal's connectors — witnesses turning the fewest tiles
    away from it are preferred."""
    from ortools.sat.python import cp_model
    from tools.orphan_checker import Level, build_model
    level = Level([[(c['name'], str(c['rotation']), c['type']) for c in row]
                   for row in data_map])
    m, pw, open_ = build_model(level)
    if near is not None:
        turned = []
        for v in range(level.n):
            dv = m.NewBoolVar(f"turned{v}")
            for d in range(4):
                m.AddImplication(open_[v][d] if not near[v][d] else open_[v][d].Not(), dv)
            turned.append(dv)
        m.Minimize(sum(turned))
    candidates = level.pipeline_cells()
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = workers
    t0 = time.time()
    found, seen = [], set()
    for k in range(max_witnesses):
        rest = [v for v in candidates if v not in seen]
        left = time_limit - (time.time() - t0)
        if not rest or left <= 0:
            break
        # some tile not unpowered in an earlier witness is unpowered here
        guard = m.NewBoolVar(f"g{k}")
        m.AddBoolOr([pw[v].Not() for v in rest]).OnlyEnforceIf(guard)
        m.ClearAssumptions()
        m.AddAssumption(guard)
        solver.parameters.max_time_in_seconds = left
        st = solver.Solve(m)
        if st == cp_model.INFEASIBLE:
            break
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return found or None
        unpowered = {v for v in range(level.n) if not solver.Value(pw[v])}
        patterns = [tuple(bool(solver.Value(open_[v][d])) for d in range(4))
                    for v in range(level.n)]
        found.append((patterns, unpowered))
        seen |= unpowered
        m.Add(guard == 0)
    return found


def nogood_cells(rows, cols, live, patterns, unpowered, mode=None):
    """Tiles one witness's nogood asks to reshape (see NOGOOD_MODE)."""
    mode = mode or NOGOOD_MODE
    n = rows * cols
    turned = {v for v in range(n) if patterns[v] != tuple(live[v])}
    if mode == 'legacy':
        return turned | unpowered
    border = set()
    for v in unpowered:
        i, j = divmod(v, cols)
        for di, dj in _DELTA:
            ni, nj = i + di, j + dj
            if 0 <= ni < rows and 0 <= nj < cols and ni * cols + nj not in unpowered:
                border.add(ni * cols + nj)
    return ((turned - unpowered) | border) or (turned | unpowered)


class GeneratorSat:
    def __init__(self, time_limit=DEFAULT_TIME_LIMIT, workers=DEFAULT_WORKERS,
                 seed=None, log=None):
        self.time_limit = time_limit
        self.workers = workers
        self.rng = random.Random(seed)
        self.log = log or (lambda msg: print(f"sat: {msg}", flush=True))
        self.stats = {}

    def generate(self, rows, cols, batteries_pct, targets_pct, batteries=None):
        """Solved, proved orphan-free data_map
        (list[list[{'name','rotation','type'}]]).

        batteries_pct / targets_pct: shares of all cells. Batteries are exactly
        round(cells x %), lamps within +-LAMP_TOLERANCE of their share;
        batteries = an exact battery count instead of the share.
        Raises ValueError for impossible shares, RuntimeError if the time
        budget runs out first."""
        n = rows * cols
        bats, targets = counts(rows, cols, batteries_pct, targets_pct)
        if batteries is not None:
            bats = batteries
        info = composition(rows, cols, 100 * bats / n, targets_pct)
        if info['error']:
            raise ValueError(info['error'])
        lo, pref, hi = targets
        self.log(f"{rows}x{cols}: {bats} batteries, {pref} lamps ({lo}..{hi}), "
                 f"~{info['junctions']} junctions, ~{info['chains_pct']:.0f}% chain tiles")
        cap, forced = single_lamp_cap(bats, hi)
        if forced > math.floor(SINGLE_LAMP_SHARE * bats):
            self.log(f"these shares force >= {forced} of {bats} networks to have one lamp")

        self.stats = {'attempts': 0, 'candidates': 0, 'witnesses': 0}
        t0 = time.time()
        left = lambda: self.time_limit - (time.time() - t0)
        misses = 0                     # placements that gave no first candidate
        while left() > 0:
            self.stats['attempts'] += 1
            attempt = self.stats['attempts']
            placement = self._place_batteries(rows, cols, bats)
            model = _Model(rows, cols, placement, targets, self.rng, self.workers)
            limit = FIRST_SOLVE_LIMIT
            proposal = 0
            while proposal < MAX_PROPOSALS and left() > 0:
                res, status = model.propose(min(limit, left()))
                if res is None:
                    if proposal == 0:
                        misses += 1
                        if misses % 5 == 0:
                            self.log(f"{misses} battery placements fit no level yet — "
                                     f"if this goes on, try more lamps or fewer batteries")
                        break
                    if status == 'INFEASIBLE':
                        self.log(f"attempt {attempt}: nogoods rule out every level, "
                                 f"new battery placement")
                        break
                    if limit < FIRST_SOLVE_LIMIT:
                        limit = FIRST_SOLVE_LIMIT      # hinted solve ran short: retry longer
                        continue
                    self.log(f"attempt {attempt}: no candidate in {limit:g}s, "
                             f"new battery placement")
                    break
                limit = GEN_SOLVE_LIMIT
                proposal += 1
                self.stats['candidates'] += 1
                live, bat_cells = res
                data_map = self._to_data_map(rows, cols, bat_cells, live)
                witnesses = find_witnesses(
                    data_map, min(CHECK_SOLVE_LIMIT, max(1.0, left())), self.workers,
                    near=live if MINIMIZE_WITNESS else None)
                if witnesses is None:
                    self.log(f"attempt {attempt}: check timed out, starting over")
                    break
                if not witnesses:
                    self.log(f"proved orphan-free — attempt {attempt}, "
                             f"candidate {proposal}, {time.time() - t0:.1f}s")
                    return data_map
                self.stats['witnesses'] += len(witnesses)
                orphans = set()
                for patterns, unpowered in witnesses:
                    model.forbid(data_map, nogood_cells(rows, cols, live, patterns, unpowered))
                    orphans |= unpowered
                self.log(f"attempt {attempt}, candidate {proposal}: "
                         f"{len(orphans)} orphan tiles, reshaping "
                         f"({time.time() - t0:.0f}s)")
        raise RuntimeError(f"no orphan-free level in {self.time_limit:g}s — "
                           f"try a smaller grid or other batteries/lamps %")

    # ------------------------------------------------------------------ #

    def _place_batteries(self, rows, cols, count):
        """`count` random cells (as indices), spread apart: min distance
        BATTERY_SPACING x sqrt(cells / count), relaxed until it fits."""
        cells = [(i, j) for i in range(rows) for j in range(cols)]
        spacing = max(2, round(BATTERY_SPACING * math.sqrt(rows * cols / count)))
        while True:
            self.rng.shuffle(cells)
            picked = []
            for c in cells:
                if all(abs(c[0] - p[0]) + abs(c[1] - p[1]) >= spacing for p in picked):
                    picked.append(c)
                    if len(picked) == count:
                        return {i * cols + j for i, j in picked}
            spacing -= 1

    @staticmethod
    def _to_data_map(rows, cols, bat_cells, live):
        data_map = []
        for i in range(rows):
            row = []
            for j in range(cols):
                v = i * cols + j
                conns = tuple(live[v])
                name, rotation = _LOOKUP[conns]
                if v in bat_cells:
                    kind = 'battery'
                elif sum(conns) == 1:
                    kind = 'target'
                else:
                    kind = 'pipeline'
                row.append({'name': name, 'rotation': rotation, 'type': kind})
            data_map.append(row)
        return data_map
