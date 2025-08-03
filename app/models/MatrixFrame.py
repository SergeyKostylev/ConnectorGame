
import app.config as config

class MatrixFrame:
    def __init__(self, name, rotation, frame_type):
        self.__name = name
        self.__rotation = 0 # will be set in __turn_by_degrees()
        self.__matrix = config.frames[name]
        self.__turn_by_degrees(rotation)
        self.__frame_type = frame_type

    @property
    def matrix(self):
        return self.__matrix

    @property
    def name(self):
        return self.__name
    @property
    def rotation(self):
        return self.__rotation

    def is_target(self):
        return self.__frame_type == 'target'

    def is_battery(self):
        return self.__frame_type == 'battery'

    def is_pipeline(self):
        return self.__frame_type == 'pipeline'

    def has_connector(self, duration: str)-> bool:
        match duration:
            case config.DURATION_TOP:
                return self.__matrix[0][1] == 1
            case config.DURATION_RIGHT:
                return self.__matrix[1][2] == 1
            case config.DURATION_BOTTOM:
                return self.__matrix[2][1] == 1
            case config.DURATION_LEFT:
                return self.__matrix[1][0] == 1
            case _:
                raise ValueError(f'Unknown duration {duration}')

    def turn(self):
        transposed = list(zip(*self.__matrix))
        self.__matrix = [list(row)[::-1] for row in transposed]
        self.__rotation = 0 if (self.__rotation + 90) == 360 else self.__rotation + 90

    def __turn_by_degrees(self, degrees):
        for _ in range(int(degrees / 90)):
            self.turn()