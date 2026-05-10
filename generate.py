import sys
import os
import re
import json
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


def save_level(meet_map, shuffled_map, name, version):
    path = os.path.join(LEVELS_DIR, f"{name}.json")
    encoded_meet = [[encode_tile(c) for c in row] for row in meet_map]
    encoded_shuffled = [[encode_tile(c) for c in row] for row in shuffled_map]
    with open(path, 'w') as f:
        f.write(_format_level_json(_build_metadata(meet_map, version), encoded_meet, encoded_shuffled))
    print(f"Saved: {path}")
    return path


def save_level_to(meet_map, shuffled_map, path, version):
    encoded_meet = [[encode_tile(c) for c in row] for row in meet_map]
    encoded_shuffled = [[encode_tile(c) for c in row] for row in shuffled_map]
    dir_ = os.path.dirname(path)
    if dir_:
        os.makedirs(dir_, exist_ok=True)
    with open(path, 'w') as f:
        f.write(_format_level_json(_build_metadata(meet_map, version), encoded_meet, encoded_shuffled))
    print(f"Saved: {path}")


def _tile_path(cell):
    t, n, r = cell['type'], cell['name'], cell['rotation']
    if t == 'battery':
        return f"./src/battery/bat_{r}.jpg"
    if t == 'target':
        return f"./src/target/off_{r}.jpg"
    return f"./src/{n}{r}.jpg"


_tile_cache: dict = {}


def save_image(data_map, name):
    tile_px = config.MATRIX_FRAME_RENDER_SIZE
    rows, cols = len(data_map), len(data_map[0])
    img = Image.new('RGB', (cols * tile_px, rows * tile_px))

    draw = ImageDraw.Draw(img)
    for i, row in enumerate(data_map):
        for j, cell in enumerate(row):
            path = _tile_path(cell)
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
    save_image(data_map, name)
    if shuffled_data:
        save_image(shuffled_data, name + "_shuffled")

    if run:
        from app.pygame import App
        from app.models.Matrix import Matrix
        run_map = shuffled_data if shuffled_data else data_map
        App(Matrix(frame_map_data=run_map)).run()
