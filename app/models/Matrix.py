from app.config import frames
import networkx as nx
import random

from app.models.MatrixFrame import MatrixFrame


class Matrix(nx.Graph):
    def __init__(self, frame_map_data: list, **attr):
        super().__init__(**attr)
        self.frames_map: list[MatrixFrame] = []
        self.__fill_frame_map(frame_map_data)
        # TODO: mix if need
        self.__fill_graph()

    def __fill_frame_map(self, frame_map_data):
        """ one element: {'name': 'g', 'rotation': 0, 'type': 'pipeline'}"""
        self.frames_map = [[0] * len(frame_map_data[0]) for _ in range(len(frame_map_data))]
        print(self.frames_map)
        for i, j in self.iterate_shape():
            f_data = frame_map_data[i][j]
            self.frames_map[i][j] = MatrixFrame(f_data['name'], f_data['rotation'], f_data['type'])


    def __fill_graph(self):
        for x, y in self.iterate_shape():
            self.add_node(create_node_name(x, y), pos=(y, x)) #pos (y, x) is correct

        for x, y in self.iterate_shape():
            neighbor_connection_index = random.choice(list(frames.keys()))
            self.__set_orientation(x, y, neighbor_connection_index)
            # print(f"{x} x {y}")

    def turn_frame(self, x, y):
        self.frames_map[x][y].turn()
        # TODO: recalculate graph
        # TODO: recalculate connectors

    def get_frame(self, x, y)-> MatrixFrame:
        return self.frames_map[x][y]

    def get_shape(self):
        return len(self.frames_map), len(self.frames_map[0])

    def __set_orientation(self, i, j, neighbor_connection_index):
        # TODO: Add edges
        pass
        # if i == 1 and j == 1:  # add 3: "┘"
        #     neighbor_connection_index = 3
            # self.add_edge(create_node_name(i, j), '1-0')
            # self.add_edge(create_node_name(i, j), '0-1')

    def iterate_shape(self):
        x, y = self.get_shape()
        for i in range(x):
            for j in range(y):
                yield i, j

    def get_frames_map(self)-> list[MatrixFrame]:
        return self.frames_map

def create_node_name(i, j):
    return f"{i}-{j}"
