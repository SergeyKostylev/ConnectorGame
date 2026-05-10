import sys
import os
import copy

from app.pygame import App
from app.models.Matrix import Matrix
from app.services.helper import unsort_map
from app.services.DataMapGenerator import Generator

LEVELS_DIR = "levels"


def resolve_name(arg):
    return f"level_{int(arg):03d}" if arg.isdigit() else arg


if __name__ == "__main__":
    args = sys.argv[1:]
    force = "--force" in args
    args = [a for a in args if a != "--force"]

    if not args:
        print("Usage: python run_shuffled.py <level> [--force]")
        sys.exit(1)

    name = resolve_name(args[0])
    path = os.path.join(LEVELS_DIR, f"{name}.json")

    if not os.path.exists(path):
        if not force:
            print(f"Level '{name}' not found in {LEVELS_DIR}/")
            sys.exit(1)
        rows = int(input("Rows: "))
        cols = int(input("Cols: "))
        data_map = Generator().generate(rows, cols)
        from generate import save_level
        shuffled = unsort_map(copy.deepcopy(data_map))
        save_level(data_map, shuffled, name, version=1)

    from generate import load_level_file
    meet, shuffled, _ = load_level_file(path)
    run_map = shuffled if shuffled else unsort_map(copy.deepcopy(meet))
    App(Matrix(frame_map_data=run_map)).run()
