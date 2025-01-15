import sys
import pygame
from app.services.render import Render

from app.models.Matrix import Matrix


FPS = 60

class App:
    interval = 1000 // FPS

    def __init__(self, matrix: Matrix):
        self.__render = Render(matrix)

    def run(self):
        pygame.init()
        threshold = pygame.time.get_ticks() + self.interval
        self.__render.render()
        while True:
            current_time = pygame.time.get_ticks()
            self.process_input()
            self.update()

            if current_time > threshold:
                self.__render.test()
                self.__render.render()
                self.__render.flip_display()


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
                snake_command = None
                match event.key:
                    case pygame.K_LEFT:
                        print("LEFT")
                if snake_command is not None:
                    pass
    def __reinit_properties(self):
        pass
        # self.__snake_command_buf = []
        # self.__game_area: GameArea = build_game_area()
        # self.__info_bar = build_info_bar()


    def exit(self):
        pygame.quit()
        sys.exit()
