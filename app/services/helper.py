import networkx as nx
import matplotlib.pyplot as plt
from app.config import MATRIX_DEFAULT_SIZE


def show_graph(Matrix):
    pos = nx.get_node_attributes(Matrix, 'pos')
    nx.draw(Matrix, pos, with_labels=True, node_color="lightblue", node_size=800, edge_color="gray")
    plt.gca().invert_yaxis()
    plt.show()


def get_default_figure_map():
    # data_map = [
    #     [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'g', 'rotation': 0, 'type': 'pipeline'}],
    #     [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'g', 'rotation': 0, 'type': 'pipeline'}],
    #     [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'g', 'rotation': 0, 'type': 'pipeline'}]
    # ]
    res = []
    x, y = MATRIX_DEFAULT_SIZE
    for _ in range(y):
        res.append([{'name': 'g', 'rotation': 0, 'type': 'pipeline'} for _ in range(x)])

    return res

def print_pretty_figure_matrix(matrix):
    for _, i in enumerate(matrix):
        print(i)

