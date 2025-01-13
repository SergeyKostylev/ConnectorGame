from app.models.Matrix import Matrix
from app.services.helper import *





if __name__ == '__main__':
    data_map = get_default_figure_map()

    m = Matrix(frame_map_data = data_map)
    # #
    show_graph(m)
    show_in_console(m)
    print('-------------')
    m.turn_frame(0, 0)
    m.turn_frame(0, 0)
    m.turn_frame(0, 0)


    show_in_console(m)
    show_graph(m)
