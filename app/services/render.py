import random

from typing import Dict

from app.config import MATRIX_FRAME_RENDER_SIZE
from app.models.Cursor import Cursor
from app.models.Matrix import Matrix, create_node_name
import pygame

from app.models.MatrixFrame import MatrixFrame

MF_SIZE = MATRIX_FRAME_RENDER_SIZE

textures = {}

class Render:
    def __init__(self, matrix: Matrix, cursor: Cursor):
        matrix_shape = matrix.get_shape()
        SCREEN_SIZE = (matrix_shape[1] * MF_SIZE, matrix_shape[0] * MF_SIZE)
        self.screen = pygame.Surface = pygame.display.set_mode(SCREEN_SIZE)
        self.grid: Dict[str, GritItem] = {}
        self.__set_grid(matrix)

        self.matrix = matrix
        self.cursor = cursor
        print(self.grid)

    def __set_grid(self, matrix: Matrix):
        for i, j in matrix.iterate_shape():
            position_name = create_node_name(i, j)
            frame = matrix.get_frame(i, j)
            connected_to_battery = matrix.is_connected_to_battery(i, j)
            self.grid[position_name] = self.fill_grid_item(i, j, frame, connected_to_battery)

    def fill_grid_item(self, x, y, matrix_frame: MatrixFrame, connected_to_battery: bool):
        return GritItem(
            x=y * MF_SIZE,
            y=x * MF_SIZE,
            matrix_frame=matrix_frame,
            connected_to_battery = connected_to_battery
        )

    def render(self):
        self.__set_grid(self.matrix)

        for grid in self.grid.values():
            grid.draw(self.screen)

        self.cursor.draw(self.screen)


def get_random_color():
    return random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)


class GritItem:
    def __init__(self, x, y, matrix_frame: MatrixFrame, connected_to_battery: bool):
        self.rect = pygame.Rect(x, y, MF_SIZE, MF_SIZE)
        self.matrix_frame = matrix_frame
        self.color = get_random_color()
        self.matrix_frame_name = matrix_frame.name
        self.matrix_frame_rotation = matrix_frame.rotation
        self.connected_to_battery = connected_to_battery


    def get_texture_path(self)-> str:
        if self.matrix_frame.is_pipeline():
            return f"./src/{self.matrix_frame_name}{str(self.matrix_frame_rotation)}.jpg"

        if self.matrix_frame.is_battery():
            return f"./src/battery/bat_{str(self.matrix_frame_rotation)}.jpg"


        off_on = 'on' if self.connected_to_battery else 'off'
        return f"./src/target/{off_on}_{str(self.matrix_frame_rotation)}.jpg"


    def draw(self, surface):
        if self.matrix_frame_name is not None:
            texture = self.get_frame_texture(self.get_texture_path())

            scaled_texture = pygame.transform.scale(texture, (MF_SIZE, MF_SIZE))

            surface.blit(scaled_texture, self.rect.topleft)
            pygame.draw.rect(surface, (28, 107, 160), self.rect, 1)
        else:
            pygame.draw.rect(surface, self.color, self.rect)

    def get_frame_texture(self, texture_path):
        if texture_path not in textures:
            textures[texture_path] = pygame.image.load(self.get_texture_path())

        return textures[texture_path]
