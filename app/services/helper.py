import networkx as nx
import matplotlib.pyplot as plt
from app.config import MATRIX_DEFAULT_SIZE
from app.models.Matrix import Matrix
from collections import defaultdict
from app.models.MatrixFrame import MatrixFrame
import app.config as config


def show_graph(matrix: Matrix):
    pos = nx.get_node_attributes(matrix, 'pos')
    nx.draw(matrix, pos, with_labels=True, node_color="lightblue", node_size=800, edge_color="gray")
    plt.gca().invert_yaxis()
    plt.show()

def show_in_console(matrix: Matrix):
    array = defaultdict(lambda: defaultdict(str))
    for x, y in matrix.iterate_shape():
        if x not in array:
            array[x] = {}
        array[x][y] = get_console_frame(matrix.get_frame(x, y))

    print("\n".join("".join(row.values()) for row in array.values()))


def get_default_figure_map():
    data_map = [
        [{'name': 'g', 'rotation': 90, 'type': 'pipeline'}, {'name': 'g', 'rotation': 180, 'type': 'pipeline'}],
        [{'name': 't', 'rotation': 270, 'type': 'pipeline'}, {'name': 't', 'rotation': 90, 'type': 'pipeline'}],
        [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'g', 'rotation': 270, 'type': 'pipeline'}]
    ]
    return data_map
    # res = []
    # x, y = MATRIX_DEFAULT_SIZE
    # for _ in range(y):
    #     res.append([{'name': 'l', 'rotation': 0, 'type': 'pipeline'} for _ in range(x)])
    #
    # return res

def print_pretty_figure_matrix(matrix):
    for _, i in enumerate(matrix):
        print(i)

def get_console_frame(matrix_fame: MatrixFrame):
    return config.console_symbols[f"{matrix_fame.name}{matrix_fame.rotation}"]