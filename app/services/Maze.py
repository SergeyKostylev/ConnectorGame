import random
import matplotlib.pyplot as plt
import numpy as np

WALL = 0
PASSAGE = 1

def create_grid(width, height):
    # Создаем полностью заполненное поле стенами
    grid = np.zeros((height, width), dtype=int)
    return grid

def neighbors(x, y, grid):
    directions = [(-2, 0), (2, 0), (0, -2), (0, 2)]
    result = []
    for dx, dy in directions:
        nx, ny = x + dx, y + dy
        if 0 < nx < grid.shape[1] and 0 < ny < grid.shape[0]:
            result.append((nx, ny))
    return result

def prim_maze(width, height):
    if width % 2 == 0: width += 1
    if height % 2 == 0: height += 1

    grid = create_grid(width, height)

    start_x = random.randrange(1, width, 2)
    start_y = random.randrange(1, height, 2)
    grid[start_y, start_x] = PASSAGE

    walls = []
    for nx, ny in neighbors(start_x, start_y, grid):
        walls.append(((start_x, start_y), (nx, ny)))

    while walls:
        (x1, y1), (x2, y2) = walls.pop(random.randint(0, len(walls)-1))
        if grid[y2, x2] == WALL:
            grid[(y1 + y2)//2, (x1 + x2)//2] = PASSAGE
            grid[y2, x2] = PASSAGE
            for nx, ny in neighbors(x2, y2, grid):
                if grid[ny, nx] == WALL:
                    walls.append(((x2, y2), (nx, ny)))

    return grid

def draw_maze(grid):
    plt.figure(figsize=(10, 10))
    plt.imshow(grid, cmap='binary')  # 'binary' = белый (1) и черный (0)
    plt.axis('off')
    plt.show()

# Пример использования
def maze():
    maze = prim_maze(9, 9)






    print(maze)

    draw_maze(maze)
