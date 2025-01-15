from app.pygame import App
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

def run_py_game():
    data_map = get_default_figure_map()
    m = Matrix(frame_map_data=data_map)

    app = App(m)
    show_graph(m)
    show_in_console(m)
    app.run()



if __name__ == '__main__':
    # test_console()

    run_py_game()