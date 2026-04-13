import sys
import os
import yaml
from app.pygame import App
from app.services.helper import *
import app.config as config

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
    if config.DEBUG:
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


def log(params: dict):
    print("\n".join(f"  {k}: {v}" for k, v in params.items()) + "\n")


if __name__ == '__main__':
    args = sys.argv[1:]

    shuffled = '--shuffled' in args
    args = [a for a in args if a != '--shuffled']
    folder = SHUFFLED_DIR if shuffled else LEVELS_DIR

    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        rows, cols = int(args[0]), int(args[1])
        log({'command': 'run', 'rows': rows, 'cols': cols})
        run_py_game(Generator().generate(rows, cols))
    elif len(args) == 1:
        path = resolve_path(args[0], folder)
        log({'command': 'level-run', 'file': path, 'shuffled': shuffled})
        run_py_game(load_level(path))
    elif len(args) == 0:
        path = find_latest(folder)
        log({'command': 'level-run', 'file': path, 'shuffled': shuffled, 'mode': 'latest'})
        run_py_game(load_level(path))
