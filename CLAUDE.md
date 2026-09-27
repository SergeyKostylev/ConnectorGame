# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ConnectorGame is a grid-based pipe/connector puzzle game (like "Plumber"/"Net"), built with Python, pygame, and numpy. The player rotates tiles to connect all `target` tiles to a `battery` tile via `pipeline` tiles.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install pygame   # not in requirements.txt but required — venv already has it installed
```

Note: `requirements.txt` also carries `PyYAML` and `networkx`, which are no longer used (levels are JSON; graph logic is the hand-rolled `GraphHelper`). `matplotlib` is only reachable via dead code (`Maze.draw_maze`, `helper.show_graph`).

## Common commands

Run via `make <target>` (see `Makefile`; `make help` lists all with descriptions):

- `make launch` — open the GUI launcher (`launcher.py`): generate levels and edit them, all in one pygame window. Same as `python main.py` with no arguments.
- `make generate-level-v3 rows=R cols=C batteries=N targets_percent=P run=1` — generate a level with the current generator (V3), save JSON + PNG to `levels/`.
- `make generate-level-sat rows=R cols=C batteries_percent=B targets_percent=P run=1` — generate a proved orphan-free level with the CP-SAT generator (OR-Tools).
- `python3 tools/bench_sat.py [--sizes 11x12 15x15] [--batteries B] [--lamps L] [--seeds N] [--nogood local|legacy] [--no-minimize]` — benchmark the sat generator (prints a table, writes no levels).
- `make generate-level-v2 rows=R cols=C batteries=N run=1` — generate with V2 (no target-density control).
- `make generate-level-v1 rows=R cols=C` — generate with V1 (pipeline/missing only, no battery/target).
- `make level-run [N]` — run a saved level from `levels/` (latest if no arg). Add `--shuffled` via `python main.py N --shuffled` to play the shuffled variant directly.
- `make level-run-shuffled [N]` — run the shuffled variant.
- `make edit [N]` — open the standalone tile editor (`edit.py`) for a level (latest if no arg).
- `make run-default` — play the latest level (`python main.py latest`).

There is no test suite, linter, or CI config in this repo.

## Controls (in-game)

- Arrow keys: move cursor.
- Space: rotate the tile under the cursor 90° clockwise.
- In the editor / launcher's inline editor: left-click rotates a tile, right-click opens a context menu to change a tile's shape/type directly.

## Architecture

### Tile model
A tile (`MatrixFrame`, `app/models/MatrixFrame.py`) is a 3×3 binary connector matrix plus a `type`. Shapes live in `app/config.py::frames`:
- `g` corner (2 conns), `l` straight (2 opposite), `t` T-junction (3), `x` cross (4), `i` dead-end (1), `w` wall (0, all-zero — no connectors).
`turn()` rotates the matrix 90° CW and tracks `rotation` (0/90/180/270). `has_connector(direction)` reads one edge of the matrix.

Tile `type` is one of: `battery` (power source), `target` (needs to be powered), `pipeline` (the tiles the player rotates), `missing` (an intermediate dead-end state used only during generation, never persisted as final).

### Grid + connectivity
`Matrix(GraphHelper)` (`app/models/Matrix.py`) holds a 2D grid of `MatrixFrame` plus an adjacency graph over node names `"i-j"`. Every `turn_frame()`/`replace_frame()` call triggers `reconnect_one(x, y)`, which checks the tile's 4 neighbors and adds/removes graph edges based on whether both sides have a matching connector. `is_connected_to_battery(i, j)` does a DFS (`GraphHelper.has_path`, hand-rolled — no networkx) from a tile to any battery node. `GraphHelper` is a minimal from-scratch adjacency-set graph (no external graph library).

### Rendering
`Render`/`GritItem` (`app/services/render.py`) draw tile textures from `src/*.jpg` each frame, keyed by shape+rotation (or connected-state for targets/battery). Texture paths: pipeline `src/{name}{rotation}.jpg`, battery `src/battery/bat_{rotation}.jpg`, target `src/target/{on|off}_{rotation}.jpg`. `App` (`app/pygame.py`) runs the 24 FPS main loop: arrow keys move `Cursor`, Space calls `matrix.turn_frame()`.

### Level generation pipeline
Four generators (`app/services/DataMapGenerator*.py`); V1–V3 build on each other, SAT is standalone:
1. **V1** (`Generator`): runs Prim's maze algorithm (`app/services/Maze.py`), slices the maze into 3×3 blocks, and matches each block against all rotations of every shape to get a `data_map` of `pipeline`/`missing` tiles. No battery/target yet.
2. **V2** (`GeneratorV2(Generator)`): takes V1's output, builds a connectivity graph over tiles, and cuts N‑1 edges (never a leaf's only edge; both resulting sides must retain a leaf) to split the maze into N independent components. Cutting an edge removes the connector from *both* adjacent tiles (shape changes, e.g. `t`→`g`), via a precomputed connection-pattern → (shape, rotation) lookup. Any pipeline tile that degenerates to `i`-shape becomes `missing`. Each resulting component gets one `missing`→`battery`, the rest `missing`→`target`.
3. **V3** (`GeneratorV3(GeneratorV2)`): runs V2, then reduces the target *density* to a target percentage (`targets_percent`, default 15%) via two tree-surgery strategies applied repeatedly until at/under the limit or no more merges are possible: **direct merge** (two adjacent targets, redirect one into the other when the shared parent has ≥3 connections) and **chain reroute** (walk up a chain of 2-connection tiles from a target to the first ≥3-connection node, splice a new edge between two adjacent targets and cut the old one). This is the launcher's default generator.
4. **SAT** (`GeneratorSat`, `app/services/DataMapGeneratorSat.py`): independent of V1–V3 (imports nothing from them); every level it returns is **proved orphan-free**. Plan and agreed requirements: `docs/sat_generator_plan.md`. "No orphans" is a ∀ property, so it runs a CEGAR loop of two CP-SAT models: the generator model proposes a solved level; `find_witnesses` (on `tools/orphan_checker.build_model`) searches it for a win state with an unpowered pipeline, preferring the one that turns the fewest tiles; each witness becomes a nogood over `nogood_cells` (`NOGOOD_MODE='local'`: turned tiles that stay powered + powered tiles bordering the unpowered ones; `'legacy'`: turned + unpowered) and the generator proposes again until the check is INFEASIBLE. A model whose nogoods leave no level is replaced by a fresh one; 120 s budget, then it fails without saving. Generator model: shared edge bools (no dangling connectors); the solver places exactly `round(cells × batteries%)` batteries (`bat[v]`, spaced ≥ `0.6·sqrt(cells/batteries)` apart); lamps within ±10 % of their share; dead ends = batteries + lamps; one parent per non-battery cell with a size flow (no parent cycles, battery receives network size − 1) and a lamp flow (battery receives its network's lamp count); live edges = cells − batteries → a forest, one network per battery. Rules: never battery→lamp directly; single-lamp networks ≤ 25 % (or what the shares force: `2B − lamps`), short networks (< 50 % of average size) ≤ 20 %, lamps one pipe from their battery ≤ 10 % of lamps — each a cap plus an objective penalty; random edge weights for variety. Branching is fixed by the counts (T-junctions + 2·crosses = lamps − batteries); `composition()` computes it for the launcher's preview under the sat fields. `tools/bench_sat.py` benchmarks it (writes nothing to `levels/`). Saved with `generator: "sat"` and `orphan_check: "success"`.

`data_map` is a `list[list[dict]]` of `{'name', 'rotation', 'type'}` cells throughout generation; it only becomes a `Matrix` when actually rendered/played.

### Level file format
`generate.py` saves levels as JSON to `levels/level_NNN.json` (auto-incrementing name), with a hand-formatted (not `json.dump`) pretty-printer for compact tile grids:
```json
{
  "metadata": {"size": "RxC", "generator": "v3", "battery": "...", "target": "...", "pipeline": "...", "wall": "..."},
  "meet_map": [["i:270:battery", "l:90:pipeline", ...], ...],
  "shuffled_map": [[...], ...]
}
```
Each cell is encoded `"name:rotation:type"`. `meet_map` is the solved level; `shuffled_map` is the same tiles with rotations randomized (`unsort_map`) — this is the playable, unsolved puzzle. A `.png` render is saved alongside each level (`save_image`) for both maps.

### GUI launcher (`launcher.py`)
Single-file pygame UI with no external framework. Layout is always a **3-column view** (no tabs):

- **Left column** (`GEN_COL_W = 185px`): generation form — algo selector buttons (`self._gen_algo_btns`: `"v3"`, `"sat"`, `"empty"` — an all-wall grid of rows×cols, written in-process; selection persisted as `Generate.algo` in prefs; for `sat` the "batteries %" field is passed as a percentage, for `v3` as a count), then inputs: rows, cols, batteries %, targets %, check-orphans checkbox. "Generate <algo>" button right under the inputs, and below it a log box (`_draw_gen_log`) with the whole output of the last generation; while it runs the button turns into "Stop · m:ss" (a live clock; clicking terminates the `generate.py` child), the generator's `sat: ...` progress lines stream into the status bar, the final status gets the total time, and the new level gets selected in the list and opened in the editor (`App._open_generated`; asks first if the editor has unsaved edits).
- **Middle column** (user-resizable via drag handle): 2-column filter grid with counts → one row [refresh | Check all], 50/50 → level list (`LevelListPanel`). There is no Update button: `LevelListPanel.poll_disk()` (called every frame) stats `levels/` once per second — every write goes through `_atomic_write`'s rename, which bumps the folder mtime — plus a `scandir` every 5 s for in-place edits by hand, and re-reads only the files that changed. `App._sync_open_level` then updates the level open in the editor: same tiles on disk → only the orphan status refreshes; new tiles → reloaded, unless the editor has unsaved edits (those win).
- **Right column**: "Show Shuffled" checkbox, Save/Orphan buttons, meta comparison, inline editor (`InlineEditor`) with optional shuffled view (`ShuffledView`) side-by-side.

Key classes: `TextInput`, `Checkbox`, `Dropdown` (custom widgets), `LevelListPanel` (scrollable list with per-row orphan check state tracking), `InlineEditor` (wraps `Matrix` + `RenderEditor`), `ShuffledView` (playable shuffled map in main window), `LevelCheck` (multiprocessing-based orphan solver), `ConfirmDialog`.

Preferences persist to `.launcher_prefs.json` (window size, list column width, show-shuffled, filters, gen form values).

### Editor
Two separate editors exist:
- `edit.py` / `app/editor/app_editor.py` (`AppEditor(App)`): standalone full-window editor process. Left-click rotates, right-click opens `ContextMenu` (`app/editor/context_menu.py`) to swap a tile's name/rotation/type directly. Saves back to the level's JSON (with numbered backups in `levels/backup/`).
- `launcher.py::InlineEditor`: the same editing model, but embedded inside the GUI launcher's right column (renders to an offscreen `Surface`, scaled into the panel) alongside an optional `ShuffledView` that mirrors edits live to the shuffled variant.

### Orphan checker
`tools/orphan_checker.py` (Python, CP-SAT: the whole level is one model; a check takes well under a second). There is no "limit achieved" status any more: if the time limit runs out with no orphan found, the check fails with an error and stores nothing. First it validates the solved map (`meet_map`): every lamp and pipe powered, no tile with a loose side (a connector facing the border or a neighbour without the matching connector), and no two batteries in one network — otherwise the result is `broken` (the orphan search would be vacuous: with no win state, "no win leaves a tile unpowered" is trivially true) and the bad cells go to `orphan_cells`; the launcher's level filters are `success`, `failed` (failed, broken and unchecked levels together) and `in progress`. Launched as a child `multiprocessing.Process` from `LevelCheck`. Results are written back into the level's JSON `metadata.orphan_check` field by `generate.write_orphan_check()`. The launcher batch-checks up to `BATCH_PARALLEL = 4` levels in parallel.

## Known rough edges
- `requirements.txt` includes unused `PyYAML`/`networkx` and omits `pygame`.
- `helper.show_graph()` is a no-op (networkx/matplotlib code is dead, kept commented out).
- `GritItem.color` (random) is unused dead code.
- `Cursor` (`app/models/Cursor.py`) has a pygame dependency noted as TODO to remove.
