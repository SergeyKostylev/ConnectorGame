from app.services.Maze import prim_maze, draw_maze
from app.config import frames
import numpy as np


def turn(block):
    transposed = list(zip(*block))
    return [list(row)[::-1] for row in transposed]


class Generator:
    def __init__(self):
        self.__all_shapes = self.__generate_all_shapes()

    def generate(self, rows = 3, columns= 3):
        width = (rows - 1) * 3
        height = (columns - 1) * 3

        return self.__maze_data_generator(width, height)

    def __maze_data_generator(self, width, height):

        frames_shapes = self.__get_frames_shapes(width, height)

        return frames_shapes

    def __get_frames_shapes(self, width, height):
        maze = prim_maze(width, height)
        draw_maze(maze)
        res = []

        maze = self.__insert_dynamic_zeros_or_twos(maze)

        blocks = self.__get_blocks(maze)


        for i, row_blocks in enumerate(blocks):
            row = []
            for j, block in enumerate(row_blocks):
                info = self.__get_info_by_block(block)
                row.append(info)
            res.append(row)

        draw_maze(maze)

        return res

    def __get_info_by_block(self, block: list):

        for info in self.__all_shapes:
            if np.array_equal(info['shape'], block):
                type_name = 'pipeline' if info['name'] != 'i' else 'missing'
                return {'name': info['name'], 'rotation': info['rotation'], 'type': type_name}

        raise ValueError(f"unknown block {block}")


    def __generate_all_shapes(self):
        res = []
        for name, shape in frames.items():
            rotated = shape
            for rotation in [0, 90, 180, 270]:
                res.append({
                    'name': name,
                    'rotation': rotation,
                    'shape': rotated,
                })
                rotated = turn(rotated)
        return res

    def __insert_dynamic_zeros_or_twos(self, arr):
        def process_row(row):
            result = []
            insert_after = [2]
            next_step = 2
            i = 0
            while i < len(row):
                result.append(row[i])
                current_pos = len(result)
                if (current_pos - len(insert_after)) in insert_after and i < len(row) - 1:
                    left = result[-1]
                    right = row[i + 1]
                    if left == 1 and right == 1:
                        result.append(1)
                    else:
                        result.append(0)
                    insert_after.append(insert_after[-1] + next_step)
                i += 1
            return result

        processed_rows = [process_row(row) for row in arr]

        result = []
        insert_after = [2]
        next_step = 2
        i = 0
        while i < len(processed_rows):
            result.append(processed_rows[i])
            current_pos = len(result)
            if (current_pos - len(insert_after)) in insert_after and i < len(processed_rows) - 1:
                row_above = processed_rows[i]
                row_below = processed_rows[i + 1]
                new_row = []
                for a, b in zip(row_above, row_below):
                    if a == 1 and b == 1:
                        new_row.append(1)
                    else:
                        new_row.append(0)
                result.append(new_row)
                insert_after.append(insert_after[-1] + next_step)
            i += 1

        return np.array(result)

    def __get_blocks(self, maze, block_size=3):
        height, width = maze.shape
        blocks = []

        for i in range(0, height - block_size + 1, block_size):
            row = []
            for j in range(0, width - block_size + 1, block_size):
                block = maze[i:i + block_size, j:j + block_size]
                row.append(block)
            blocks.append(row)

        return blocks