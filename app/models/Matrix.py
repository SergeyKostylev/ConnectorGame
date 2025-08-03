from app.models.GraphHelper import GraphHelper
from app.models.MatrixFrame import MatrixFrame
import app.config as config

class Matrix(GraphHelper):
    def __init__(self, frame_map_data: list):
        super().__init__()
        self.frames_map: list[MatrixFrame] = []
        self.__targets_position_names = set() # see create_node_name()
        self.__batteries_position_names = set() # see create_node_name()
        self.__fill_frame_map(frame_map_data)
        self.__fill_graph()
        self.__last_touched_frames = set()

    def __fill_frame_map(self, frame_map_data):
        """ one element: {'name': 'g', 'rotation': 0, 'type': 'pipeline'}"""
        self.frames_map = [[0] * len(frame_map_data[0]) for _ in range(len(frame_map_data))]
        print(self.frames_map)
        for i, j in self.iterate_shape():
            f_data = frame_map_data[i][j]
            mf = MatrixFrame(f_data['name'], f_data['rotation'], f_data['type'])
            self.frames_map[i][j] = mf
            self.__registrate_frame_as_target_or_battery(i, j, mf)

    def __fill_graph(self):
        for x, y in self.iterate_shape():
            self.add_node(create_node_name(x, y), pos=(y, x))  # pos (y, x) is correct

        self.reconnect_all()

    def __registrate_frame_as_target_or_battery(self, i, j, mf : MatrixFrame):
        if mf.is_pipeline():
            return

        name = create_node_name(i, j)

        if mf.is_target():
            self.__targets_position_names.add(name)
        elif mf.is_battery():
            self.__batteries_position_names.add(name)


    def turn_frame(self, x, y):
        self.frames_map[x][y].turn()
        self.reconnect_one(x, y, True)
        self.__last_touched_frames.add((x, y))

    def get_last_touched_frame(self) -> set | None:
        return self.__last_touched_frames.pop() if len(self.__last_touched_frames) != 0 else None

    def get_frame(self, x, y) -> MatrixFrame:
        return self.frames_map[x][y]

    def is_connected_to_battery(self, i, j) -> bool:
        """ if an element is battery returns True if it connected with other battery """
        element_pos_name = create_node_name(i, j)
        res = False

        for battery in self.__batteries_position_names:
            if element_pos_name == battery:
                continue
            if self.has_path(element_pos_name, battery):
                res = True
                break

        return res

    def get_frame_or_none(self, x, y) -> MatrixFrame | None:
        return self.get_frame(x, y) if self.frame_exist(x, y) else None

    def frame_exist(self, x, y) -> bool:
        return x >= 0 and y >= 0 and x < len(self.frames_map) and y < len(self.frames_map[x])

    def get_shape(self):
        return len(self.frames_map), len(self.frames_map[0])

    def connect_frames(self, nodeName1: str, nodeName2: str):
        self.add_edge(nodeName1, nodeName2)

    def disconnect_frames(self, nodeName1: str, nodeName2: str):
        if self.has_edge(nodeName1, nodeName2):
            self.remove_edge(nodeName1, nodeName2)

    def iterate_shape(self):
        x, y = self.get_shape()
        for i in range(x):
            for j in range(y):
                yield i, j

    def get_frames_map(self) -> list[MatrixFrame]:
        return self.frames_map

    def reconnect_all(self):
        for x, y in self.iterate_shape():
            self.reconnect_one(x, y, False)  # not need to check top and left

    def reconnect_one(self, x, y, check_top_and_left=True):
        current_frame = self.get_frame(x, y)
        current_node_name = create_node_name(x, y)

        # TODO need to refactoring
        right_neighbor = self.get_frame_or_none(x, y + 1)
        if right_neighbor is not None:
            right_node_name = create_node_name(x, y + 1)
            if current_frame.has_connector(config.DURATION_RIGHT) & right_neighbor.has_connector(config.DURATION_LEFT):
                self.connect_frames(current_node_name, right_node_name)
            else:
                self.disconnect_frames(current_node_name, right_node_name)

        bottom_neighbor = self.get_frame_or_none(x + 1, y)
        if bottom_neighbor is not None:
            bottom_node_name = create_node_name(x + 1, y)
            if current_frame.has_connector(config.DURATION_BOTTOM) & bottom_neighbor.has_connector(config.DURATION_TOP):
                self.connect_frames(current_node_name, bottom_node_name)
            else:
                self.disconnect_frames(current_node_name, bottom_node_name)
        if check_top_and_left is False:
            return

        left_neighbor = self.get_frame_or_none(x, y - 1)
        if left_neighbor is not None:
            left_node_name = create_node_name(x, y - 1)
            if current_frame.has_connector(config.DURATION_LEFT) & left_neighbor.has_connector(config.DURATION_RIGHT):
                self.connect_frames(current_node_name, left_node_name)
            else:
                self.disconnect_frames(current_node_name, left_node_name)

        top_neighbor = self.get_frame_or_none(x - 1, y)
        if top_neighbor is not None:
            top_node_name = create_node_name(x - 1, y)
            if current_frame.has_connector(config.DURATION_TOP) & top_neighbor.has_connector(config.DURATION_BOTTOM):
                self.connect_frames(current_node_name, top_node_name)
            else:
                self.disconnect_frames(current_node_name, top_node_name)


def create_node_name(i, j)-> str:
    return f"{i}-{j}"
