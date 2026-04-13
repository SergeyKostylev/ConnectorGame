import sys
import os
import re
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from app.services.DataMapGenerator import Generator
from app.services.DataMapGeneratorV2 import GeneratorV2
from app.services.DataMapGeneratorV3 import GeneratorV3
from app.services.helper import unsort_map
import app.config as config
import random as _random


def random_rows():
    return _random.randint(config.GENERATE_ROWS_MIN, config.GENERATE_ROWS_MAX)


def random_cols():
    return _random.randint(config.GENERATE_COLS_MIN, config.GENERATE_COLS_MAX)


def random_batteries(rows, cols):
    return max(1, round(rows * cols * config.GENERATE_BATTERIES_DENSITY))

SHUFFLED_DIR = os.path.join("levels", "shuffled")

LEVELS_DIR = "levels"


def next_auto_name():
    os.makedirs(LEVELS_DIR, exist_ok=True)
    existing = [
        f for f in os.listdir(LEVELS_DIR)
        if re.match(r"level_\d+\.yaml$", f)
    ]
    numbers = [int(re.search(r"\d+", f).group()) for f in existing]
    next_num = max(numbers) + 1 if numbers else 1
    return f"level_{next_num:03d}"




def stats_comments(data_map, version):
    counts = {}
    for row in data_map:
        for cell in row:
            t = cell['type']
            counts[t] = counts.get(t, 0) + 1
    total = sum(counts.values())
    lines = [f"# generator: v{version}"]
    for t in ['battery', 'target', 'pipeline', 'missing']:
        c = counts.get(t, 0)
        lines.append(f"# {t}: {c} ({c / total * 100:.1f}%)")
    return lines


def save_yaml(data_map, name, version):
    lines = [f"# {len(data_map)}x{len(data_map[0])}"]
    lines += stats_comments(data_map, version)
    for i, row in enumerate(data_map):
        lines.append(f"# row {i + 1}")
        for j, cell in enumerate(row):
            prefix = "- - " if j == 0 else "  - "
            lines.append(f"{prefix}name: {cell['name']} # {i + 1}-{j + 1}")
            lines.append(f"    rotation: {cell['rotation']}")
            lines.append(f"    type: {cell['type']}")

    path = os.path.join(LEVELS_DIR, f"{name}.yaml")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved YAML: {path}")
    return path


def save_yaml_to(data_map, path, version):
    lines = [f"# {len(data_map)}x{len(data_map[0])}"]
    lines += stats_comments(data_map, version)
    for i, row in enumerate(data_map):
        lines.append(f"# row {i + 1}")
        for j, cell in enumerate(row):
            prefix = "- - " if j == 0 else "  - "
            lines.append(f"{prefix}name: {cell['name']} # {i + 1}-{j + 1}")
            lines.append(f"    rotation: {cell['rotation']}")
            lines.append(f"    type: {cell['type']}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved YAML: {path}")


def save_image(data_map, name):
    rows = len(data_map)
    cols = len(data_map[0])

    cell = 1.0
    fig, ax = plt.subplots(figsize=(cols, rows))
    ax.set_xlim(0, cols)
    ax.set_ylim(0, rows)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.invert_yaxis()

    type_colors = {
        "battery": "#f5c542",
        "target":  "#5bc8f5",
        "pipeline": "#e8e8e8",
        "missing":  "#cccccc",
    }
    connector_color = "#333333"
    lw = 2.5

    for i, row in enumerate(data_map):
        for j, cell_data in enumerate(row):
            frame_type = cell_data.get("type", "pipeline")
            color = type_colors.get(frame_type, "#ffffff")

            rect = patches.FancyBboxPatch(
                (j + 0.05, i + 0.05), 0.9, 0.9,
                boxstyle="round,pad=0.05",
                linewidth=1,
                edgecolor="#aaaaaa",
                facecolor=color,
            )
            ax.add_patch(rect)

            name_key = cell_data["name"]
            rotation = cell_data["rotation"]

            shape = config.frames[name_key]
            from app.models.MatrixFrame import MatrixFrame
            mf = MatrixFrame(name_key, rotation, frame_type)

            cx, cy = j + 0.5, i + 0.5
            half = 0.45

            if mf.has_connector("top"):
                ax.plot([cx, cx], [cy, cy - half], color=connector_color, lw=lw, solid_capstyle="round")
            if mf.has_connector("bottom"):
                ax.plot([cx, cx], [cy, cy + half], color=connector_color, lw=lw, solid_capstyle="round")
            if mf.has_connector("left"):
                ax.plot([cx - half, cx], [cy, cy], color=connector_color, lw=lw, solid_capstyle="round")
            if mf.has_connector("right"):
                ax.plot([cx, cx + half], [cy, cy], color=connector_color, lw=lw, solid_capstyle="round")

            ax.plot(cx, cy, "o", color=connector_color, markersize=4)

    path = os.path.join(LEVELS_DIR, f"{name}.png")
    plt.savefig(path, bbox_inches="tight", dpi=96)
    plt.close()
    print(f"Saved image: {path}")
    subprocess.run(["open", path])


VERSION_FLAGS = {
    1: set(),
    2: {'batteries', 'shuffled', 'run'},
    3: {'batteries', 'shuffled', 'run', 'targets-percent'},
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
    parsed['shuffled'] = kv.get('shuffled', '1') != '0'
    parsed['rows'] = int(positional[0]) if len(positional) > 0 else None
    parsed['cols'] = int(positional[1]) if len(positional) > 1 else None

    return parsed


def validate_args(parsed):
    version = parsed['version']
    supported = VERSION_FLAGS[version]
    unsupported = []

    if parsed['batteries'] is not None and 'batteries' not in supported:
        unsupported.append('batteries')
    if not parsed['shuffled'] and 'shuffled' not in supported:
        unsupported.append('shuffled')
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
    rows = parsed['rows'] or random_rows()
    cols = parsed['cols'] or random_cols()
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
        'shuffled': shuffled,
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

    save_yaml(data_map, name, version)
    save_image(data_map, name)

    shuffled_path = None
    if shuffled:
        import copy
        shuffled_map = unsort_map(copy.deepcopy(data_map))
        shuffled_path = os.path.join(SHUFFLED_DIR, f"{name}.yaml")
        save_yaml_to(shuffled_map, shuffled_path, version)

    if run:
        from app.pygame import App
        from app.models.Matrix import Matrix
        import yaml
        run_path = shuffled_path if shuffled_path else os.path.join(LEVELS_DIR, f"{name}.yaml")
        with open(run_path) as f:
            App(Matrix(frame_map_data=yaml.safe_load(f))).run()
