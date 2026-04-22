import pygame

from app.pygame import App
from app.config import MATRIX_FRAME_RENDER_SIZE
from app.editor.context_menu import ContextMenu

MF_SIZE = MATRIX_FRAME_RENDER_SIZE


class AppEditor(App):
    def __init__(self, matrix):
        super().__init__(matrix)
        self._context_menu = ContextMenu()
        self._right_click_tile = None

    def run(self):
        pygame.init()
        render = self._App__render
        threshold = pygame.time.get_ticks() + self.interval
        render.render()
        while True:
            current_time = pygame.time.get_ticks()
            self.process_input()
            self.update()

            if current_time > threshold:
                render.render()
                self._context_menu.draw(render.screen)
                pygame.display.flip()
                threshold += self.interval

    def process_input(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.exit()
            elif event.type == pygame.MOUSEMOTION:
                self._context_menu.handle_hover(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3:
                    self._right_click_tile = (event.pos[1] // MF_SIZE, event.pos[0] // MF_SIZE)
                    self._context_menu.show(*event.pos)
                elif event.button == 1:
                    item = self._context_menu.handle_click(event.pos)
                    if item is not None and self._right_click_tile is not None:
                        self.on_menu_select(item, self._right_click_tile)

    def on_menu_select(self, item, tile_pos):
        name, rotation, frame_type = item
        row, col = tile_pos
        self.matrix.replace_frame(row, col, name, rotation, frame_type)
