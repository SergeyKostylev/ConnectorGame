import pygame

ITEM_WIDTH = 150
ITEM_HEIGHT = 30
BG_COLOR = (240, 240, 240)
BORDER_COLOR = (100, 100, 100)
TEXT_COLOR = (20, 20, 20)
ITEMS = ["перший", "другий"]


class ContextMenu:
    def __init__(self):
        self.visible = False
        self.x = 0
        self.y = 0
        self._font = None

    def show(self, x, y):
        self.x = x
        self.y = y
        self.visible = True

    def hide(self):
        self.visible = False

    def _get_font(self):
        if self._font is None:
            self._font = pygame.font.SysFont(None, 22)
        return self._font

    def get_item_rect(self, index):
        return pygame.Rect(self.x, self.y + index * ITEM_HEIGHT, ITEM_WIDTH, ITEM_HEIGHT)

    def handle_click(self, pos):
        """Returns index of clicked item, or None if clicked outside."""
        if not self.visible:
            return None
        for i in range(len(ITEMS)):
            if self.get_item_rect(i).collidepoint(pos):
                self.hide()
                return i
        self.hide()
        return None

    def draw(self, surface):
        if not self.visible:
            return
        font = self._get_font()
        for i, item in enumerate(ITEMS):
            rect = self.get_item_rect(i)
            pygame.draw.rect(surface, BG_COLOR, rect)
            pygame.draw.rect(surface, BORDER_COLOR, rect, 1)
            text = font.render(item, True, TEXT_COLOR)
            text_y = rect.y + (ITEM_HEIGHT - text.get_height()) // 2
            surface.blit(text, (rect.x + 8, text_y))
