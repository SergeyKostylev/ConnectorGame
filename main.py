import sys
import os
import json
import copy
from app.pygame import App
from app.services.helper import *
import app.config as config

LEVELS_DIR        = "levels"
SHUFFLED_POS_FILE = ".shuffled_window_pos.json"


class _PosTrackingApp(App):
    def on_window_moved(self, x, y):
        try:
            with open(SHUFFLED_POS_FILE, 'w') as f:
                json.dump({'x': x, 'y': y}, f)
        except Exception:
            pass


class _ViewOnlyApp(_PosTrackingApp):
    def __init__(self, matrix):
        super().__init__(matrix)
        # disable cursor rendering
        self._App__render._show_cursor = False

    def process_input(self):
        import pygame
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.exit()
            elif event.type == pygame.WINDOWMOVED:
                self.on_window_moved(event.x, event.y)


def test_console():
    data_map = get_default_figure_map()
    m = Matrix(frame_map_data=data_map)
    show_graph(m)
    show_in_console(m)
    print('-------------')
    m.turn_frame(0, 0)

    show_in_console(m)
    show_graph(m)


def run_py_game(data_map=None, track_pos=False, view_only=False):
    if data_map is None:
        data_map = get_default_figure_map()
    m = Matrix(frame_map_data=data_map)

    if track_pos:
        try:
            with open(SHUFFLED_POS_FILE) as f:
                pos = json.load(f)
            os.environ['SDL_VIDEO_WINDOW_POS'] = f"{pos['x']},{pos['y']}"
        except Exception:
            pass
        app = _ViewOnlyApp(m) if view_only else _PosTrackingApp(m)
    else:
        app = App(m)

    if config.DEBUG:
        show_graph(m)
        show_in_console(m)
    app.run()


def find_latest():
    files = sorted(f for f in os.listdir(LEVELS_DIR) if f.endswith('.json'))
    if not files:
        print(f"No levels found in {LEVELS_DIR}/")
        sys.exit(1)
    return os.path.join(LEVELS_DIR, files[-1])


def resolve_path(arg):
    return os.path.join(LEVELS_DIR, f"level_{int(arg):03d}.json") if arg.isdigit() else arg


def load_level(path, use_shuffled=False):
    if not os.path.exists(path):
        print(f"Level not found: {path}")
        sys.exit(1)
    from generate import load_level_file
    meet, shuffled, _ = load_level_file(path)
    if use_shuffled:
        return shuffled if shuffled else unsort_map(copy.deepcopy(meet))
    return meet


def log(params: dict):
    print("\n".join(f"  {k}: {v}" for k, v in params.items()) + "\n")


if __name__ == '__main__':
    args = sys.argv[1:]

    shuffled   = '--shuffled'   in args
    view_only  = '--view-only'  in args
    args = [a for a in args if a not in ('--shuffled', '--view-only')]

    if len(args) == 2 and args[0].isdigit() and args[1].isdigit():
        rows, cols = int(args[0]), int(args[1])
        log({'command': 'run', 'rows': rows, 'cols': cols})
        run_py_game(Generator().generate(rows, cols))
    elif len(args) == 1:
        path = resolve_path(args[0])
        log({'command': 'level-run', 'file': path, 'shuffled': shuffled})
        run_py_game(load_level(path, use_shuffled=shuffled), track_pos=shuffled, view_only=view_only)
    elif len(args) == 0:
        path = find_latest()
        log({'command': 'level-run', 'file': path, 'shuffled': shuffled, 'mode': 'latest'})
        run_py_game(load_level(path, use_shuffled=shuffled), track_pos=shuffled, view_only=view_only)
