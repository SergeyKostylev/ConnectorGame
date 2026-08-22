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

- `make launch` — open the GUI launcher (`launcher.py`): generate levels and edit them, all in one pygame window.
- `make generate-level-v3 rows=R cols=C batteries=N targets_percent=P run=1` — generate a level with the current generator (V3), save JSON + PNG to `levels/`.
- `make generate-level-v2 rows=R cols=C batteries=N run=1` — generate with V2 (no target-density control).
- `make generate-level-v1 rows=R cols=C` — generate with V1 (pipeline/missing only, no battery/target).
- `make level-run [N]` — run a saved level from `levels/` (latest if no arg). Add `--shuffled` via `python main.py N --shuffled` to play the shuffled variant directly.
- `make level-run-shuffled [N]` — run the shuffled variant.
- `make edit [N]` — open the standalone tile editor (`edit.py`) for a level (latest if no arg).
- `make run-default` — run the hardcoded example level in `app/services/helper.py::get_default_figure_map`.

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
Three generator versions build on each other (`app/services/DataMapGenerator*.py`):
1. **V1** (`Generator`): runs Prim's maze algorithm (`app/services/Maze.py`), slices the maze into 3×3 blocks, and matches each block against all rotations of every shape to get a `data_map` of `pipeline`/`missing` tiles. No battery/target yet.
2. **V2** (`GeneratorV2(Generator)`): takes V1's output, builds a connectivity graph over tiles, and cuts N‑1 edges (never a leaf's only edge; both resulting sides must retain a leaf) to split the maze into N independent components. Cutting an edge removes the connector from *both* adjacent tiles (shape changes, e.g. `t`→`g`), via a precomputed connection-pattern → (shape, rotation) lookup. Any pipeline tile that degenerates to `i`-shape becomes `missing`. Each resulting component gets one `missing`→`battery`, the rest `missing`→`target`.
3. **V3** (`GeneratorV3(GeneratorV2)`): runs V2, then reduces the target *density* to a target percentage (`targets_percent`, default 15%) via two tree-surgery strategies applied repeatedly until at/under the limit or no more merges are possible: **direct merge** (two adjacent targets, redirect one into the other when the shared parent has ≥3 connections) and **chain reroute** (walk up a chain of 2-connection tiles from a target to the first ≥3-connection node, splice a new edge between two adjacent targets and cut the old one). This is the generator the launcher and `make generate-level-v3` use.

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

### Editor
Two separate editors exist:
- `edit.py` / `app/editor/app_editor.py` (`AppEditor(App)`): standalone full-window editor process. Left-click rotates, right-click opens `ContextMenu` (`app/editor/context_menu.py`) to swap a tile's name/rotation/type directly. Saves back to the level's JSON (with numbered backups in `levels/backup/`).
- `launcher.py::InlineEditor`: the same editing model, but embedded inside the GUI launcher's "Edit Levels" tab (renders to an offscreen `Surface`, scaled into the panel) alongside an optional separate `ShuffledWindow` (a real `multiprocessing.Process` running its own pygame loop) that mirrors edits live to the shuffled variant.

### GUI launcher (`launcher.py`)
Single-file pygame UI (custom `TextInput`/`Checkbox`/`Dropdown`/`LevelListPanel` widgets, no framework) with two tabs: **Generate v3** (params → shells out to `generate.py v3`, or builds an empty wall-only level directly) and **Edit Levels** (browse `levels/*.json`, edit inline, optionally watch the shuffled version in a synced second window). Preferences (window size, selected tab, form values, shuffled-window position) persist to `.launcher_prefs.json`.

## Known rough edges
- `requirements.txt` includes unused `PyYAML`/`networkx` and omits `pygame`.
- `helper.show_graph()` is a no-op (networkx/matplotlib code is dead, kept commented out).
- `GritItem.color` (random) is unused dead code.
- `Cursor` (`app/models/Cursor.py`) has a pygame dependency noted as TODO to remove.
