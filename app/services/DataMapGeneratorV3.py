import random

from app.services.DataMapGeneratorV2 import GeneratorV2
from app.models.MatrixFrame import MatrixFrame
import app.config as config

_ALL_DIRS = ['top', 'right', 'bottom', 'left']

_DIRECTIONS = {
    'top':    (-1,  0, 'bottom'),
    'right':  ( 0,  1, 'left'),
    'bottom': ( 1,  0, 'top'),
    'left':   ( 0, -1, 'right'),
}


def _make_mf(cell):
    return MatrixFrame(cell['name'], cell['rotation'], cell['type'])


def _conn_count(cell):
    mf = _make_mf(cell)
    return sum(1 for d in _ALL_DIRS if mf.has_connector(d))


def _find_parent(data_map, i, j, rows, cols):
    """Find the single neighbor that target (i,j) connects to. Returns (dir, pi, pj) or None."""
    mf = _make_mf(data_map[i][j])
    for d, (di, dj, opp) in _DIRECTIONS.items():
        ni, nj = i + di, j + dj
        if not (0 <= ni < rows and 0 <= nj < cols):
            continue
        mf_n = _make_mf(data_map[ni][nj])
        if mf.has_connector(d) and mf_n.has_connector(opp):
            return d, ni, nj
    return None


DEFAULT_TARGETS_PCT = 15
MIN_COMPONENT_TILES = 10


class GeneratorV3(GeneratorV2):
    def generate(self, rows=3, cols=3, batteries=None, target_limit=None):
        self._target_limit = target_limit
        self._total_cells = rows * cols
        self._min_component = max(MIN_COMPONENT_TILES, self._total_cells // (batteries * 3)) if batteries else MIN_COMPONENT_TILES
        return super().generate(rows, cols, batteries=batteries)

    def _process(self, data_map, num_batteries):
        data_map = super()._process(data_map, num_batteries)
        return self._reduce_targets(data_map)

    # ------------------------------------------------------------------ #
    # Override V2: ensure cuts don't create tiny components

    def _find_one_valid_cut(self, graph):
        leaves = {n for n, nbrs in graph.items() if len(nbrs) == 1}

        edges = set()
        for n, nbrs in graph.items():
            for m in nbrs:
                edges.add(tuple(sorted([n, m])))

        valid = []
        for a, b in edges:
            if a in leaves or b in leaves:
                continue
            comp_a = self._bfs_excluding(graph, a, b)
            comp_b = self._bfs_excluding(graph, b, a)
            if not ((comp_a & leaves) and (comp_b & leaves)):
                continue
            if len(comp_a) < self._min_component or len(comp_b) < self._min_component:
                continue
            valid.append((a, b))

        return random.choice(valid) if valid else None

    # ------------------------------------------------------------------ #

    def _add_connector(self, data_map, i, j, direction):
        cell = data_map[i][j]
        mf = _make_mf(cell)
        conns = frozenset(d for d in _ALL_DIRS if mf.has_connector(d))
        new_conns = conns | {direction}
        if new_conns in self._connection_to_shape:
            name, rotation = self._connection_to_shape[new_conns]
            data_map[i][j] = {'name': name, 'rotation': rotation, 'type': cell['type']}

    def _reduce_targets(self, data_map):
        rows, cols = len(data_map), len(data_map[0])
        target_limit = self._target_limit
        if target_limit is None:
            target_limit = round(self._total_cells * DEFAULT_TARGETS_PCT / 100)
        target_count = sum(
            1 for row in data_map for cell in row if cell['type'] == 'target'
        )

        s1_count, s2_count = 0, 0

        while target_count > target_limit:
            # Strategy 1: redirect B from P_B to A (P_B must have ≥3 conns)
            if self._try_direct_merge(data_map, rows, cols):
                target_count -= 1
                s1_count += 1
                continue
            # Strategy 2: chain reroute — walk up from A through 2-conn tiles,
            # cut at first ≥3 conn node, connect A↔B
            if self._try_chain_reroute(data_map, rows, cols):
                target_count -= 1
                s2_count += 1
                continue
            # No more merges possible
            actual_pct = round(target_count / self._total_cells * 100, 1)
            desired_pct = round(target_limit / self._total_cells * 100, 1)
            print(f"  [v3] targets: reached {actual_pct}% (desired {desired_pct}%, no more mergeable pairs)")
            print(f"  [v3] merges: strategy1={s1_count}, strategy2={s2_count}")
            return data_map

        print(f"  [v3] merges: strategy1={s1_count}, strategy2={s2_count}")
        return data_map

    # ------------------------------------------------------------------ #
    # Strategy 1: direct merge
    # Two adjacent targets A, B. Redirect B from P_B to A.
    # Requires P_B to have ≥3 connections.
    # Result: A becomes pipeline, B stays target. Net: -1 target.

    def _try_direct_merge(self, data_map, rows, cols):
        targets = [
            (i, j)
            for i in range(rows)
            for j in range(cols)
            if data_map[i][j]['type'] == 'target'
        ]
        random.shuffle(targets)

        for (i, j) in targets:
            mf_a = _make_mf(data_map[i][j])

            for d, (di, dj, opp) in _DIRECTIONS.items():
                ni, nj = i + di, j + dj
                if not (0 <= ni < rows and 0 <= nj < cols):
                    continue
                if data_map[ni][nj]['type'] != 'target':
                    continue
                if mf_a.has_connector(d):
                    continue

                mf_b = _make_mf(data_map[ni][nj])

                for pd, (pdi, pdj, popp) in _DIRECTIONS.items():
                    pi, pj = ni + pdi, nj + pdj
                    if not (0 <= pi < rows and 0 <= pj < cols):
                        continue
                    mf_p = _make_mf(data_map[pi][pj])
                    if not (mf_b.has_connector(pd) and mf_p.has_connector(popp)):
                        continue

                    if _conn_count(data_map[pi][pj]) < 3:
                        continue

                    self._remove_connector(data_map, ni, nj, pd)
                    self._remove_connector(data_map, pi, pj, popp)
                    self._add_connector(data_map, i, j, d)
                    self._add_connector(data_map, ni, nj, opp)
                    data_map[i][j]['type'] = 'pipeline'
                    return True

        return False

    # ------------------------------------------------------------------ #
    # Strategy 2: chain reroute
    # Two adjacent targets A, B (not connected).
    # Walk up from A: A → P_A → Q → ... → S → R
    # All tiles P_A..S have exactly 2 connections. R has ≥3.
    #
    # Action: add A↔B, remove S↔R.
    # A → pipeline, B → pipeline, S → target.
    # Tree preserved (add 1 edge, remove 1 edge on the A-B path). Net: -1 target.

    def _try_chain_reroute(self, data_map, rows, cols):
        targets = [
            (i, j)
            for i in range(rows)
            for j in range(cols)
            if data_map[i][j]['type'] == 'target'
        ]
        random.shuffle(targets)

        for (i, j) in targets:
            mf_a = _make_mf(data_map[i][j])

            # Check if A has any adjacent target B (not connected)
            b_options = []
            for bd, (bdi, bdj, b_opp) in _DIRECTIONS.items():
                if mf_a.has_connector(bd):
                    continue
                bi, bj = i + bdi, j + bdj
                if not (0 <= bi < rows and 0 <= bj < cols):
                    continue
                if data_map[bi][bj]['type'] != 'target':
                    continue
                b_options.append((bd, bi, bj, b_opp))

            if not b_options:
                continue

            # Walk up chain from A to find cut point S↔R
            cut = self._find_chain_cut(data_map, i, j, rows, cols)
            if cut is None:
                continue

            si, sj, s_dir, ri, rj, r_opp = cut
            bd, bi, bj, b_opp = random.choice(b_options)

            # 1. Add edge A↔B
            self._add_connector(data_map, i, j, bd)
            self._add_connector(data_map, bi, bj, b_opp)
            # 2. Remove edge S↔R
            self._remove_connector(data_map, si, sj, s_dir)
            self._remove_connector(data_map, ri, rj, r_opp)
            # 3. Update types
            data_map[i][j]['type'] = 'pipeline'     # A: 2 conns now
            data_map[bi][bj]['type'] = 'pipeline'    # B: 2 conns now
            data_map[si][sj]['type'] = 'target'      # S: 1 conn (dead end)
            return True

        return False

    def _find_chain_cut(self, data_map, ai, aj, rows, cols):
        """Walk from target A up the chain of 2-conn tiles.
        Returns (si, sj, s_to_r_dir, ri, rj, r_to_s_dir) when a ≥3 conn node R is found.
        Returns None if no valid cut exists."""
        parent = _find_parent(data_map, ai, aj, rows, cols)
        if parent is None:
            return None

        _, pi, pj = parent
        prev = (ai, aj)
        current = (pi, pj)

        while True:
            ci, cj = current
            conns = _conn_count(data_map[ci][cj])

            if conns >= 3:
                # Found R at (ci, cj). Cut point is between prev (S) and current (R).
                si, sj = prev
                for d, (di, dj, opp) in _DIRECTIONS.items():
                    if (si + di, sj + dj) == (ci, cj):
                        mf_s = _make_mf(data_map[si][sj])
                        mf_r = _make_mf(data_map[ci][cj])
                        if mf_s.has_connector(d) and mf_r.has_connector(opp):
                            return (si, sj, d, ci, cj, opp)
                return None

            if conns != 2:
                return None

            # Don't walk through battery tiles
            if data_map[ci][cj]['type'] == 'battery':
                return None

            # Find next node (not prev)
            next_node = None
            for d, (di, dj, opp) in _DIRECTIONS.items():
                ni, nj = ci + di, cj + dj
                if (ni, nj) == prev:
                    continue
                if not (0 <= ni < rows and 0 <= nj < cols):
                    continue
                mf_c = _make_mf(data_map[ci][cj])
                mf_n = _make_mf(data_map[ni][nj])
                if mf_c.has_connector(d) and mf_n.has_connector(opp):
                    next_node = (ni, nj)
                    break

            if next_node is None:
                return None

            prev = current
            current = next_node
