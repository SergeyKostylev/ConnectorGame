# SAT generator — implementation plan

Goal: the `sat` generator (`app/services/DataMapGeneratorSat.py`) produces good-looking,
**proved orphan-free** levels controlled only by the parameters the user sets.
It must not depend on V1–V3 in any way.

**Status:** phases 0–3 implemented (not yet benchmarked — run `tools/bench_sat.py`,
A/B with `--nogood legacy` / `--no-minimize`). Phases 4–5 next.
Deviation from the plan: the single-lamp cap is `max(25 % of networks, 2·B − lamps)`,
because every network needs a lamp — with few lamps per battery the shares themselves
force more single-lamp networks (the launcher preview and the log say so).

## Requirements (agreed with the user)

- Inputs: grid size, **batteries %**, **lamps (targets) %** — always percentages of cells,
  the generator converts them to counts internally.
- **No orphans** — mandatory, proved by the CP-SAT check (CEGAR loop, see "Current state").
- A unique solution is **not** required.
- **Never** a battery connected directly to a lamp (a network with no wires).
- A network with a single lamp is fine, but not all/most of them.
- Short networks and lamps right next to the battery are fine as occasional
  exceptions, not as the norm.
- Straight tiles are **not** banned or capped.
- No other hidden rules (V3's `MIN_COMPONENT_TILES` was explicitly rejected).

## Current state (what already exists)

- `DataMapGeneratorSat.py`:
  - `_Model` — generator CP-SAT model: one shared bool per grid edge (no dangling
    connectors), deg 1..4, `tgt[v]` ⇔ non-battery dead end, exactly one parent per
    non-battery cell, **flow** formulation (a cell sends 1 + its inflow to its parent →
    no parent cycles), live edges = cells − batteries → a forest, one tree per battery;
    shape indicators `sh[v][s]` for nogoods; random edge weights as the objective.
  - Battery positions are fixed *before* the model (`_place_batteries`, random, spread);
    restarts pick a random battery count within ±5 percentage points — this is why
    level_051 got 8.3 % batteries for a requested 12 %.
  - `find_witnesses` — orphan search built on `tools/orphan_checker.build_model`
    (now returns `(m, pw, open_)`).
  - `GeneratorSat.generate` — CEGAR loop: propose → search witnesses → nogood
    "change the shape of one tile the witness rotated or left unpowered" → repeat;
    120 s budget, `sat: ...` progress lines on stdout.
- `generate.py sat rows cols batteries-percent=B targets-percent=T` — saves with
  `generator: "sat"` and `orphan_check: "success"`.
- `launcher.py` — `sat` algo button, streamed log under the Generate/Stop button.

Known problems: 11×12 at 12 %/15 % loops through 27+ candidates with 20–46 orphan
tiles each (weak nogoods); levels with few junctions look like long parallel straights.

## Key fact: the parameters fix the branching

Every network is a tree with one battery, so for the whole level:

    T-junctions + 2 × crosses = lamps − batteries

Everything else that isn't a battery/lamp is a chain tile (straight or corner).
Example level_051: 22 lamps − 11 batteries = 11 T's, the other 88 tiles (67 %) are chains.
Lamps ≤ batteries is impossible. This is not a generator bug — show it in the UI.

## Phase 0 — benchmark

`tools/bench_sat.py` — writes nothing to `levels/`. Runs 9×5, 11×12, 15×15 over a few
seeds and reports: time to a proved level, number of candidates, actual battery/lamp %,
share of single-lamp networks, short networks, lamps next to a battery. Every later
change is measured with it.

## Phase 1 — parameters

- Batteries: exactly `round(cells × %)` (min 1), no range; restarts never change it.
- Lamps: ±10 % of the requested value (at least ±1 tile), objective pulls to exact.
- Launcher (sat only): live preview under the fields —
  "batteries N · lamps M · junctions K · chains X %"; warning if lamps ≤ batteries.

## Phase 2 — model

- Batteries chosen by the solver: `bat[v]` bools, `sum == N`, a minimum spacing between
  batteries. The "new battery placement" restart layer goes away.
- Hard: no live edge between a battery and a lamp.
- Lamp flow (new, like the size flow): every lamp sends 1 to its parent, pipes forward
  the sum, a battery receives its network's lamp count.
- Soft limits = hard cap + objective penalty (constants at the top of the module):

  | measure | definition | cap |
  |---|---|---|
  | single-lamp networks | network has exactly 1 lamp | ≤ 25 % of networks |
  | short networks | size < 50 % of average (cells ÷ batteries) | ≤ 20 % of networks |
  | lamps next to battery | battery → 1 pipe → lamp (two parent links) | ≤ 10 % of lamps |

- Objective: random noise for variety + the penalties above. Nothing about straights.

## Phase 3 — sharper nogoods (CEGAR)

- Minimal witness: in the orphan search, minimise the number of tiles whose pattern
  differs from the proposed solution → the nogood hits the actual detour.
- Nogood over the rotated *powered* tiles + their powered neighbours on the border of
  the unpowered set, **without** the unpowered tiles (today the generator escapes by
  reshaping an unpowered tile, which fixes nothing). A/B against the current nogood
  with the Phase 0 benchmark.
- Nogood includes the tile type (shape + battery/lamp/pipe), since batteries are now
  variables.
- Keep: up to 4 witnesses per round, hint with the previous solution, time budget.

## Phase 4 — difficulty metric

OR-Tools has no difficulty concept; we define our own, like Simon Tatham's Net solver
(`net.c`): simulate a human solving the shuffled level.

- **Easy** — edge rule only (border sides closed, facing sides must match).
- **Medium** — + no cycles + no closed island without a battery.
- **Hard** — needs 1-step lookahead (try an orientation, propagate, contradiction).
- **Expert** — lookahead isn't enough.

Store `difficulty` (+ number of lookahead steps) in metadata; show and filter it in the
level list.

## Phase 5 — calibration, then presets

It is not known whether more lamps or more batteries makes a level harder for a player
(more batteries → smaller sub-puzzles, likely easier; more lamps → more branching but
also more "lit" feedback). So measure, don't guess:

1. Run the benchmark over a parameter grid, e.g. 11×12 with batteries 3/5/8/12 % and
   lamps 10/15/20/30 %, several levels per cell.
2. Record the Phase 4 difficulty distribution per combination.
3. Build presets "Custom / Easy / Medium / Hard" (they fill the % fields) from that table.
4. Play a few levels per preset; adjust thresholds if feel and metric disagree.
5. Later, optional: accept a candidate only if its measured difficulty is in the band.

## Files

`app/services/DataMapGeneratorSat.py`, `tools/orphan_checker.py`, `generate.py`,
`launcher.py`, new `tools/bench_sat.py`; update `CLAUDE.md` after each phase.
