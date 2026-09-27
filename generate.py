import sys
import os
import re
import json
import fcntl
import tempfile
import contextlib
import subprocess
from PIL import Image, ImageDraw

from app.services.DataMapGenerator import Generator
from app.services.DataMapGeneratorV2 import GeneratorV2
from app.services.DataMapGeneratorV3 import GeneratorV3
from app.services.helper import unsort_map
import app.config as config



def random_batteries(rows, cols):
    return max(1, round(rows * cols * config.GENERATE_BATTERIES_DENSITY))

LEVELS_DIR = "levels"


def next_auto_name():
    os.makedirs(LEVELS_DIR, exist_ok=True)
    existing = [
        f for f in os.listdir(LEVELS_DIR)
        if re.match(r"level_\d+\.json$", f)
    ]
    numbers = [int(re.search(r"\d+", f).group()) for f in existing]
    next_num = max(numbers) + 1 if numbers else 1
    return f"level_{next_num:03d}"




def encode_tile(cell):
    return f"{cell['name']}:{cell['rotation']}:{cell['type']}"


def decode_tile(s):
    name, rotation, t = s.split(':')
    return {'name': name, 'rotation': int(rotation), 'type': t}


def decode_map(encoded):
    return [[decode_tile(cell) for cell in row] for row in encoded]


def load_level_file(path):
    with open(path) as f:
        obj = json.load(f)
    version = int(obj['metadata']['generator'][1:])
    meet = decode_map(obj['meet_map'])
    shuffled = decode_map(obj['shuffled_map']) if obj.get('shuffled_map') else []
    return meet, shuffled, version


def _build_metadata(data_map, version):
    counts = {'battery': 0, 'target': 0, 'pipeline': 0, 'wall': 0}
    for row in data_map:
        for cell in row:
            if cell['name'] == 'w':
                counts['wall'] += 1
            elif cell['type'] == 'battery':
                counts['battery'] += 1
            elif cell['type'] == 'target':
                counts['target'] += 1
            else:
                counts['pipeline'] += 1
    total = sum(counts.values())
    def fmt(k):
        c = counts[k]
        return f"{c} ({c / total * 100:.1f}%)"
    return {
        'size': f"{len(data_map)}x{len(data_map[0])}",
        'generator': f"v{version}",
        **{k: fmt(k) for k in ['battery', 'target', 'pipeline', 'wall']},
    }


def _format_map_section(label, encoded_map):
    if not encoded_map:
        return f'  "{label}": []'
    max_cell_len = max(len(f'"{cell}"') for row in encoded_map for cell in row)
    col_width = max_cell_len + 2
    lines = [f'  "{label}": [']
    for i, row in enumerate(encoded_map):
        parts = []
        for j, cell in enumerate(row):
            cell_str = f'"{cell}"'
            if j < len(row) - 1:
                parts.append((cell_str + ',').ljust(col_width))
            else:
                parts.append(cell_str.ljust(max_cell_len))
        comma = ',' if i < len(encoded_map) - 1 else ''
        lines.append(f'    [{"".join(parts)}]{comma}')
    lines.append('  ]')
    return '\n'.join(lines)


def _format_level_json(metadata, meet_map, shuffled_map):
    lines = ['{']
    lines.append('  "metadata": {')
    meta_items = list(metadata.items())
    for i, (k, v) in enumerate(meta_items):
        comma = ',' if i < len(meta_items) - 1 else ''
        lines.append(f'    {json.dumps(k)}: {json.dumps(v)}{comma}')
    lines.append('  },')
    lines.append(_format_map_section('meet_map', meet_map) + ',')
    lines.append(_format_map_section('shuffled_map', shuffled_map))
    lines.append('}')
    return '\n'.join(lines)


# ── safe writes ──────────────────────────────────────────────────────────────
# Level files are written by the editors and, concurrently, by orphan checks
# (progress while they run). Every write goes through level_lock() — one lock
# for all level files, shared by every process — and replaces the file
# atomically (temp file + os.replace), so a reader never sees half a file and
# two writers never interleave.

_LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), LEVELS_DIR, '.metadata.lock')


@contextlib.contextmanager
def level_lock():
    """Exclusive lock for reading-then-writing level files (all processes)."""
    os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
    with open(_LOCK_PATH, 'a') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write(path, text):
    """Write `text` to `path` via a temp file in the same folder + os.replace."""
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.tmp_', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def save_level(meet_map, shuffled_map, name, version):
    path = os.path.join(LEVELS_DIR, f"{name}.json")
    encoded_meet = [[encode_tile(c) for c in row] for row in meet_map]
    encoded_shuffled = [[encode_tile(c) for c in row] for row in shuffled_map]
    metadata = _with_orphan_meta(_build_metadata(meet_map, version), {})
    with level_lock():
        _atomic_write(path, _format_level_json(metadata, encoded_meet, encoded_shuffled))
    print(f"Saved: {path}")
    return path


def save_level_to(meet_map, shuffled_map, path, version):
    encoded_meet = [[encode_tile(c) for c in row] for row in meet_map]
    encoded_shuffled = [[encode_tile(c) for c in row] for row in shuffled_map]
    with level_lock():   # the carried orphan data must be what's on disk right now
        metadata = _with_orphan_meta(_build_metadata(meet_map, version),
                                     _carry_orphan_meta(path, encoded_meet))
        _atomic_write(path, _format_level_json(metadata, encoded_meet, encoded_shuffled))
    print(f"Saved: {path}")


# ── orphan check result (tools/orphan_checker.py) stored in metadata ─────────
# orphan_check:      "success" | "failed" | "limit achieved"  (absent = not checked;
#                    older files may say "incomplete" for "limit achieved")
# orphan_cells:      tiles that can stay unpowered in a win   (always present, "" if none)
# orphan_unresolved: tile that hit the search step limit — the check stops there
# orphan_stopped:    tiles not finished because the level was already failed
#                    (too expensive after an orphan was found — not verified)
# orphan_ok:         tiles proven fine — written while the check runs, so a
#                    stopped / closed check can be resumed without redoing them
# orphan_time:       how long the check took, seconds
# All of them are dropped when a tile's shape/type changes (see _carry_orphan_meta).

ORPHAN_KEYS = ('orphan_check', 'orphan_cells', 'orphan_unresolved', 'orphan_stopped',
               'orphan_ok', 'orphan_time')


def _with_orphan_meta(meta, orphan):
    """`meta` without orphan keys, then the orphan keys in a fixed order;
    orphan_cells is always written (empty when there are none)."""
    out = {k: v for k, v in meta.items() if k not in ORPHAN_KEYS}
    if 'orphan_check' in orphan:
        out['orphan_check'] = orphan['orphan_check']
    out['orphan_cells'] = orphan.get('orphan_cells', '')
    for key in ('orphan_unresolved', 'orphan_stopped', 'orphan_ok', 'orphan_time'):
        if key in orphan:
            out[key] = orphan[key]
    return out


def _shapes(encoded_map):
    """Encoded map without rotations: [["name:type", ...], ...]."""
    return [[':'.join(c.split(':')[::2]) for c in row] for row in encoded_map or []]


def level_shapes(path):
    """Shapes/types of a level's solved map — what an orphan check result depends on."""
    with open(path) as f:
        return _shapes(json.load(f).get('meet_map'))


def _carry_orphan_meta(path, encoded_meet):
    """Keep the stored check result only if no tile's shape/type changed.
    Rotations don't matter: the player rotates tiles freely anyway."""
    try:
        with open(path) as f:
            old = json.load(f)
    except Exception:
        return {}
    if _shapes(old.get('meet_map')) != _shapes(encoded_meet):
        return {}
    meta = old.get('metadata', {})
    return {k: meta[k] for k in ORPHAN_KEYS if k in meta}


def add_orphan_cells_key(path):
    """Add the (empty) orphan_cells key to a level file that lacks it;
    nothing else in the file changes. Returns True if the file was updated."""
    with level_lock():
        with open(path) as f:
            obj = json.load(f)
        if 'orphan_cells' in obj['metadata']:
            return False
        meta = _with_orphan_meta(obj['metadata'], obj['metadata'])
        _atomic_write(path, _format_level_json(meta, obj['meet_map'], obj.get('shuffled_map') or []))
    return True


def _format_cells(cells):
    return " ".join(f"({r},{c})" for r, c in cells)


def parse_cells(text):
    """"(1,2) (3,4)" -> [(1, 2), (3, 4)]"""
    return [(int(r), int(c)) for r, c in re.findall(r'\((\d+),(\d+)\)', text or '')]


def _update_orphan_meta(path, shapes, change):
    """Transaction on a level's orphan metadata: under level_lock(), re-read
    the file, and only if its tile shapes are still `shapes` (the level the
    check looked at), apply change(orphan_dict) and write atomically. Only
    orphan keys change; maps and other metadata stay as they are on disk.
    Returns False (nothing written) if the level changed meanwhile."""
    with level_lock():
        with open(path) as f:
            obj = json.load(f)
        if shapes is not None and _shapes(obj['meet_map']) != shapes:
            return False
        meta = obj['metadata']
        orphan = change({k: meta[k] for k in ORPHAN_KEYS if k in meta})
        _atomic_write(path, _format_level_json(_with_orphan_meta(meta, orphan),
                                               obj['meet_map'], obj.get('shuffled_map') or []))
    return True


def write_orphan_progress(path, shapes, ok, unused):
    """While a check runs: record the tiles proven fine so far (and orphans
    found so far — the level is failed as soon as there is one)."""
    def change(orphan):
        orphan['orphan_ok'] = _format_cells(sorted(ok))
        if unused:
            orphan['orphan_check'] = 'failed'
            orphan['orphan_cells'] = _format_cells(sorted(unused))
        return orphan
    return _update_orphan_meta(path, shapes, change)


def write_orphan_check(path, unused, unresolved, stopped=(), elapsed=None, ok=(), shapes=None):
    """Store a finished orphan check in the level's metadata. With `shapes`,
    nothing is written if the level's tiles changed since the check started."""
    def change(_old):
        if unused:
            orphan = {'orphan_check': 'failed', 'orphan_cells': _format_cells(sorted(unused))}
        elif unresolved:
            orphan = {'orphan_check': 'limit achieved'}
        else:
            orphan = {'orphan_check': 'success'}
        if unresolved:
            orphan['orphan_unresolved'] = _format_cells(unresolved)
        if stopped:
            orphan['orphan_stopped'] = _format_cells(sorted(stopped))
        if ok:
            orphan['orphan_ok'] = _format_cells(sorted(ok))
        if elapsed is not None:
            orphan['orphan_time'] = f"{elapsed:.1f}s"
        return orphan
    return _update_orphan_meta(path, shapes, change)


def _tile_path(cell, connected=False):
    t, n, r = cell['type'], cell['name'], cell['rotation']
    if t == 'battery':
        return f"./src/battery/bat_{r}.jpg"
    if t == 'target':
        off_on = 'on' if connected else 'off'
        return f"./src/target/{off_on}_{r}.jpg"
    return f"./src/{n}{r}.jpg"


_tile_cache: dict = {}


def save_image(data_map, name):
    from app.models.Matrix import Matrix
    matrix = Matrix(frame_map_data=data_map)

    tile_px = config.MATRIX_FRAME_RENDER_SIZE
    rows, cols = len(data_map), len(data_map[0])
    img = Image.new('RGB', (cols * tile_px, rows * tile_px))

    draw = ImageDraw.Draw(img)
    for i, row in enumerate(data_map):
        for j, cell in enumerate(row):
            connected = matrix.is_connected_to_battery(i, j)
            path = _tile_path(cell, connected=connected)
            if path not in _tile_cache:
                _tile_cache[path] = Image.open(path).convert('RGB').resize(
                    (tile_px, tile_px), Image.LANCZOS
                )
            x, y = j * tile_px, i * tile_px
            img.paste(_tile_cache[path], (x, y))
            draw.rectangle((x, y, x + tile_px - 1, y + tile_px - 1), outline=(28, 107, 160), width=1)

    out = os.path.join(LEVELS_DIR, f"{name}.png")
    img.save(out)
    print(f"Saved image: {out}")


VERSION_FLAGS = {
    1: set(),
    2: {'batteries', 'run'},
    3: {'batteries', 'run', 'targets-percent'},
}


def parse_args(args):
    parsed = {}

    # key=value та boolean флаги
    kv = {}
    bools = set()
    positional = []
    for a in args:
        if '=' in a:
            k, v = a.split('=', 1)
            kv[k] = v
        elif a in ('v2', 'v3', 'run'):
            bools.add(a)
        else:
            positional.append(a)

    parsed['version'] = 3 if 'v3' in bools else (2 if 'v2' in bools else 1)
    parsed['run'] = 'run' in bools
    parsed['batteries'] = int(kv['batteries']) if 'batteries' in kv else None
    parsed['targets_percent'] = float(kv['targets-percent']) if 'targets-percent' in kv else None
    parsed['shuffled'] = True
    parsed['rows'] = int(positional[0]) if len(positional) > 0 else None
    parsed['cols'] = int(positional[1]) if len(positional) > 1 else None

    return parsed


def validate_args(parsed):
    version = parsed['version']
    supported = VERSION_FLAGS[version]
    unsupported = []

    if parsed['batteries'] is not None and 'batteries' not in supported:
        unsupported.append('batteries')
    if parsed['run'] and 'run' not in supported:
        unsupported.append('run')
    if parsed['targets_percent'] is not None and 'targets-percent' not in supported:
        unsupported.append('targets-percent')

    if unsupported:
        print(f"Error: v{version} does not support: {', '.join(unsupported)}")
        sys.exit(1)

    if parsed['targets_percent'] is not None and not (0 < parsed['targets_percent'] < 100):
        print(f"Error: targets-percent must be between 0 and 100 (got {parsed['targets_percent']})")
        sys.exit(1)


if __name__ == "__main__":
    parsed = parse_args(sys.argv[1:])
    validate_args(parsed)

    version = parsed['version']
    rows = parsed['rows'] or config.GENERATE_ROWS
    cols = parsed['cols'] or config.GENERATE_COLS
    batteries = parsed['batteries']
    shuffled = parsed['shuffled']
    run = parsed['run']
    targets_percent = parsed['targets_percent']

    params = {
        'command': 'generate-level',
        'version': version,
        'rows': rows,
        'cols': cols,
        'batteries': batteries if batteries is not None else 'random',
        'targets_percent': f'{targets_percent}%' if targets_percent is not None else 'default',
        'run': run,
    }
    if version != 3:
        del params['targets_percent']
    print("\n".join(f"  {k}: {v}" for k, v in params.items()) + "\n")

    if version == 3:
        if batteries is None:
            batteries = random_batteries(rows, cols)
        target_limit = round(rows * cols * targets_percent / 100) if targets_percent is not None else None
        data_map = GeneratorV3().generate(rows, cols, batteries=batteries, target_limit=target_limit)
    elif version == 2:
        if batteries is None:
            batteries = random_batteries(rows, cols)
        data_map = GeneratorV2().generate(rows, cols, batteries=batteries)
    else:
        data_map = Generator().generate(rows, cols)

    os.makedirs(LEVELS_DIR, exist_ok=True)
    name = next_auto_name()

    import copy
    shuffled_data = unsort_map(copy.deepcopy(data_map)) if shuffled else []
    save_level(data_map, shuffled_data, name, version)

    if run:
        from app.pygame import App
        from app.models.Matrix import Matrix
        run_map = shuffled_data if shuffled_data else data_map
        App(Matrix(frame_map_data=run_map)).run()
