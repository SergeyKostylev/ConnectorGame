import pygame

MENU_H = 30
PAD = 6
BTN_W = 60
BTN_H = 20

BG = (60, 60, 60)
BTN_BG = (80, 120, 80)
BTN_HOVER = (100, 160, 100)
BTN_BORDER = (40, 40, 40)
BTN_FG = (255, 255, 255)


class TopMenu:
    def __init__(self):
        self._font = None
        self._save_rect = pygame.Rect(PAD, (MENU_H - BTN_H) // 2, BTN_W, BTN_H)
        self._hovered = False

    def _get_font(self):
        if self._font is None:
            self._font = pygame.font.SysFont(None, 18)
        return self._font

    def handle_hover(self, pos):
        self._hovered = self._save_rect.collidepoint(pos)

    def handle_click(self, pos):
        """Returns 'save' if save button clicked, else None."""
        if self._save_rect.collidepoint(pos):
            return 'save'
        return None

    def draw(self, surface):
        pygame.draw.rect(surface, BG, (0, 0, surface.get_width(), MENU_H))
        pygame.draw.rect(surface, BTN_HOVER if self._hovered else BTN_BG, self._save_rect)
        pygame.draw.rect(surface, BTN_BORDER, self._save_rect, 1)
        font = self._get_font()
        txt = font.render('Save', True, BTN_FG)
        surface.blit(txt, (
            self._save_rect.x + (BTN_W - txt.get_width()) // 2,
            self._save_rect.y + (BTN_H - txt.get_height()) // 2,
        ))
