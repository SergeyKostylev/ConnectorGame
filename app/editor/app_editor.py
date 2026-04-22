import os
import re
import shutil
import pygame

from app.pygame import App
from app.config import MATRIX_FRAME_RENDER_SIZE
from app.editor.context_menu import ContextMenu
from app.editor.render_editor import RenderEditor
from app.editor.top_menu import MENU_H

MF_SIZE = MATRIX_FRAME_RENDER_SIZE


class AppEditor(App):
    def __init__(self, matrix, file_path=None, version=3):
        super().__init__(matrix)
        self._App__render = RenderEditor(matrix, self.cursor)
        self._context_menu = ContextMenu()
        self._right_click_tile = None
        self._file_path = file_path
        self._version = version
        self._saved_state = self._snapshot()

    def _snapshot(self):
        return tuple(
            (f.name, f.rotation, 'battery' if f.is_battery() else 'target' if f.is_target() else 'pipeline')
            for row in self.matrix.frames_map
            for f in row
        )

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
        render = self._App__render
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.exit()
            elif event.type == pygame.MOUSEMOTION:
                self._context_menu.handle_hover(event.pos)
                render.top_menu.handle_hover(event.pos)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:
                    action = render.top_menu.handle_click(event.pos)
                    if action == 'save':
                        self.save()
                        return
                    if self._context_menu.visible:
                        item = self._context_menu.handle_click(event.pos)
                        if item is not None and self._right_click_tile is not None:
                            self.on_menu_select(item, self._right_click_tile)
                    else:
                        game_y = event.pos[1] - MENU_H
                        if game_y >= 0:
                            row, col = game_y // MF_SIZE, event.pos[0] // MF_SIZE
                            if self.matrix.frame_exist(row, col):
                                self.matrix.turn_frame(row, col)
                elif event.button == 3:
                    game_y = event.pos[1] - MENU_H
                    if game_y >= 0:
                        self._right_click_tile = (game_y // MF_SIZE, event.pos[0] // MF_SIZE)
                        self._context_menu.show(*event.pos)

    def on_menu_select(self, item, tile_pos):
        name, rotation, frame_type = item
        row, col = tile_pos
        self.matrix.replace_frame(row, col, name, rotation, frame_type)

    def _backup(self):
        backup_dir = os.path.join(os.path.dirname(self._file_path), 'backup')
        os.makedirs(backup_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(self._file_path))[0]
        existing = [f for f in os.listdir(backup_dir)
                    if re.match(rf'^{re.escape(stem)}_(\d+)\.yaml$', f)]
        numbers = [int(re.search(r'_(\d+)\.yaml$', f).group(1)) for f in existing]
        n = max(numbers) + 1 if numbers else 0
        dst = os.path.join(backup_dir, f'{stem}_{n}.yaml')
        shutil.copy2(self._file_path, dst)
        print(f"  backup: {dst}")

    def _build_data(self):
        return [
            [{'name': f.name, 'rotation': f.rotation,
              'type': 'battery' if f.is_battery() else 'target' if f.is_target() else 'pipeline'}
             for f in row]
            for row in self.matrix.frames_map
        ]

    def save(self):
        if self._snapshot() == self._saved_state:
            print("  save: no changes")
            return
        if self._file_path is None:
            print("  save: no file path specified")
            return
        import copy
        from generate import save_yaml_to
        from app.services.helper import unsort_map

        if os.path.exists(self._file_path):
            self._backup()
        data = self._build_data()
        save_yaml_to(data, self._file_path, self._version)

        shuffled_path = os.path.join(
            os.path.dirname(self._file_path), 'shuffled', os.path.basename(self._file_path)
        )
        save_yaml_to(unsort_map(copy.deepcopy(data)), shuffled_path, self._version)

        self._saved_state = self._snapshot()
        print(f"  saved: {self._file_path}")
        print(f"  saved: {shuffled_path}")
