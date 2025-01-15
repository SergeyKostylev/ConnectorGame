import random

from pygame import Rect
from typing import Dict
from app.models.Matrix import Matrix, create_node_name
import pygame

MF_SIZE = 100


class Render:
    def __init__(self, matrix: Matrix):
        matrix_shape = matrix.get_shape()
        SCREEN_SIZE = (matrix_shape[1] * MF_SIZE, matrix_shape[0] * MF_SIZE)
        self.screen = pygame.Surface = pygame.display.set_mode(SCREEN_SIZE)

        self.grid: Dict[str, GritItem] = {}
        self.__set_grid(matrix)
        print(self.grid)

    def __set_grid(self, matrix: Matrix):
        for i, j in matrix.iterate_shape():
            name = create_node_name(i, j)
            frame = matrix.get_frame(i, j)
            self.grid[name] = GritItem(
                name,
                x=j * MF_SIZE,
                y=i * MF_SIZE,
                matrix_frame_name=frame.name,
                matrix_frame_rotation= frame.rotation
            )

    def test(self):
        pass
        # self.grid['0-1'].matrix_frame_name = None


    def render(self):
        for grid in self.grid.values():
            grid.draw(self.screen)

    def flip_display(self):
        pygame.display.flip()


def get_random_color():
    return random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)


class GritItem:
    def __init__(self, position_name, x, y, matrix_frame_name = None, matrix_frame_rotation = None):
        self.name = position_name
        self.rect = pygame.Rect(x, y, MF_SIZE, MF_SIZE)
        self.color = get_random_color()
        self.matrix_frame_name = matrix_frame_name
        self.matrix_frame_rotation = matrix_frame_rotation

    def get_texture_path(self):
        return f"./src/{self.matrix_frame_name}{str(self.matrix_frame_rotation)}.jpg"

    def draw(self, surface):
        if self.matrix_frame_name is not None:
            texture = pygame.image.load(self.get_texture_path())
            scaled_texture = pygame.transform.scale(texture, (MF_SIZE, MF_SIZE))
            surface.blit(scaled_texture, self.rect.topleft)
            pygame.draw.rect(surface, (28, 107, 160), self.rect, 1)


        else:
            pygame.draw.rect(surface, self.color, self.rect)

            # TODO: Remove
            font = pygame.font.Font(None, 36)
            text_surface = font.render(self.name, True, 'black')
            text_rect = text_surface.get_rect(center=self.rect.center)
            surface.blit(text_surface, text_rect)
