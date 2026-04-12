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


def ask_filename():
    default = next_auto_name()
    user_input = input(f"Enter level name [{default}]: ").strip()
    return user_input if user_input else default


def save_yaml(data_map, name):
    lines = []
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


def save_yaml_to(data_map, path):
    lines = []
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


if __name__ == "__main__":
    args = sys.argv[1:]

    use_v2 = '--v2' in args
    args = [a for a in args if a != '--v2']

    batteries = None
    if '--batteries' in args:
        idx = args.index('--batteries')
        batteries = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    shuffled = True
    if '--shuffled' in args:
        idx = args.index('--shuffled')
        shuffled = args[idx + 1] != '0'
        args = args[:idx] + args[idx + 2:]

    rows = int(args[0]) if len(args) > 0 else random_rows()
    cols = int(args[1]) if len(args) > 1 else random_cols()

    version = 2 if use_v2 else 1
    print(f"Generating {rows}x{cols} level (v{version})...")

    if use_v2:
        if batteries is None:
            batteries = random_batteries(rows, cols)
        data_map = GeneratorV2().generate(rows, cols, batteries=batteries)
    else:
        data_map = Generator().generate(rows, cols)

    os.makedirs(LEVELS_DIR, exist_ok=True)
    name = ask_filename()

    save_yaml(data_map, name)
    save_image(data_map, name)

    if shuffled:
        import copy
        shuffled_map = unsort_map(copy.deepcopy(data_map))
        save_yaml_to(shuffled_map, os.path.join(SHUFFLED_DIR, f"{name}.yaml"))
