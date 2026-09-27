MATRIX_DEFAULT_SIZE = (3, 5)
MATRIX_FRAME_RENDER_SIZE = 50
EDITOR_MENU_CELL_SIZE = 33

frames = {
    "g": [[0, 1, 0],
          [0, 1, 1],
          [0, 0, 0]],

    "l": [[0, 1, 0],
          [0, 1, 0],
          [0, 1, 0]],

    "t": [[0, 0, 0],
          [1, 1, 1],
          [0, 1, 0]],

    "x": [[0, 1, 0],
          [1, 1, 1],
          [0, 1, 0]],

    "i": [[0, 0, 0],
          [0, 1, 0],
          [0, 1, 0]],

    "w": [[0, 0, 0],  # wall
          [0, 0, 0],
          [0, 0, 0]]
}

DURATION_TOP = 'top'
DURATION_RIGHT = 'right'
DURATION_BOTTOM = 'bottom'
DURATION_LEFT = 'left'

CURSOR_COLOR = (200, 50, 160)

DEBUG = 0

GENERATE_ROWS = 15
GENERATE_COLS = 15

GENERATE_BATTERIES_DENSITY = 0.05  # battery count = round(rows * cols * density)

