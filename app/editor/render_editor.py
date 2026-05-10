import pygame
from app.services.render import Render, MF_SIZE
from app.editor.top_menu import TopMenu, MENU_H


class RenderEditor(Render):
    def __init__(self, matrix, cursor):
        super().__init__(matrix, cursor)
        MIN_TILES = 10
        shape = matrix.get_shape()
        w = max(shape[1] * MF_SIZE, MIN_TILES * MF_SIZE)
        h = max(shape[0] * MF_SIZE, MIN_TILES * MF_SIZE) + MENU_H
        self.screen = pygame.display.set_mode((w, h))
        self.top_menu = TopMenu()

    def render(self):
        self.screen.fill((0, 0, 0))
        game_area = self.screen.subsurface(
            pygame.Rect(0, MENU_H, self.screen.get_width(), self.screen.get_height() - MENU_H)
        )
        orig = self.screen
        self.screen = game_area
        self._Render__set_grid(self.matrix)
        for grid in self.grid.values():
            grid.draw(self.screen)
        self.screen = orig
        self.top_menu.draw(self.screen)
