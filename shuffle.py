import sys
import os
import yaml

from app.services.helper import unsort_map

LEVELS_DIR = "levels"
SHUFFLED_DIR = os.path.join(LEVELS_DIR, "shuffled")


def save_yaml(data_map, name):
    lines = []
    for i, row in enumerate(data_map):
        lines.append(f"# row {i + 1}")
        for j, cell in enumerate(row):
            prefix = "- - " if j == 0 else "  - "
            lines.append(f"{prefix}name: {cell['name']} # {i + 1}-{j + 1}")
            lines.append(f"    rotation: {cell['rotation']}")
            lines.append(f"    type: {cell['type']}")

    os.makedirs(SHUFFLED_DIR, exist_ok=True)
    path = os.path.join(SHUFFLED_DIR, name)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved: {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shuffle.py <level.yaml>")
        sys.exit(1)

    source_path = sys.argv[1]
    with open(source_path) as f:
        data_map = yaml.safe_load(f)

    unsort_map(data_map)

    filename = os.path.basename(source_path)
    save_yaml(data_map, filename)
