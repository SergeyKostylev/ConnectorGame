from app.models.Matrix import Matrix, create_node_name
from app.models.MatrixFrame import MatrixFrame


class MatrixEditor(Matrix):
    def replace_frame(self, x, y, name, rotation, frame_type):
        old_frame = self.get_frame(x, y)
        node_name = create_node_name(x, y)

        if old_frame.is_target():
            self._Matrix__targets_position_names.discard(node_name)
        elif old_frame.is_battery():
            self._Matrix__batteries_position_names.discard(node_name)

        self.frames_map[x][y] = MatrixFrame(name, rotation, frame_type)

        if frame_type == 'target':
            self._Matrix__targets_position_names.add(node_name)
        elif frame_type == 'battery':
            self._Matrix__batteries_position_names.add(node_name)

        self.reconnect_one(x, y, True)
