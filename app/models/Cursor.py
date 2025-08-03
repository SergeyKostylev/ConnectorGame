import pygame

from app.config import MATRIX_FRAME_RENDER_SIZE, CURSOR_COLOR

F_SIZE = MATRIX_FRAME_RENDER_SIZE


# TODO: need to get rid of pygame dependency
class Cursor:
    def __init__(self, position: tuple[int, int], max_x: int, max_y: int):
        self.__rect = pygame.Rect(position[0], position[1], F_SIZE, F_SIZE)
        self.__max_x = max_x
        self.__max_y = max_y

    def move_left(self):
        if self.__rect.x - F_SIZE >= 0:
            self.__move(-F_SIZE, 0)

    def move_right(self):
        if self.__rect.x + F_SIZE < self.__max_x:
            self.__move(F_SIZE, 0)

    def move_up(self):
        if self.__rect.y - F_SIZE >= 0:
            self.__move(0, -F_SIZE)

    def move_down(self):
        if self.__rect.y + F_SIZE < self.__max_y:
            self.__move(0, F_SIZE)

    def draw(self, surface):
        pygame.draw.rect(surface, CURSOR_COLOR, self.__rect, 5)

    def __move(self, x, y):
        self.__rect.move_ip(x, y)

    def get_position(self):
        return int(self.__rect.y / F_SIZE), int(self.__rect.x / F_SIZE)
