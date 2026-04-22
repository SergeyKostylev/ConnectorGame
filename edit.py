import sys
import os
import yaml

from app.editor.app_editor import AppEditor
from app.editor.matrix_editor import MatrixEditor

LEVELS_DIR = "levels"


def resolve_path(arg):
    return os.path.join(LEVELS_DIR, f"level_{int(arg):03d}.yaml") if arg.isdigit() else arg


def find_latest():
    files = sorted(f for f in os.listdir(LEVELS_DIR) if f.endswith('.yaml'))
    if not files:
        print("No levels found")
        sys.exit(1)
    return os.path.join(LEVELS_DIR, files[-1])


def load_level(path):
    if not os.path.exists(path):
        print(f"Level not found: {path}")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


if __name__ == '__main__':
    args = sys.argv[1:]
    path = resolve_path(args[0]) if args else find_latest()
    data_map = load_level(path)
    print(f"  command: edit\n  file: {path}\n")
    AppEditor(MatrixEditor(frame_map_data=data_map)).run()
