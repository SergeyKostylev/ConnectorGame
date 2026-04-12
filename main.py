import sys
from app.pygame import App
from app.services.DataMapGenerator import Generator
from app.services.helper import *


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


if __name__ == '__main__':
    if len(sys.argv) == 3:
        rows, cols = int(sys.argv[1]), int(sys.argv[2])
        run_py_game(Generator().generate(rows, cols))
    else:
        run_py_game()
