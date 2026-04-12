import sys
import os
import yaml
from app.pygame import App
from app.services.helper import *

LEVELS_DIR = "levels"
SHUFFLED_DIR = os.path.join(LEVELS_DIR, "shuffled")


def test_console():
    data_map = get_default_figure_map()
    m = Matrix(frame_map_data=data_map)
    show_graph(m)
    show_in_console(m)
    print('-------------')
    m.turn_frame(0, 0)

    show_in_console(m)
    show_graph(m)


def run_py_game(data_map=None):
    if data_map is None:
        data_map = get_default_figure_map()
    m = Matrix(frame_map_data=data_map)

    app = App(m)
    show_graph(m)
    show_in_console(m)
    app.run()


def find_latest(folder):
    files = sorted(f for f in os.listdir(folder) if f.endswith('.yaml'))
    if not files:
        print(f"No levels found in {folder}/")
        sys.exit(1)
    return os.path.join(folder, files[-1])


def resolve_path(arg, folder):
    return os.path.join(folder, f"level_{int(arg):03d}.yaml") if arg.isdigit() else arg


def load_level(path):
    if not os.path.exists(path):
        print(f"Level not found: {path}")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


if __name__ == '__main__':
    args = sys.argv[1:]

    shuffled = '--shuffled' in args
    args = [a for a in args if a != '--shuffled']
    folder = SHUFFLED_DIR if shuffled else LEVELS_DIR

    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        run_py_game(Generator().generate(int(args[0]), int(args[1])))
    elif len(args) == 1:
        run_py_game(load_level(resolve_path(args[0], folder)))
    elif len(args) == 0 and shuffled:
        run_py_game(load_level(find_latest(folder)))
    elif len(args) == 0:
        run_py_game(load_level(find_latest(LEVELS_DIR)))
