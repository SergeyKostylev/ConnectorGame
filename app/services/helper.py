import random

import networkx as nx
import matplotlib.pyplot as plt
from app.config import MATRIX_DEFAULT_SIZE
from app.models.Matrix import Matrix
from collections import defaultdict
from app.models.MatrixFrame import MatrixFrame
import app.config as config
from app.services.DataMapGenerator import Generator


def show_graph(matrix: Matrix):
    return
    # pos = nx.get_node_attributes(matrix, 'pos')
    # nx.draw(matrix, pos, with_labels=True, node_color="lightblue", node_size=800, edge_color="gray")
    # plt.gca().invert_yaxis()
    # plt.show()

    fig, ax = plt.subplots(figsize=(8, 8))
    for node, neighbors in matrix.edges.items():
        x1, y1 = matrix.nodes[node]['pos']
        for neighbor in neighbors:
            x2, y2 = matrix.nodes[neighbor]['pos']
            ax.plot([x1, x2], [y1, y2], 'gray', zorder=1)

    for node, data in matrix.nodes.items():
        x, y = data['pos']
        ax.scatter(x, y, s=800, color='lightblue', zorder=2)
        ax.text(x, y, node, ha='center', va='center', fontsize=10, zorder=3)

    xs = [pos['pos'][0] for pos in matrix.nodes.values()]
    ys = [pos['pos'][1] for pos in matrix.nodes.values()]

    ax.set_xlim(min(xs) - 1, max(xs) + 1)
    ax.set_ylim(min(ys) - 1, max(ys) + 1)

    ax.invert_yaxis()
    ax.set_aspect('equal')
    ax.axis('off')

    plt.tight_layout()
    plt.show()

def show_in_console(matrix: Matrix):
    array = defaultdict(lambda: defaultdict(str))
    for x, y in matrix.iterate_shape():
        if x not in array:
            array[x] = {}
        array[x][y] = get_console_frame(matrix.get_frame(x, y))

    print("\n".join("".join(row.values()) for row in array.values()))


def get_default_figure_map():
    # types: pipeline, battery, target
    # data_map = [
    #     [{'name': 'i', 'rotation': 90, 'type': 'target'}, {'name': 't', 'rotation': 180, 'type': 'pipeline'}, {'name': 'g', 'rotation': 180, 'type': 'pipeline'}],
    #     [{'name': 'g', 'rotation': 270, 'type': 'pipeline'}, {'name': 'g', 'rotation': 90, 'type': 'pipeline'}, {'name': 'l', 'rotation': 90, 'type': 'pipeline'}],
    #     [{'name': 'i', 'rotation': 0, 'type': 'target'}, {'name': 'g', 'rotation': 270, 'type': 'pipeline'}, {'name': 'g', 'rotation': 270, 'type': 'pipeline'}],
    #     [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'x', 'rotation': 270, 'type': 'pipeline'}, {'name': 'g', 'rotation': 270, 'type': 'pipeline'}],
    #     [{'name': 'i', 'rotation': 0, 'type': 'target'}, {'name': 'i', 'rotation': 270, 'type': 'battery'}, {'name': 'i', 'rotation': 270, 'type': 'target'}],
    # ]

    # data_map = [[{'name': 'i', 'rotation': 270, 'type': 'missing'}, {'name': 'l', 'rotation': 90, 'type': 'pipeline'},
    #   {'name': 't', 'rotation': 0, 'type': 'pipeline'}, {'name': 'i', 'rotation': 90, 'type': 'missing'},
    #   {'name': 'i', 'rotation': 0, 'type': 'missing'}, {'name': 'i', 'rotation': 0, 'type': 'missing'}],
    #  [{'name': 'i', 'rotation': 270, 'type': 'missing'}, {'name': 'l', 'rotation': 90, 'type': 'pipeline'},
    #   {'name': 'x', 'rotation': 0, 'type': 'pipeline'}, {'name': 'i', 'rotation': 90, 'type': 'missing'},
    #   {'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 't', 'rotation': 90, 'type': 'pipeline'}],
    #  [{'name': 'i', 'rotation': 0, 'type': 'missing'}, {'name': 'i', 'rotation': 0, 'type': 'missing'},
    #   {'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'g', 'rotation': 180, 'type': 'pipeline'},
    #   {'name': 'i', 'rotation': 0, 'type': 'battery'}, {'name': 'l', 'rotation': 0, 'type': 'pipeline'}],
    #  [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 't', 'rotation': 90, 'type': 'pipeline'},
    #   {'name': 'g', 'rotation': 90, 'type': 'pipeline'}, {'name': 't', 'rotation': 90, 'type': 'pipeline'},
    #   {'name': 't', 'rotation': 270, 'type': 'pipeline'}, {'name': 't', 'rotation': 90, 'type': 'pipeline'}],
    #  [{'name': 'i', 'rotation': 0, 'type': 'missing'}, {'name': 'g', 'rotation': 0, 'type': 'pipeline'},
    #   {'name': 't', 'rotation': 90, 'type': 'pipeline'}, {'name': 'g', 'rotation': 0, 'type': 'pipeline'},
    #   {'name': 't', 'rotation': 90, 'type': 'pipeline'}, {'name': 'i', 'rotation': 180, 'type': 'missing'}],
    #  [{'name': 'g', 'rotation': 0, 'type': 'pipeline'}, {'name': 'l', 'rotation': 90, 'type': 'pipeline'},
    #   {'name': 'g', 'rotation': 270, 'type': 'pipeline'}, {'name': 'i', 'rotation': 270, 'type': 'missing'},
    #   {'name': 't', 'rotation': 180, 'type': 'pipeline'}, {'name': 'i', 'rotation': 90, 'type': 'missing'}]]

    data_map = Generator().generate(5, 5)

    # print(data_map)
    # exit()


    return unsort_map(data_map)
    return data_map


def unsort_map(map):
    for row in map:
        for cell in row:
            cell['rotation'] = random.choice([0, 90, 180, 270])

    return map


def print_pretty_figure_matrix(matrix):
    for _, i in enumerate(matrix):
        print(i)

def get_console_frame(matrix_fame: MatrixFrame):
    return config.console_symbols[f"{matrix_fame.name}{matrix_fame.rotation}"]