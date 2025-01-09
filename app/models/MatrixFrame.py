
from app.config import frames

class MatrixFrame:
    def __init__(self, name, rotation, frame_type):
        self.__name = name
        self.__matrix = frames[name]
        self.__rotation = rotation
        self.__frame_type = frame_type

    @property
    def matrix(self):
        return self.__matrix

    def has_connector(self, duration: str)-> bool:
        match duration:
            case 'top':
                return self.__matrix[0][1] == 1
            case 'right':
                return self.__matrix[1][2] == 1
            case 'bottom':
                return self.__matrix[2][1] == 1
            case 'left':
                return self.__matrix[1][0] == 1
            case _:
                raise ValueError(f'Unknown duration {duration}')

    def turn(self):
        transposed = list(zip(*self.__matrix))
        self.__matrix = [list(row)[::-1] for row in transposed]
        self.__rotation = self.__rotation + 90