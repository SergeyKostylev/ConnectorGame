from app.models.Matrix import Matrix
from app.services.helper import *




if __name__ == '__main__':
    x = 0
    y = 0
    data_map = get_default_figure_map()

    m = Matrix(frame_map_data = data_map)
    #
    show_graph(m)

