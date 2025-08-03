import sys
import pygame

from app.config import MATRIX_FRAME_RENDER_SIZE
from app.services.helper import show_graph
from app.services.render import Render, Cursor
from app.models.Matrix import Matrix


FPS = 24

class App:
    interval = 1000 // FPS

    def __init__(self, matrix: Matrix):
        cursor_max_x = matrix.get_shape()[1] * MATRIX_FRAME_RENDER_SIZE
        cursor_max_y = matrix.get_shape()[0] * MATRIX_FRAME_RENDER_SIZE
        self.cursor = Cursor((0, 0), cursor_max_x, cursor_max_y)
        self.matrix = matrix
        self.__render = Render(matrix, self.cursor)

    def run(self):
        pygame.init()
        threshold = pygame.time.get_ticks() + self.interval
        self.__render.render()
        while True:
            current_time = pygame.time.get_ticks()
            self.process_input()
            self.update()

            if current_time > threshold:
                self.__render.render()
                # self.__render.render_new(self.matrix, self.cursor)

                pygame.display.flip()

                threshold += self.interval

    def update(self):
        pass
        # while len(self.__snake_command_buf) != 0:
        #     self.__game_area.add_snake_turn_command(self.__snake_command_buf.pop(0))

    def process_input(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.exit()

            elif event.type == pygame.KEYDOWN:
                command = None
                match event.key:
                    case pygame.K_LEFT:
                        self.cursor.move_left()
                    case pygame.K_RIGHT:
                        self.cursor.move_right()
                    case pygame.K_UP:
                        self.cursor.move_up()
                    case pygame.K_DOWN:
                        self.cursor.move_down()
                    case pygame.K_SPACE:
                        px, py = self.cursor.get_position()
                        self.matrix.turn_frame(px, py)
                        show_graph(self.matrix)
                if command is not None:
                    pass
    def __reinit_properties(self):
        pass
        # self.__snake_command_buf = []
        # self.__game_area: GameArea = build_game_area()
        # self.__info_bar = build_info_bar()


    def exit(self):
        pygame.quit()
        sys.exit()
