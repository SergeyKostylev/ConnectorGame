import sys
import os
import yaml

from app.pygame import App
from app.models.Matrix import Matrix
from app.services.helper import unsort_map
from app.services.DataMapGenerator import Generator

LEVELS_DIR = "levels"
SHUFFLED_DIR = os.path.join(LEVELS_DIR, "shuffled")


def resolve_name(arg):
    return f"level_{int(arg):03d}" if arg.isdigit() else arg


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def save_yaml(data_map, path):
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
    print(f"Saved: {path}")


def run_level(path):
    data_map = load_yaml(path)
    m = Matrix(frame_map_data=data_map)
    App(m).run()


if __name__ == "__main__":
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if not args:
        print("Usage: python run_shuffled.py <level> [--force]")
        sys.exit(1)

    name = resolve_name(args[0])
    original_path = os.path.join(LEVELS_DIR, f"{name}.yaml")
    shuffled_path = os.path.join(SHUFFLED_DIR, f"{name}.yaml")

    if not os.path.exists(shuffled_path):
        if not os.path.exists(original_path):
            if not force:
                print(f"Level '{name}' not found in {LEVELS_DIR}/")
                sys.exit(1)
            rows = int(input("Rows: "))
            cols = int(input("Cols: "))
            data_map = Generator().generate(rows, cols)
            save_yaml(data_map, original_path)
        else:
            data_map = load_yaml(original_path)

        unsort_map(data_map)
        save_yaml(data_map, shuffled_path)

    run_level(shuffled_path)
