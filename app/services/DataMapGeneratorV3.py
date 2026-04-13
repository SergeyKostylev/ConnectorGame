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


DEFAULT_TARGETS_PCT = 15


class GeneratorV3(GeneratorV2):
    def generate(self, rows=3, cols=3, batteries=None, target_limit=None):
        self._target_limit = target_limit
        self._total_cells = rows * cols
        return super().generate(rows, cols, batteries=batteries)

    def _process(self, data_map, num_batteries):
        data_map = super()._process(data_map, num_batteries)
        return self._reduce_targets(data_map)

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

        while target_count > target_limit:
            if not self._try_merge_one_target_pair(data_map, rows, cols):
                actual_pct = round(target_count / self._total_cells * 100, 1)
                desired_pct = round(target_limit / self._total_cells * 100, 1)
                print(f"  [v3] targets: reached {actual_pct}% (desired {desired_pct}%, no more mergeable pairs)")
                return data_map
            target_count -= 1

        return data_map

    def _try_merge_one_target_pair(self, data_map, rows, cols):
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
                # A і B вже з'єднані — пропускаємо
                if mf_a.has_connector(d):
                    continue

                mf_b = _make_mf(data_map[ni][nj])

                # Знаходимо батька B (P_B)
                for pd, (pdi, pdj, popp) in _DIRECTIONS.items():
                    pi, pj = ni + pdi, nj + pdj
                    if not (0 <= pi < rows and 0 <= pj < cols):
                        continue
                    mf_p = _make_mf(data_map[pi][pj])
                    if not (mf_b.has_connector(pd) and mf_p.has_connector(popp)):
                        continue

                    # P_B повинен мати ≥ 3 з'єднань, інакше стане dead end
                    parent_conns = sum(1 for dd in _ALL_DIRS if mf_p.has_connector(dd))
                    if parent_conns <= 2:
                        continue

                    # Виконуємо злиття:
                    # 1. Видаляємо ребро B → P_B
                    self._remove_connector(data_map, ni, nj, pd)
                    self._remove_connector(data_map, pi, pj, popp)
                    # 2. Додаємо ребро A → B
                    self._add_connector(data_map, i, j, d)
                    self._add_connector(data_map, ni, nj, opp)
                    # 3. A тепер має 2 з'єднання → pipeline
                    data_map[i][j]['type'] = 'pipeline'
                    return True

        return False
