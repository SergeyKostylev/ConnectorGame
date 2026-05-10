import pygame
from app.services.render import Render, MF_SIZE
from app.editor.top_menu import TopMenu, MENU_H


class RenderEditor(Render):
    def __init__(self, matrix, cursor, surface=None, show_menu=True):
        super().__init__(matrix, cursor, surface=surface)
        self._show_menu = show_menu
        if surface is None:
            MIN_TILES = 10
            shape = matrix.get_shape()
            w = max(shape[1] * MF_SIZE, MIN_TILES * MF_SIZE)
            h = max(shape[0] * MF_SIZE, MIN_TILES * MF_SIZE) + (MENU_H if show_menu else 0)
            self.screen = pygame.display.set_mode((w, h))
        self.top_menu = TopMenu()

    def render(self):
        self.screen.fill((0, 0, 0))
        if self._show_menu:
            game_area = self.screen.subsurface(
                pygame.Rect(0, MENU_H, self.screen.get_width(), self.screen.get_height() - MENU_H)
            )
        else:
            game_area = self.screen
        orig = self.screen
        self.screen = game_area
        self._Render__set_grid(self.matrix)
        for grid in self.grid.values():
            grid.draw(self.screen)
        self.screen = orig
        if self._show_menu:
            self.top_menu.draw(self.screen)
