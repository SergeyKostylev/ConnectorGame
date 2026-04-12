import random

from app.services.DataMapGenerator import Generator
from app.models.MatrixFrame import MatrixFrame
import app.config as config

_ALL_DIRS = ['top', 'right', 'bottom', 'left']

_DIRECTIONS = {
    'top':    (-1,  0, 'bottom'),
    'right':  ( 0,  1, 'left'),
    'bottom': ( 1,  0, 'top'),
    'left':   ( 0, -1, 'right'),
}

_OPPOSITE = {
    'top': 'bottom', 'bottom': 'top',
    'left': 'right', 'right': 'left',
}

_DELTA_TO_DIR = {
    (-1,  0): 'top',
    ( 1,  0): 'bottom',
    ( 0, -1): 'left',
    ( 0,  1): 'right',
}


def _make_mf(cell):
    return MatrixFrame(cell['name'], cell['rotation'], cell['type'])


class GeneratorV2(Generator):
    def __init__(self):
        super().__init__()
        self._connection_to_shape = self._build_connection_lookup()

    def generate(self, rows=3, cols=3, batteries=None):
        data_map = super().generate(rows, cols)

        if batteries is None:
            raise ValueError("batteries must be provided")

        return self._process(data_map, batteries)

    # ------------------------------------------------------------------ #

    def _process(self, data_map, num_batteries):
        graph = self._build_graph(data_map)
        cuts = self._select_cuts(graph, num_batteries - 1)
        data_map = self._apply_cuts(data_map, cuts)
        data_map = self._refresh_dead_ends(data_map)
        components = self._find_components(data_map)
        return self._assign_roles(data_map, components)

    # ------------------------------------------------------------------ #
    # Lookup: connection pattern → (shape name, rotation)

    def _build_connection_lookup(self):
        lookup = {frozenset(): ('w', 0)}
        for name in config.frames:
            if name == 'w':
                continue
            for rotation in [0, 90, 180, 270]:
                mf = MatrixFrame(name, rotation, 'pipeline')
                conns = frozenset(d for d in _ALL_DIRS if mf.has_connector(d))
                if conns not in lookup:
                    lookup[conns] = (name, rotation)
        return lookup

    # ------------------------------------------------------------------ #
    # Graph

    def _build_graph(self, data_map):
        rows, cols = len(data_map), len(data_map[0])
        graph = {(i, j): set() for i in range(rows) for j in range(cols)}

        for i in range(rows):
            for j in range(cols):
                mf = _make_mf(data_map[i][j])
                for d, (di, dj, opp) in _DIRECTIONS.items():
                    ni, nj = i + di, j + dj
                    if 0 <= ni < rows and 0 <= nj < cols:
                        mf_n = _make_mf(data_map[ni][nj])
                        if mf.has_connector(d) and mf_n.has_connector(opp):
                            graph[(i, j)].add((ni, nj))
                            graph[(ni, nj)].add((i, j))
        return graph

    def _find_components(self, data_map):
        graph = self._build_graph(data_map)
        visited = set()
        components = []

        for node in graph:
            if node not in visited:
                comp = []
                stack = [node]
                while stack:
                    cur = stack.pop()
                    if cur in visited:
                        continue
                    visited.add(cur)
                    comp.append(cur)
                    stack.extend(graph[cur] - visited)
                components.append(comp)
        return components

    # ------------------------------------------------------------------ #
    # Cut selection — cut edges, not tiles

    def _select_cuts(self, graph, num_cuts):
        graph = {k: set(v) for k, v in graph.items()}  # working copy
        cuts = []

        for _ in range(num_cuts):
            cut = self._find_one_valid_cut(graph)
            if cut is None:
                break
            a, b = cut
            graph[a].discard(b)
            graph[b].discard(a)
            cuts.append(cut)

        return cuts

    def _find_one_valid_cut(self, graph):
        leaves = {n for n, nbrs in graph.items() if len(nbrs) == 1}

        edges = set()
        for n, nbrs in graph.items():
            for m in nbrs:
                edges.add(tuple(sorted([n, m])))

        valid = []
        for a, b in edges:
            # don't cut a leaf's only connection — it would become isolated
            if a in leaves or b in leaves:
                continue
            comp_a = self._bfs_excluding(graph, a, b)
            comp_b = self._bfs_excluding(graph, b, a)
            # each side must have at least one leaf (for battery assignment)
            if (comp_a & leaves) and (comp_b & leaves):
                valid.append((a, b))

        return random.choice(valid) if valid else None

    def _bfs_excluding(self, graph, start, excluded):
        visited = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(n for n in graph[node] if n != excluded)
        return visited

    # ------------------------------------------------------------------ #
    # Apply cuts to data_map — remove connectors from both tile sides

    def _apply_cuts(self, data_map, cuts):
        for (i1, j1), (i2, j2) in cuts:
            di, dj = i2 - i1, j2 - j1
            dir_fwd = _DELTA_TO_DIR[(di, dj)]
            dir_bwd = _OPPOSITE[dir_fwd]
            self._remove_connector(data_map, i1, j1, dir_fwd)
            self._remove_connector(data_map, i2, j2, dir_bwd)
        return data_map

    def _remove_connector(self, data_map, i, j, direction):
        cell = data_map[i][j]
        mf = _make_mf(cell)
        conns = frozenset(d for d in _ALL_DIRS if mf.has_connector(d))
        new_conns = conns - {direction}

        if new_conns in self._connection_to_shape:
            name, rotation = self._connection_to_shape[new_conns]
            data_map[i][j] = {'name': name, 'rotation': rotation, 'type': cell['type']}

    # ------------------------------------------------------------------ #
    # After cuts, pipeline tiles that became i-shape are new dead-ends

    def _refresh_dead_ends(self, data_map):
        for row in data_map:
            for cell in row:
                if cell['type'] == 'pipeline' and cell['name'] == 'i':
                    cell['type'] = 'missing'
        return data_map

    # ------------------------------------------------------------------ #
    # Assign battery / target per component

    def _assign_roles(self, data_map, components):
        for comp in components:
            missing = [(i, j) for i, j in comp if data_map[i][j]['type'] == 'missing']
            if not missing:
                continue
            battery = random.choice(missing)
            data_map[battery[0]][battery[1]]['type'] = 'battery'
            for i, j in missing:
                if (i, j) != battery:
                    data_map[i][j]['type'] = 'target'
        return data_map
