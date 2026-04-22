import pygame
from app.config import EDITOR_MENU_CELL_SIZE

CELL = EDITOR_MENU_CELL_SIZE
PAD = 4
HEADER_H = 16
COL_GAP = 3

BG = (45, 45, 45)
CELL_BG = (210, 210, 210)
HOVER_BG = (255, 240, 120)
BORDER = (20, 20, 20)
HEADER_BG = (70, 80, 140)
HEADER_FG = (255, 255, 255)


def _path(name, rotation, frame_type):
    if frame_type == 'battery':
        return f"./src/battery/bat_{rotation}.jpg"
    if frame_type == 'target':
        return f"./src/target/off_{rotation}.jpg"
    return f"./src/{name}{rotation}.jpg"


COLUMNS = [
    {
        'title': 'Pipeline',
        'grid_cols': 4,
        'items': (
            [('g', r, 'pipeline') for r in [0, 90, 180, 270]] +
            [('l', r, 'pipeline') for r in [0, 90]] +
            [('t', r, 'pipeline') for r in [0, 90, 180, 270]] +
            [('x', r, 'pipeline') for r in [0]]
        ),
    },
    {
        'title': 'Target',
        'grid_cols': 1,
        'items': [('i', r, 'target') for r in [0, 90, 180, 270]],
    },
    {
        'title': 'Battery',
        'grid_cols': 1,
        'items': [('i', r, 'battery') for r in [0, 90, 180, 270]],
    },
    {
        'title': 'Wall',
        'grid_cols': 1,
        'items': [('w', 0, 'pipeline')],
    },
]


class ContextMenu:
    def __init__(self):
        self.visible = False
        self.x = 0
        self.y = 0
        self._font = None
        self._cache = {}
        self._rects = []
        self._hovered = -1

    def _menu_size(self):
        w = PAD * 2 - COL_GAP
        max_rows = 0
        for col in COLUMNS:
            gc = col['grid_cols']
            rows = (len(col['items']) + gc - 1) // gc
            max_rows = max(max_rows, rows)
            w += gc * CELL + COL_GAP
        h = PAD * 2 + HEADER_H + max_rows * CELL
        return w, h

    def show(self, x, y):
        w, h = self._menu_size()
        screen = pygame.display.get_surface()
        if screen:
            sw, sh = screen.get_size()
            x = min(x, sw - w)
            y = min(y, sh - h)
        self.x = max(0, x)
        self.y = max(0, y)
        self.visible = True
        self._hovered = -1
        self._build_rects()

    def hide(self):
        self.visible = False
        self._rects = []

    def _font_get(self):
        if self._font is None:
            self._font = pygame.font.SysFont(None, 14)
        return self._font

    def _build_rects(self):
        self._rects = []
        cx = self.x + PAD
        for col in COLUMNS:
            gc = col['grid_cols']
            cy = self.y + PAD + HEADER_H
            for idx, item in enumerate(col['items']):
                rx = cx + (idx % gc) * CELL
                ry = cy + (idx // gc) * CELL
                self._rects.append((pygame.Rect(rx, ry, CELL - 2, CELL - 2), item))
            cx += gc * CELL + COL_GAP

    def _texture(self, name, rotation, frame_type):
        path = _path(name, rotation, frame_type)
        if path not in self._cache:
            try:
                img = pygame.image.load(path)
                self._cache[path] = pygame.transform.scale(img, (CELL - 4, CELL - 4))
            except Exception:
                self._cache[path] = None
        return self._cache[path]

    def handle_hover(self, pos):
        if not self.visible:
            return
        self._hovered = -1
        for i, (rect, _) in enumerate(self._rects):
            if rect.collidepoint(pos):
                self._hovered = i
                return

    def handle_click(self, pos):
        """Returns (name, rotation, frame_type) tuple or None."""
        if not self.visible:
            return None
        for rect, item in self._rects:
            if rect.collidepoint(pos):
                self.hide()
                return item
        self.hide()
        return None

    def draw(self, surface):
        if not self.visible:
            return

        total_w, total_h = self._menu_size()
        pygame.draw.rect(surface, BG, (self.x, self.y, total_w, total_h))
        pygame.draw.rect(surface, BORDER, (self.x, self.y, total_w, total_h), 1)

        font = self._font_get()
        cx = self.x + PAD
        col_idx_offset = 0

        for col in COLUMNS:
            gc = col['grid_cols']
            items = col['items']
            col_w = gc * CELL

            pygame.draw.rect(surface, HEADER_BG, (cx, self.y + PAD, col_w, HEADER_H))
            txt = font.render(col['title'], True, HEADER_FG)
            surface.blit(txt, (cx + (col_w - txt.get_width()) // 2,
                               self.y + PAD + (HEADER_H - txt.get_height()) // 2))

            cy = self.y + PAD + HEADER_H
            for local_idx, (name, rotation, frame_type) in enumerate(items):
                global_idx = col_idx_offset + local_idx
                rect = self._rects[global_idx][0]
                bg = HOVER_BG if self._hovered == global_idx else CELL_BG
                pygame.draw.rect(surface, bg, rect)
                tex = self._texture(name, rotation, frame_type)
                if tex:
                    surface.blit(tex, (rect.x + 1, rect.y + 1))
                pygame.draw.rect(surface, BORDER, rect, 1)

            col_idx_offset += len(items)
            cx += col_w + COL_GAP
