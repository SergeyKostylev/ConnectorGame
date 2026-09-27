import sys
import os
import re
import json
import subprocess
import threading
import pygame
import app.config as config
from app.services.DataMapGeneratorV3 import DEFAULT_TARGETS_PCT

PREFS_FILE  = ".launcher_prefs.json"
LEVELS_DIR  = "levels"

W, H      = 480, 420
HEADER_H  = 50
STATUS_H  = 30
RUN_H     = 34
PAD       = 12
ROW_H     = 38
INPUT_H   = 24
LABEL_W   = 110
INP_W     = 160
STEP_W    = 22
CAPTION_H = 20   # 'shuffled' / 'solved' labels above the two maps
NAME_H    = 28   # level name above the maps
LOCK_H    = 78   # orphan check progress above the maps while the level is locked

BG        = (30,  30,  30 )
HEADER    = (45,  45,  45 )
NAV_SEL   = (55,  80,  55 )
NAV_HOV   = (48,  48,  48 )
SEP       = (55,  55,  55 )
BTN_BG    = (80,  120, 80 )
BTN_HOV   = (100, 155, 100)
BTN_DIS   = (55,  55,  55 )
INPUT_BG  = (48,  48,  48 )
INPUT_ACT = (55,  65,  78 )
BOR       = (75,  75,  75 )
BOR_ACT   = (100, 140, 180)
DROP_BG   = (52,  52,  52 )
DROP_HOV  = (70,  70,  70 )
FG        = (240, 240, 240)
FG_DIM    = (150, 150, 150)
FG_DIS    = (90,  90,  90 )
FG_STATUS = (170, 200, 170)

ORPHAN_COLORS = {
    'success':    (110, 190, 110),
    'failed':     (210, 95, 95),
    'limit achieved': (210, 170, 70),
    'not checked': (210, 170, 70),
}
# row kept in a filtered list although it no longer matches (see LevelListPanel.pinned)
STALE_ROW = (92, 78, 32)
# darker fills for the Orphan status badge in the editor
ORPHAN_BADGE_COLORS = {
    'success':    (70, 130, 70),
    'failed':     (150, 60, 60),
    'limit achieved': (150, 115, 45),
    'not checked': (150, 115, 45),
}


def orphan_status(meta):
    """orphan_check from a level's metadata; 'incomplete' is the old name
    of 'limit achieved' (a tile hit the search step limit)."""
    st = meta.get('orphan_check', 'not checked')
    return 'limit achieved' if st == 'incomplete' else st


# level list filters: key -> checkbox label
LEVEL_FILTERS = {'success': 'success', 'failed': 'failed', 'limit achieved': 'limit',
                 'unchecked': 'unchecked', 'running': 'in progress'}


# ── widgets ──────────────────────────────────────────────────────────────────

class TextInput:
    def __init__(self, placeholder="", step=1, min_val=1, max_val=None):
        self.placeholder = placeholder
        self.step    = step
        self.min_val = min_val
        self.max_val = max_val
        self.value   = ""
        self.active  = False
        self.rect    = pygame.Rect(0, 0, 0, 0)
        self._minus  = pygame.Rect(0, 0, 0, 0)
        self._plus   = pygame.Rect(0, 0, 0, 0)
        self._hov_m  = False
        self._hov_p  = False

    def get(self):
        return self.value.strip() or None

    def _current(self):
        try:
            return int(self.value) if self.value else int(self.placeholder)
        except ValueError:
            return self.min_val

    def _apply(self, val):
        val = max(self.min_val, val)
        if self.max_val is not None:
            val = min(self.max_val, val)
        self.value = str(val)

    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            self._hov_m = self._minus.collidepoint(event.pos)
            self._hov_p = self._plus.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self._minus.collidepoint(event.pos):
                self._apply(self._current() - self.step)
                self.active = False
            elif self._plus.collidepoint(event.pos):
                self._apply(self._current() + self.step)
                self.active = False
            else:
                self.active = self.rect.collidepoint(event.pos)
        elif event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.value = self.value[:-1]
            elif event.key == pygame.K_ESCAPE:
                self.active = False
            elif event.unicode.isdigit():
                new = self.value + event.unicode
                if self.max_val is None or int(new) <= self.max_val:
                    self.value = new

    def _draw_step_btn(self, surf, font, rect, label, hovered):
        color = BTN_HOV if hovered else INPUT_BG
        pygame.draw.rect(surf, color, rect, border_radius=4)
        pygame.draw.rect(surf, BOR,   rect, 1, border_radius=4)
        t = font.render(label, True, FG)
        surf.blit(t, (rect.centerx - t.get_width() // 2,
                      rect.centery - t.get_height() // 2))

    def draw(self, surf, font, x, y, w):
        self._minus = pygame.Rect(x,                   y, STEP_W, INPUT_H)
        self.rect   = pygame.Rect(x + STEP_W + 2,      y, w - STEP_W * 2 - 4, INPUT_H)
        self._plus  = pygame.Rect(x + w - STEP_W,      y, STEP_W, INPUT_H)

        self._draw_step_btn(surf, font, self._minus, "−", self._hov_m)
        self._draw_step_btn(surf, font, self._plus,  "+", self._hov_p)

        bg  = INPUT_ACT if self.active else INPUT_BG
        bor = BOR_ACT   if self.active else BOR
        pygame.draw.rect(surf, bg,  self.rect, border_radius=4)
        pygame.draw.rect(surf, bor, self.rect, 1, border_radius=4)

        text  = self.value if self.value else self.placeholder
        color = FG         if self.value else FG_DIM
        txt = font.render(text, True, color)
        surf.blit(txt, (self.rect.centerx - txt.get_width() // 2,
                        self.rect.y + (INPUT_H - txt.get_height()) // 2))


class Checkbox:
    def __init__(self, checked=False):
        self.checked = checked
        self.rect    = pygame.Rect(0, 0, 0, 0)

    def get(self):
        return self.checked

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.checked = not self.checked

    def draw(self, surf, font, x, y, w):
        size = INPUT_H
        self.rect = pygame.Rect(x, y, size, size)
        pygame.draw.rect(surf, INPUT_BG, self.rect, border_radius=4)
        pygame.draw.rect(surf, BOR,      self.rect, 1, border_radius=4)
        if self.checked:
            m = 5
            pygame.draw.line(surf, FG,
                             (self.rect.x + m, self.rect.centery),
                             (self.rect.centerx - 1, self.rect.bottom - m), 2)
            pygame.draw.line(surf, FG,
                             (self.rect.centerx - 1, self.rect.bottom - m),
                             (self.rect.right - m, self.rect.y + m), 2)


class Dropdown:
    def __init__(self, options):
        self.options  = options
        self.selected = 0
        self.open     = False
        self.rect     = pygame.Rect(0, 0, 0, 0)
        self._items   = []

    def get(self):
        return self.options[self.selected][1]

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.open = not self.open
                return True
            if self.open:
                for i, r in enumerate(self._items):
                    if r.collidepoint(event.pos):
                        self.selected = i
                        self.open = False
                        return True
                self.open = False
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.open = False
        return False

    def draw(self, surf, font, x, y, w):
        self.rect = pygame.Rect(x, y, w, INPUT_H)
        pygame.draw.rect(surf, INPUT_BG, self.rect, border_radius=4)
        pygame.draw.rect(surf, BOR,      self.rect, 1, border_radius=4)
        lbl = font.render(self.options[self.selected][0], True, FG)
        surf.blit(lbl, (x + 6, y + (INPUT_H - lbl.get_height()) // 2))
        arr = font.render("▾", True, FG_DIM)
        surf.blit(arr, (x + w - arr.get_width() - 6, y + (INPUT_H - arr.get_height()) // 2))

    def draw_overlay(self, surf, font):
        if not self.open:
            return
        self._items = []
        for i, (label, _) in enumerate(self.options):
            r = pygame.Rect(self.rect.x, self.rect.bottom + i * INPUT_H, self.rect.w, INPUT_H)
            self._items.append(r)
            pygame.draw.rect(surf, DROP_HOV if i == self.selected else DROP_BG, r)
            pygame.draw.rect(surf, BOR, r, 1)
            txt = font.render(label, True, FG)
            surf.blit(txt, (r.x + 6, r.y + (INPUT_H - txt.get_height()) // 2))


# ── level list panel ──────────────────────────────────────────────────────────

class LevelListPanel:
    ITEM_H = 94

    def __init__(self):
        self._levels      = []   # list of {'name': str, 'meta': dict}
        self.selected     = -1
        self.editing      = -1   # index of level whose edit panel is open
        self._prev_selected = -1
        self._rects       = []
        self._delete_rects = []
        self._check_rects = []
        self._checks      = {}   # level name -> LevelCheck
        # which levels the list shows, by orphan check state
        self.filters      = set(LEVEL_FILTERS)
        # rows kept on screen although they no longer match the filters
        # (their state changed while shown); cleared by refresh / filter change
        self.pinned       = set()
        self.blink_until  = {}   # name -> pygame ticks when its 3 s blink ends
        self._last_state  = {}   # name -> state seen on the previous frame
        self._last_shown  = set()
        self._scroll_to   = None   # name of a row to scroll into view on next draw
        self._edit_rects  = []
        self._scroll          = 0    # pixel offset
        self._scroll_to_bottom = True
        self._list_h          = 0
        self._font_sm     = None
        self._refresh()

    def _refresh(self):
        self.selected          = -1
        self._scroll_to_bottom = True
        try:
            files = sorted(
                f for f in os.listdir(LEVELS_DIR)
                if re.match(r'level_\d+\.json$', f)
            )
        except Exception:
            self._levels = []
            return
        levels = []
        for f in files:
            name = os.path.splitext(f)[0]
            meta  = {}
            mtime = None
            try:
                path  = os.path.join(LEVELS_DIR, f)
                mtime = os.path.getmtime(path)
                with open(path) as fp:
                    meta = json.load(fp).get('metadata', {})
            except Exception:
                pass
            levels.append({'name': name, 'meta': meta, 'mtime': mtime})
        self._levels = levels

    def reload(self):
        """Re-read levels from disk, keeping the selection and scroll position."""
        sel_name  = self.selected_name()
        edit_name = (self._levels[self.editing]['name']
                     if 0 <= self.editing < len(self._levels) else None)
        scroll = self._scroll
        self._refresh()
        self._scroll_to_bottom = False
        self._scroll = scroll
        names = [l['name'] for l in self._levels]
        self.selected = names.index(sel_name) if sel_name in names else -1
        self.editing  = names.index(edit_name) if edit_name in names else -1

    # ── unused-tile checks ───────────────────────────────────────────────────

    def toggle_check(self, name):
        """Start a check of `name`, or stop it if it is running.
        Returns True if a check was started."""
        check = self._checks.get(name)
        if check and check.running:
            check.stop()
            del self._checks[name]
            return False
        self._checks[name] = LevelCheck(os.path.join(LEVELS_DIR, f"{name}.json"))
        return True

    def needs_recheck_confirm(self, name):
        """True if starting a check of `name` would redo a stored success."""
        check = self._checks.get(name)
        if check and check.running:
            return False  # the click stops it — no need to ask
        entry = next((l for l in self._levels if l['name'] == name), None)
        return bool(entry) and entry['meta'].get('orphan_check') == 'success'

    def poll_checks(self):
        """Returns [(name, LevelCheck)] for checks that finished since last call."""
        return [(n, c) for n, c in list(self._checks.items()) if c.poll()]

    def forget_checks(self, names):
        for n in names:
            c = self._checks.pop(n, None)
            if c:
                c.stop()

    def state_of(self, entry):
        """The entry's orphan check state — a LEVEL_FILTERS key."""
        c = self._checks.get(entry['name'])
        if c and c.running:
            return 'running'
        state = orphan_status(entry['meta'])
        return state if state in LEVEL_FILTERS else 'unchecked'

    def visible(self):
        """[(index into _levels, entry)] that pass the filters, plus pinned rows."""
        return [(li, e) for li, e in enumerate(self._levels)
                if self.state_of(e) in self.filters or e['name'] in self.pinned]

    def clear_pins(self):
        """Re-apply the filters: drop rows kept only because their state changed."""
        self.pinned.clear()
        self.blink_until.clear()

    def is_blinking(self, name):
        return self.blink_until.get(name, 0) > pygame.time.get_ticks()

    def track_states(self):
        """Called every frame. A shown row whose state changed so that it no
        longer matches the filters stays on screen (pinned). A new check result
        makes it blink for 3 s; a level that became 'success' then disappears,
        any other result stays with a yellow fill until refresh."""
        now = pygame.time.get_ticks()
        for name, until in list(self.blink_until.items()):
            if until <= now:
                del self.blink_until[name]
                entry = next((e for e in self._levels if e['name'] == name), None)
                if entry and self.state_of(entry) == 'success' and 'success' not in self.filters:
                    self.pinned.discard(name)          # fixed -> leaves the list
        for e in self._levels:
            name, st = e['name'], self.state_of(e)
            prev = self._last_state.get(name)
            if prev is not None and st != prev and name in self._last_shown \
                    and st not in self.filters:
                self.pinned.add(name)
                if st in ('success', 'failed', 'limit achieved'):   # a check result
                    self.blink_until[name] = now + 3000
                    self._scroll_to = name
            self._last_state[name] = st
        self.pinned &= {e['name'] for e in self._levels}
        self._last_shown = {e['name'] for _, e in self.visible()}

    def row_is_stale(self, entry):
        """Pinned row that no longer matches the filters (yellow fill)."""
        return entry['name'] in self.pinned and self.state_of(entry) not in self.filters

    def _check_for(self, entry):
        """The check to show for a list entry; hidden once the file changed."""
        c = self._checks.get(entry['name'])
        if c and (c.running or c.mtime == entry['mtime']):
            return c
        return None

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for r, li in self._delete_rects:
                if r.collidepoint(event.pos):
                    return ('delete', self._levels[li]['name'])
            for r, li in self._check_rects:
                if r.collidepoint(event.pos):
                    return ('check', self._levels[li]['name'])
            for r, li in self._rects:
                if r.collidepoint(event.pos):
                    self._prev_selected = self.selected
                    self.selected = li
                    self.editing  = li
                    return ('open', self._levels[li]['name'])
        elif event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self.visible()) * self.ITEM_H - self._list_h)
            self._scroll = max(0, min(max_scroll, self._scroll - event.y * 20))
        return None

    def draw(self, surf, font, x, y, w, h):
        self.track_states()
        if self._font_sm is None:
            self._font_sm = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 12)

        SB_W = 8  # scrollbar width
        list_w = w - SB_W - 2

        pygame.draw.rect(surf, INPUT_BG, (x, y, w, h), border_radius=4)
        pygame.draw.rect(surf, BOR,      (x, y, w, h), 1, border_radius=4)

        self._list_h = h - 2
        if self._scroll_to_bottom:
            self._scroll = max(0, len(self.visible()) * self.ITEM_H - self._list_h)
            self._scroll_to_bottom = False
        self._rects  = []
        self._delete_rects = []
        self._check_rects  = []
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(x + 1, y + 1, list_w, h - 2))

        mouse = pygame.mouse.get_pos()
        ih    = self.ITEM_H
        pad   = 8

        shown = self.visible()
        if self._scroll_to is not None:
            vi = next((k for k, (_, e) in enumerate(shown) if e['name'] == self._scroll_to), None)
            if vi is not None:
                top, bottom = vi * ih, (vi + 1) * ih
                if top < self._scroll:
                    self._scroll = top
                elif bottom > self._scroll + self._list_h:
                    self._scroll = bottom - self._list_h
            self._scroll_to = None
        # keep the scroll valid when filters shrink the list
        self._scroll = max(0, min(self._scroll, len(shown) * ih - self._list_h))
        for vi, (li, entry) in enumerate(shown):
            ry = y + 1 + vi * ih - self._scroll
            if ry + ih < y + 1:
                continue
            if ry > y + h - 1:
                break
            r = pygame.Rect(x + 1, ry, list_w, ih)
            self._rects.append((r, li))

            if self.is_blinking(entry['name']):
                on = (pygame.time.get_ticks() // 250) % 2 == 0
                bg = ORPHAN_BADGE_COLORS.get(self.state_of(entry), BOR_ACT) if on else INPUT_BG
            elif li == self.selected:
                bg = NAV_SEL
            elif self.row_is_stale(entry):
                bg = STALE_ROW
            elif r.collidepoint(mouse):
                bg = DROP_HOV
            else:
                bg = INPUT_BG
            pygame.draw.rect(surf, bg, r)

            check   = self._check_for(entry)
            running = check is not None and check.running

            # delete button — small square, bottom-right of the row
            btn_sz = 22
            del_rect = pygame.Rect(r.right - pad - btn_sz, ry + ih - pad - btn_sz, btn_sz, btn_sz)
            self._delete_rects.append((del_rect, li))
            del_hov = del_rect.collidepoint(mouse)
            pygame.draw.rect(surf, (120, 55, 55) if del_hov else (70, 45, 45),
                             del_rect, border_radius=4)
            pygame.draw.rect(surf, BOR, del_rect, 1, border_radius=4)
            xt = font.render("x", True, FG)
            surf.blit(xt, (del_rect.centerx - xt.get_width() // 2,
                           del_rect.centery - xt.get_height() // 2))

            # "Check orphans" / "Stop" button — top-right of the row
            chk_w = max(self._font_sm.size(s)[0] for s in ("Check orphans", "Stop")) + 14
            chk_h = 20
            chk_rect = pygame.Rect(r.right - pad - chk_w, ry + pad, chk_w, chk_h)
            self._check_rects.append((chk_rect, li))
            chk_hov = chk_rect.collidepoint(mouse)
            if running:
                chk_bg = (140, 105, 50) if chk_hov else (110, 85, 40)
            else:
                chk_bg = (70, 110, 70) if chk_hov else (50, 75, 50)
            pygame.draw.rect(surf, chk_bg, chk_rect, border_radius=4)
            pygame.draw.rect(surf, BOR, chk_rect, 1, border_radius=4)
            ck = self._font_sm.render("Stop" if running else "Check orphans", True, FG)
            surf.blit(ck, (chk_rect.centerx - ck.get_width() // 2,
                           chk_rect.centery - ck.get_height() // 2))

            # texts are clipped so they never run under the buttons
            text_clip = pygame.Rect(r.x, ry, chk_rect.x - 6 - r.x, ih).clip(surf.get_clip())
            list_clip = surf.get_clip()
            surf.set_clip(text_clip)

            # name (+ check result / progress next to it)
            ty = ry + pad
            txt = font.render(entry['name'], True, FG)
            surf.blit(txt, (r.x + pad, ty))
            if check:
                ct = self._font_sm.render(check.label(), True, check.color())
                surf.blit(ct, (r.x + pad + txt.get_width() + 8,
                               ty + txt.get_height() - ct.get_height()))
            ty += txt.get_height() + 3

            # metadata lines
            m = entry['meta']
            meta_lines = [
                f"size: {m.get('size','?')}  {m.get('generator','?')}",
                f"bat: {m.get('battery','?')}  target: {m.get('target','?')}",
                f"pipeline: {m.get('pipeline','?')}  wall: {m.get('wall','?')}",
            ]
            for line in meta_lines:
                t = self._font_sm.render(line, True, FG_DIM)
                surf.blit(t, (r.x + pad, ty))
                ty += t.get_height() + 1
            # orphan check status, stored in metadata by the Check orphans button
            orphan = orphan_status(m)
            t = self._font_sm.render(f"orphans: {orphan}", True,
                                     ORPHAN_COLORS.get(orphan, FG_DIM))
            surf.blit(t, (r.x + pad, ty))
            surf.set_clip(list_clip)

            # separator
            sep_y = ry + ih - 1
            pygame.draw.line(surf, SEP, (x + 1, sep_y), (x + list_w, sep_y))

            # check progress bar — along the bottom line of the row
            if check:
                frac  = 1.0 if not check.running else (
                    check.done / check.total if check.total else 0.0)
                bar_w = int((list_w - 1) * frac)
                if bar_w > 0:
                    pygame.draw.rect(surf, check.color(), (x + 1, ry + ih - 3, bar_w, 3))

        surf.set_clip(clip)

        # scrollbar
        total_h = len(shown) * ih
        if total_h > self._list_h:
            track_x = x + list_w + 2
            track_h = h - 2
            pygame.draw.rect(surf, DROP_BG, (track_x, y + 1, SB_W - 1, track_h))
            thumb_h = max(20, track_h * self._list_h // total_h)
            max_scroll = total_h - self._list_h
            thumb_y = y + 1 + (track_h - thumb_h) * self._scroll // max_scroll
            pygame.draw.rect(surf, BOR_ACT, (track_x, thumb_y, SB_W - 1, thumb_h), border_radius=3)

    def selected_name(self):
        if 0 <= self.selected < len(self._levels):
            return self._levels[self.selected]['name']
        return None


# ── action definition ─────────────────────────────────────────────────────────

class Action:
    def __init__(self, label, inputs, run_fn, panel=None):
        self.label  = label
        self.inputs = inputs   # list of (label_str, widget)
        self.run_fn = run_fn
        self.panel  = panel


# ── confirm dialog ────────────────────────────────────────────────────────────

class ConfirmDialog:
    W, H = 380, 140

    def __init__(self, message, buttons=None):
        self._message = message
        self._buttons = buttons or [
            ('save',    'Save',    True),
            ('discard', 'Discard', False),
            ('cancel',  'Cancel',  False),
        ]
        self._result  = None   # None, or one of the button keys above
        self._rects   = {}
        self._hov     = None
        self._font    = None
        self._font_sm = None

    @property
    def answered(self):
        return self._result is not None

    def handle(self, event):
        if event.type == pygame.MOUSEMOTION:
            self._hov = next((k for k, r in self._rects.items()
                              if r.collidepoint(event.pos)), None)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for k, r in self._rects.items():
                if r.collidepoint(event.pos):
                    self._result = k
                    return
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._result = 'cancel'

    def draw(self, surf):
        if self._font is None:
            self._font    = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 15)
            self._font_sm = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 13)
        sw, sh = surf.get_size()
        dim = pygame.Surface((sw, sh), pygame.SRCALPHA)
        dim.fill((0, 0, 0, 140))
        surf.blit(dim, (0, 0))
        dx = (sw - self.W) // 2
        dy = (sh - self.H) // 2
        pygame.draw.rect(surf, HEADER, (dx, dy, self.W, self.H), border_radius=8)
        pygame.draw.rect(surf, BOR,    (dx, dy, self.W, self.H), 1, border_radius=8)
        t = self._font.render(self._message, True, FG)
        surf.blit(t, (dx + (self.W - t.get_width()) // 2, dy + 28))
        btn_w, btn_h = 100, 32
        gap = 12
        n = len(self._buttons)
        bx = dx + (self.W - btn_w * n - gap * (n - 1)) // 2
        by = dy + self.H - btn_h - 22
        for k, label, primary in self._buttons:
            r = pygame.Rect(bx, by, btn_w, btn_h)
            self._rects[k] = r
            col = BTN_HOV if self._hov == k else (BTN_BG if primary else DROP_BG)
            pygame.draw.rect(surf, col, r, border_radius=5)
            pygame.draw.rect(surf, BOR, r, 1, border_radius=5)
            lt = self._font_sm.render(label, True, FG)
            surf.blit(lt, (r.centerx - lt.get_width() // 2,
                           r.centery - lt.get_height() // 2))
            bx += btn_w + gap


# ── inline editor ─────────────────────────────────────────────────────────────

class InlineEditor:
    def __init__(self, data_map, file_path, version, shuffled_data=None, on_tile_changed=None):
        from app.models.Matrix import Matrix
        from app.services.render import Cursor, MF_SIZE
        from app.editor.render_editor import RenderEditor
        from app.editor.context_menu import ContextMenu
        from app.editor.top_menu import MENU_H

        self._MF      = MF_SIZE
        self._MENU_H  = MENU_H
        self._file_path = file_path
        self._version   = version

        matrix = Matrix(frame_map_data=data_map)
        shape  = matrix.get_shape()
        self._matrix  = matrix
        self._cursor  = Cursor((0, 0), shape[1] * MF_SIZE, shape[0] * MF_SIZE)
        self._context_menu    = ContextMenu()
        self._right_click_tile = None

        ew, eh = shape[1] * MF_SIZE, shape[0] * MF_SIZE
        self._surf   = pygame.Surface((ew, eh))
        self._render = RenderEditor(matrix, self._cursor, surface=self._surf, show_menu=False)

        self._MENU_H        = 0  # no top menu in inline mode
        self._on_tile_changed = on_tile_changed
        self._shuffled_data = [list(row) for row in shuffled_data] if shuffled_data else []
        self._saved_state   = self._snapshot()
        self._orphan_check  = self.read_orphan_check()
        self._original_meta = self._compute_meta()
        self.rect = pygame.Rect(0, 0, 0, 0)   # updated in draw()
        self._ox = 0   # screen offset, updated in draw()
        self._oy = 0
        self._scale = 1.0

    def read_orphan_check(self):
        """orphan_check stored in the level file ('not checked' if absent);
        also refreshes the stored orphan cells used for the tile marks."""
        try:
            with open(self._file_path) as f:
                meta = json.load(f).get('metadata', {})
        except Exception:
            meta = {}
        cells = lambda key: [tuple(map(int, m))
                             for m in re.findall(r'\((\d+),(\d+)\)', meta.get(key, ''))]
        self._orphan_cells = cells('orphan_cells')
        self._limit_cells  = cells('orphan_unresolved')   # tile where the step limit was hit
        return orphan_status(meta)

    def _shapes_changed(self):
        """True if some tile's shape/type differs from the saved file
        (rotation-only edits don't count — they don't affect the check)."""
        return any(a[0] != b[0] or a[2] != b[2]
                   for a, b in zip(self._snapshot(), self._saved_state))

    def shorted_batteries(self):
        """Batteries that share one connected network with another battery
        (in the solved map as currently edited)."""
        fm   = self._matrix.frames_map
        rows, cols = len(fm), len(fm[0])
        parent = list(range(rows * cols))
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        for i in range(rows):
            for j in range(cols):
                f = fm[i][j]
                if j + 1 < cols and f.has_connector('right') and fm[i][j + 1].has_connector('left'):
                    parent[find(i * cols + j)] = find(i * cols + j + 1)
                if i + 1 < rows and f.has_connector('bottom') and fm[i + 1][j].has_connector('top'):
                    parent[find(i * cols + j)] = find((i + 1) * cols + j)
        by_net = {}
        for i in range(rows):
            for j in range(cols):
                if fm[i][j].is_battery():
                    by_net.setdefault(find(i * cols + j), []).append((i, j))
        return {b for bats in by_net.values() if len(bats) > 1 for b in bats}

    def orphan_marks(self):
        """{(r, c): 'orphan' | 'limit' | 'changed'} for tiles the last check reported:
        'orphan' = can stay unpowered, 'limit' = the search hit its step limit there,
        'changed' = the tile's shape/type was edited since the check."""
        cols  = len(self._matrix.frames_map[0])
        now   = self._snapshot()
        marks = {}
        for kind, tiles in (('limit', self._limit_cells), ('orphan', self._orphan_cells)):
            for r, c in tiles:
                k = r * cols + c
                if k < len(now):
                    a, b = now[k], self._saved_state[k]
                    marks[(r, c)] = kind if (a[0], a[2]) == (b[0], b[2]) else 'changed'
        return marks

    def _compute_meta(self):
        counts = {'battery': 0, 'target': 0, 'pipeline': 0, 'wall': 0}
        total  = sum(len(row) for row in self._matrix.frames_map)
        for row in self._matrix.frames_map:
            for f in row:
                if f.name == 'w':       counts['wall']     += 1
                elif f.is_battery():    counts['battery']  += 1
                elif f.is_target():     counts['target']   += 1
                else:                   counts['pipeline'] += 1
        shape = self._matrix.get_shape()
        def fmt(k):
            c = counts[k]
            return f"{c} ({c / total * 100:.1f}%)"
        return {
            'size':     f"{shape[0]}x{shape[1]}",
            'battery':  fmt('battery'),
            'target':   fmt('target'),
            'pipeline': fmt('pipeline'),
            'wall':     fmt('wall'),
            # changed shapes/types invalidate the stored check (same rule as on save)
            'orphans':  ('not checked' if self._shapes_changed() else self._orphan_check),
        }

    def _snapshot(self):
        return tuple(
            (f.name, f.rotation,
             'battery' if f.is_battery() else 'target' if f.is_target() else 'pipeline')
            for row in self._matrix.frames_map for f in row
        )

    def update_shuffled_tile(self, r, c, name, frame_type):
        if self._shuffled_data and r < len(self._shuffled_data) and c < len(self._shuffled_data[r]):
            self._shuffled_data[r][c]['name'] = name
            self._shuffled_data[r][c]['type'] = frame_type

    def _translate(self, pos):
        return (int((pos[0] - self._ox) / self._scale),
                int((pos[1] - self._oy) / self._scale))

    def handle(self, event):
        # context menu uses screen coords; tiles use editor-local coords
        if event.type == pygame.MOUSEMOTION:
            self._context_menu.handle_hover(event.pos)   # screen coords
        elif event.type == pygame.MOUSEBUTTONDOWN:
            tp = self._translate(event.pos)
            if event.button == 1:
                if self._context_menu.visible:
                    item = self._context_menu.handle_click(event.pos)  # screen coords
                    if item is not None and self._right_click_tile is not None:
                        name, rotation, frame_type = item
                        r, c = self._right_click_tile
                        self._matrix.replace_frame(r, c, name, rotation, frame_type)
                        if self._on_tile_changed:
                            self._on_tile_changed(r, c, name, frame_type)
                else:
                    gy = tp[1] - self._MENU_H
                    if gy >= 0:
                        r, c = gy // self._MF, tp[0] // self._MF
                        if self._matrix.frame_exist(r, c):
                            self._matrix.turn_frame(r, c)
            elif event.button == 3:
                tp = self._translate(event.pos)
                gy = tp[1] - self._MENU_H
                if gy >= 0:
                    self._right_click_tile = (gy // self._MF, tp[0] // self._MF)
                    self._context_menu.show(*event.pos)  # screen coords, clamped to display

    def draw(self, dest, x, y, w, h):
        self._render.render()
        # context menu is NOT drawn here — drawn via draw_overlay() on the launcher screen

        if w <= 0 or h <= 0:
            return
        ew, eh = self._surf.get_size()
        scale  = min(w / ew, h / eh, 1.0)
        sw, sh = max(1, int(ew * scale)), max(1, int(eh * scale))
        bx = x + (w - sw) // 2
        by = y + (h - sh) // 2

        self._ox, self._oy, self._scale = bx, by, scale
        self.rect = pygame.Rect(bx, by, sw, sh)   # where the level is on screen

        scaled = pygame.transform.scale(self._surf, (sw, sh)) if scale < 1.0 else self._surf
        dest.blit(scaled, (bx, by))
        # batteries wired into the same network — translucent red fill
        tile = self._MF * scale
        for r, c in self.shorted_batteries():
            cell = pygame.Rect(self.rect.x + int(c * tile), self.rect.y + int(r * tile),
                               int(tile) + 1, int(tile) + 1)
            fill = pygame.Surface(cell.size, pygame.SRCALPHA)
            fill.fill((230, 40, 40, 110))
            dest.blit(fill, cell.topleft)
        _draw_orphan_marks(dest, self.rect, scale, self._MF, self.orphan_marks())

    def draw_overlay(self, dest):
        """Draw context menu directly on dest (launcher screen) at screen coords."""
        self._context_menu.draw(dest)

    def save(self):
        if self._file_path is None:
            return
        import copy
        from generate import save_level_to
        from app.services.helper import unsort_map

        data = [
            [{'name': f.name, 'rotation': f.rotation,
              'type': 'battery' if f.is_battery() else 'target' if f.is_target() else 'pipeline'}
             for f in row]
            for row in self._matrix.frames_map
        ]
        if self._shuffled_data:
            shuffled = self._shuffled_data
            for row, srow in zip(data, shuffled):
                for cell, scell in zip(row, srow):
                    scell['name'] = cell['name']
                    scell['type'] = cell['type']
        else:
            shuffled = unsort_map(copy.deepcopy(data))
        save_level_to(data, shuffled, self._file_path, self._version)
        self._saved_state = self._snapshot()


# ── level check (separate process) ────────────────────────────────────────────

def _check_worker(level_path, sys_path, out_queue):
    """Runs in a child process: tools/orphan_checker.py over one level,
    reporting progress per checked tile. The check stops at the first tile
    that hits the step limit (status 'limit achieved')."""
    import sys, time
    for p in reversed(sys_path):
        if p not in sys.path:
            sys.path.insert(0, p)
    t0 = time.time()
    try:
        from orphan_checker import CheckJob
        job = CheckJob(level_path)
        if job.dangling:
            out_queue.put(('error', 'meet_map has unmatched connectors'))
            return
        out_queue.put(('total', job.total, job.budget))
        last = [0.0]
        def progress(cell, steps):
            # a new tile always reports; within a tile at most ~3 times a second
            now = time.time()
            if steps == 0 or now - last[0] >= 0.3:
                last[0] = now
                out_queue.put(('tile', cell, steps))
        for cell, _shape, status in job.run(on_progress=progress):
            out_queue.put(('cell', cell, status))
        out_queue.put(('done', time.time() - t0))
    except Exception as e:
        out_queue.put(('error', str(e)))


class LevelCheck:
    """A running or finished unused-tile check of one level file."""

    def __init__(self, level_path):
        import sys, multiprocessing
        self.mtime    = os.path.getmtime(level_path)
        self.total    = 0
        self.done     = 0
        self.unused   = []   # tiles that can stay unpowered in a win state
        self.timeouts = []   # tile that hit the step limit (the check stops there)
        self.stopped_early = False   # a tile got too expensive after an orphan was found
        self.error    = None
        self.elapsed  = None
        self.running  = True
        import time as _time
        self.started    = _time.time()
        self.budget     = 0      # search steps allowed per tile
        self.tile       = None   # (row, col) being checked right now
        self.tile_steps = 0      # search steps spent on it so far
        self.tile_start = None
        tools_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools')
        self._queue = multiprocessing.Queue()
        self._proc  = multiprocessing.Process(
            target=_check_worker,
            args=(level_path, [tools_dir] + sys.path, self._queue),
            daemon=True,
        )
        self._proc.start()

    def _drain(self):
        import queue as _queue
        while True:
            try:
                msg = self._queue.get_nowait()
            except _queue.Empty:
                return
            kind = msg[0]
            if kind == 'total':
                self.total = msg[1]
                self.budget = msg[2] if len(msg) > 2 else 0
            elif kind == 'tile':
                import time as _time
                if msg[1] != self.tile:
                    self.tile, self.tile_start = msg[1], _time.time()
                self.tile_steps = msg[2]
            elif kind == 'cell':
                self.done += 1
                self.tile = None
                if msg[2] == 'unused':
                    self.unused.append(msg[1])
                elif msg[2] == 'timeout':
                    self.timeouts.append(msg[1])
                elif msg[2] == 'stopped':
                    self.stopped_early = True
            elif kind == 'done':
                self.elapsed = msg[1]
                self.running = False
            elif kind == 'error':
                self.error   = msg[1]
                self.running = False

    def poll(self):
        """Read progress. Returns True once, when the check has just finished."""
        if not self.running:
            return False
        alive = self._proc.is_alive()
        self._drain()
        if self.running and not alive:
            self._drain()
            if self.running:
                self.error   = "check process exited unexpectedly"
                self.running = False
        return not self.running

    def progress_lines(self):
        """(badge text, line above it) for the lock overlay while running."""
        import time as _time
        fmt = lambda s: f"{int(s) // 60}:{int(s) % 60:02d}"
        now   = _time.time()
        badge = (f"Orphan check running · {self.done}/{self.total} · {fmt(now - self.started)}"
                 if self.total else "Orphan check starting…")
        above = None
        if self.tile is not None:
            r, c  = self.tile
            steps = f"{self.tile_steps:,}".replace(",", " ")
            limit = f" / {self.budget:,}".replace(",", " ") if self.budget else ""
            above = f"tile ({r},{c}) · {steps}{limit} steps · {fmt(now - self.tile_start)}"
        return badge, above

    def stop(self):
        if self._proc.is_alive():
            self._proc.terminate()
        self.running = False

    def label(self):
        if self.running:
            return f"{self.done}/{self.total}" if self.total else "…"
        if self.error:
            return "error"
        if self.unused:
            return f"{len(self.unused)} unused"
        if self.timeouts:
            return "limit achieved"
        return "OK"

    def color(self):
        if self.running:
            return BOR_ACT
        if self.error or self.unused:
            return (190, 75, 75)
        if self.timeouts:
            return (200, 160, 60)
        return (90, 170, 90)


# ── shuffled view (left of the editor, in the main window) ───────────────────

def _dim_locked(surf, rect):
    """Dim a map that can't be edited (its level's orphan check is running)."""
    dim = pygame.Surface(rect.size, pygame.SRCALPHA)
    dim.fill((0, 0, 0, 120))
    surf.blit(dim, rect.topleft)


def _draw_lock_banner(surf, centerx, top, label, hint=None, above=None):
    """Lock info drawn ABOVE the maps (so no tiles are covered), in a block
    LOCK_H high starting at `top`: `above` (current tile progress), then a
    non-clickable button-like badge with `label`, then `hint`."""
    y = top
    af = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 13, bold=True)
    if above:
        at = af.render(above, True, FG)
        surf.blit(at, (centerx - at.get_width() // 2, y))
    y += af.get_height() + 4
    font = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 16, bold=True)
    t    = font.render(label, True, FG)
    btn  = pygame.Rect(0, y, t.get_width() + 32, t.get_height() + 10)
    btn.centerx = centerx
    pygame.draw.rect(surf, (60, 90, 130), btn, border_radius=8)
    pygame.draw.rect(surf, BOR_ACT, btn, 1, border_radius=8)
    surf.blit(t, (btn.centerx - t.get_width() // 2, btn.centery - t.get_height() // 2))
    if hint:
        ht = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 12).render(hint, True, FG_DIM)
        surf.blit(ht, (centerx - ht.get_width() // 2, btn.bottom + 4))


def _draw_orphan_marks(surf, rect, scale, tile_px, marks):
    """Tiles from the last check: red '!' (can stay unpowered), yellow '?'
    (shape/type edited since the check) in the tile's top-right corner, or an
    orange fill with "LIMIT" written on the tile where the step limit was hit."""
    if not marks:
        return
    size = max(10, int(tile_px * scale * 0.42))
    font = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", size, bold=True)
    tile = tile_px * scale
    lfont = pygame.font.SysFont("helveticaneue,helvetica,arial,sans",
                                max(8, int(tile * 0.26)), bold=True)
    for (r, c), kind in marks.items():
        if kind == 'limit':
            # tile where the search hit its step limit: "LIMIT" written on the tile
            cell = pygame.Rect(rect.x + int(c * tile), rect.y + int(r * tile),
                               int(tile) + 1, int(tile) + 1)
            fill = pygame.Surface(cell.size, pygame.SRCALPHA)
            fill.fill((225, 150, 30, 90))
            surf.blit(fill, cell.topleft)
            t = lfont.render("LIMIT", True, FG)
            lab = pygame.Rect(0, 0, t.get_width() + 6, t.get_height() + 2)
            lab.center = cell.center
            pygame.draw.rect(surf, (150, 90, 20), lab, border_radius=3)
            surf.blit(t, (lab.centerx - t.get_width() // 2, lab.centery - t.get_height() // 2))
            continue
        col  = (215, 60, 60) if kind == 'orphan' else (225, 180, 40)
        text = "!" if kind == 'orphan' else "?"
        tx   = rect.x + int((c + 1) * tile_px * scale)
        ty   = rect.y + int(r * tile_px * scale)
        rad  = size // 2 + 2
        cx, cy = tx - rad - 1, ty + rad + 1
        pygame.draw.circle(surf, col, (cx, cy), rad)
        pygame.draw.circle(surf, (20, 20, 20), (cx, cy), rad, 1)
        t = font.render(text, True, (20, 20, 20) if kind == 'changed' else FG)
        surf.blit(t, (cx - t.get_width() // 2, cy - t.get_height() // 2))


class ShuffledView:
    """The shuffled (unsolved) map, drawn in the main window next to the
    editor. Left click rotates a tile, like playing the level."""

    def __init__(self, shuffled_data):
        from app.models.Matrix import Matrix
        from app.services.render import MF_SIZE, Cursor, Render
        self._MF     = MF_SIZE
        self._matrix = Matrix(frame_map_data=shuffled_data)
        rows, cols   = self._matrix.get_shape()
        self._surf   = pygame.Surface((cols * MF_SIZE, rows * MF_SIZE))
        self._render = Render(self._matrix, Cursor((0, 0), cols * MF_SIZE, rows * MF_SIZE),
                              surface=self._surf, show_cursor=False)
        self._dirty  = False
        self.locked  = False     # set while the level's orphan check runs
        self.marks   = {}        # orphan tile marks, mirrored from the editor
        self.rect    = pygame.Rect(0, 0, 0, 0)   # updated in draw()
        self._scale  = 1.0

    # same interface the editor used for the old separate window
    alive = True

    def close(self):
        pass

    def update_tile(self, r, c, name, frame_type):
        """Mirror a shape/type change from the editor, keeping this tile's rotation."""
        cur_rot = self._matrix.frames_map[r][c].rotation
        self._matrix.replace_frame(r, c, name, cur_rot, frame_type)

    def get_state(self):
        return [[{'name': f.name, 'rotation': f.rotation,
                  'type': ('battery' if f.is_battery()
                           else 'target' if f.is_target() else 'pipeline')}
                 for f in row]
                for row in self._matrix.frames_map]

    def set_locked(self, locked):
        self.locked = locked

    def has_shuffled_changes(self):
        return self._dirty

    def mark_saved(self):
        self._dirty = False

    def handle(self, event):
        """Left click rotates the tile under the mouse. Returns True if handled."""
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1 \
                or not self.rect.collidepoint(event.pos) or self.locked:
            return False
        c = int((event.pos[0] - self.rect.x) / self._scale) // self._MF
        r = int((event.pos[1] - self.rect.y) / self._scale) // self._MF
        if self._matrix.frame_exist(r, c):
            self._matrix.turn_frame(r, c)
            self._dirty = True
        return True

    def draw(self, dest, x, y, w, h):
        self._render.render()
        if w <= 0 or h <= 0:
            return
        ew, eh = self._surf.get_size()
        scale  = min(w / ew, h / eh, 1.0)
        sw, sh = max(1, int(ew * scale)), max(1, int(eh * scale))
        self.rect   = pygame.Rect(x + (w - sw) // 2, y + (h - sh) // 2, sw, sh)
        self._scale = scale
        scaled = pygame.transform.scale(self._surf, (sw, sh)) if scale < 1.0 else self._surf
        dest.blit(scaled, self.rect.topleft)
        _draw_orphan_marks(dest, self.rect, scale, self._MF, self.marks)
        if self.locked:
            _dim_locked(dest, self.rect)


# ── launcher ──────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self):
        pygame.init()
        win_size      = self._read_window_size()
        self.screen   = pygame.display.set_mode(win_size, pygame.RESIZABLE)
        pygame.display.set_caption("ConnectorGame")
        self.font     = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 15)
        self.font_h   = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 19)
        self._font_sm    = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 12)
        self._meta_icons = {}
        self.status         = ""
        self._busy          = False
        self._sel           = 0
        self._inline_editor   = None
        self._shuffled_win    = None
        self._confirm_dialog  = None
        self._pending_action     = None
        self._pending_cancel     = None
        self._pending_edit_level = None
        self._pending_check_level = None
        self._batch = None   # running batch check of unchecked levels, see _pump_batch()
        cpus = os.cpu_count() or 4
        # 0 = check all unchecked levels at once
        self._parallel_input = TextInput(str(min(4, cpus)), step=1, min_val=0, max_val=cpus)
        self._batch_rect     = pygame.Rect(0, 0, 0, 0)
        self._filter_rects   = []   # [(rect, filter key)] above the level list
        self._orphan_rect    = pygame.Rect(0, 0, 0, 0)   # Orphan badge, when clickable
        self._orphan_hov     = False
        self._batch_hov      = False
        self._save_rect           = pygame.Rect(0, 0, 0, 0)
        self._save_hov            = False
        self._update_rect         = pygame.Rect(0, 0, 0, 0)
        self._update_hov          = False
        self._show_shuffled       = True
        self._show_shuffled_rect  = pygame.Rect(0, 0, 0, 0)
        self._list_col_w      = None   # None = auto
        self._col_resizing    = False
        self._resize_hov      = False
        self._resize_handle   = pygame.Rect(0, 0, 0, 0)
        self._actions       = self._build_actions()
        self._load_prefs()

    @staticmethod
    def _read_window_size():
        try:
            with open(PREFS_FILE) as f:
                data = json.load(f)
            w, h = data.get("window_size", [W, H])
            return (max(w, W), max(h, H))
        except Exception:
            return (W, H)

    # ── actions ───────────────────────────────────────────────────────────────

    def _build_actions(self):
        bat_default = str(max(1, round(
            config.GENERATE_ROWS * config.GENERATE_COLS * config.GENERATE_BATTERIES_DENSITY
        )))
        gen_inputs = [
            ("rows",        TextInput(str(config.GENERATE_ROWS),    step=1,  min_val=3)),
            ("cols",        TextInput(str(config.GENERATE_COLS),    step=1,  min_val=3)),
            ("batteries %", TextInput(bat_default,               step=1, min_val=1, max_val=99)),
            ("targets %",   TextInput(str(DEFAULT_TARGETS_PCT),  step=5, min_val=5, max_val=95)),
            ("edit",        Checkbox()),
            ("empty level", Checkbox()),
            ("check orphans", Checkbox()),
        ]
        return [
            Action("Generate v3",  gen_inputs,         self._do_generate),
            Action("Edit Levels",  [],                 self._do_edit_levels,
                   panel=LevelListPanel()),
        ]

    # ── generate v3 ───────────────────────────────────────────────────────────

    def _do_generate(self):
        inputs = dict(self._actions[0].inputs)
        rows  = inputs["rows"].get()
        cols  = inputs["cols"].get()
        bat   = inputs["batteries %"].get()
        tgt   = inputs["targets %"].get()
        edit  = inputs["edit"].get()
        empty = inputs["empty level"].get()
        check = inputs["check orphans"].get()

        try:
            if empty:
                import copy
                from generate import next_auto_name, save_level
                from app.services.helper import unsort_map
                r = int(rows) if rows else config.GENERATE_ROWS
                c = int(cols) if cols else config.GENERATE_COLS
                wall_tile    = {'name': 'w', 'rotation': 0, 'type': 'pipeline'}
                data_map     = [[dict(wall_tile) for _ in range(c)] for _ in range(r)]
                shuffled_map = unsort_map(copy.deepcopy(data_map))
                name = next_auto_name()
                path = save_level(data_map, shuffled_map, name, 3)
                self.status = f"Saved: {path}"
                saved = f"Saved: {path}"
            else:
                cmd = [sys.executable, "generate.py", "v3"]
                if rows:
                    cmd.append(rows)
                if cols:
                    if not rows:
                        cmd.append(str(config.GENERATE_ROWS))
                    cmd.append(cols)
                if bat:
                    cmd.append(f"batteries={bat}")
                if tgt:
                    cmd.append(f"targets-percent={tgt}")
                result = subprocess.run(cmd, capture_output=True, text=True)
                out    = result.stdout + result.stderr
                saved  = next((l for l in out.splitlines() if "Saved:" in l and ".json" in l), None)
                self.status = saved.strip() if saved else (result.stderr.strip() or "Done")

            if saved:
                path = saved.strip().replace("Saved:", "").strip()
                level_name = os.path.splitext(os.path.basename(path))[0]
                if edit:
                    self._pending_edit_level = level_name
                if check:
                    # started by the main loop — the panel is not thread-safe
                    self._pending_check_level = level_name
        except Exception as e:
            self.status = str(e)
        finally:
            self._busy = False

    def _do_save_editor(self):
        if self._shuffled_win and self._shuffled_win.alive:
            state = self._shuffled_win.get_state()
            if state:
                self._inline_editor._shuffled_data = state
            self._shuffled_win.mark_saved()
        self._inline_editor.save()
        self._inline_editor._orphan_check  = self._inline_editor.read_orphan_check()
        self._inline_editor._original_meta = self._inline_editor._compute_meta()
        cur_panel = self._actions[self._sel].panel
        if cur_panel:
            cur_panel.reload()   # keeps selection and scroll position
        self.status = f"Saved: {self._inline_editor._file_path}"

    def _has_unsaved_changes(self):
        if self._inline_editor is None:
            return False
        main_changed = self._inline_editor._snapshot() != self._inline_editor._saved_state
        shuffled_changed = (self._shuffled_win is not None and
                            self._shuffled_win.has_shuffled_changes())
        return main_changed or shuffled_changed

    def _do_edit_levels(self):
        self._busy = False

    # ── check orphans: batch over unchecked levels ────────────────────────────

    def _levels_panel(self):
        return next(a.panel for a in self._actions if a.panel)

    def _batch_parallel(self):
        """How many checks run at once; 0 in the field = no limit (all at once)."""
        n = self._parallel_input._current()
        return n if n > 0 else float('inf')

    def _toggle_batch_check(self):
        panel = self._levels_panel()
        if self._batch:
            done = self._batch_done()
            for name in self._batch['started']:
                c = panel._checks.get(name)
                if c and c.running:
                    c.stop()
                    del panel._checks[name]
            self._batch = None
            self.status = f"Batch check stopped ({done} checked)"
            return
        panel.reload()
        queue = [l['name'] for l in panel._levels   # sorted by level number
                 if 'orphan_check' not in l['meta']]
        if not queue:
            self.status = "All levels are already checked"
            return
        unsaved = self._unsaved_open_level(set(queue))
        if unsaved:
            self._ask_save_before_check(unsaved, self._toggle_batch_check)
            return
        self._save_prefs()
        self._batch = {'queue': queue, 'started': [], 'total': len(queue)}
        self.status = f"Checking {len(queue)} unchecked levels…"

    def _batch_running(self):
        panel = self._levels_panel()
        return [n for n in self._batch['started']
                if n in panel._checks and panel._checks[n].running]

    def _batch_done(self):
        return len(self._batch['started']) - len(self._batch_running())

    def _pump_batch(self):
        """Keep up to `parallel` checks running; called every frame."""
        if not self._batch:
            return
        panel   = self._levels_panel()
        limit   = self._batch_parallel()
        running = self._batch_running()
        while len(running) < limit and self._batch['queue']:
            name = self._batch['queue'].pop(0)
            if not os.path.exists(os.path.join(LEVELS_DIR, f"{name}.json")):
                self._batch['total'] -= 1
                continue
            if name not in panel._checks or not panel._checks[name].running:
                panel.toggle_check(name)
            self._batch['started'].append(name)
            running.append(name)
        if not running and not self._batch['queue']:
            total = self._batch['total']
            self._batch = None
            self.status = f"Batch check finished: {total} levels checked"

    def _batch_label(self, width):
        """Longest button text that fits `width`."""
        if self._batch:
            p = f"{self._batch_done()}/{self._batch['total']}"
            options = [f"Stop checking · {p}", f"Stop · {p}", "Stop"]
        else:
            n = sum('orphan_check' not in l['meta'] for l in self._levels_panel()._levels)
            options = ([f"Check unchecked ({n})", f"Check ({n})", str(n)] if n
                       else ["All levels checked", "All checked", "—"])
        return next((o for o in options if self.font.size(o)[0] <= width), options[-1])

    def _draw_level_filters(self, panel, x, y, w):
        """Checkboxes above the level list: all / checked / unchecked / in progress.
        Wraps to more rows when narrow. Returns the height used."""
        fnt, box, gap = self._font_sm, 14, 12
        items = [('all', 'all')] + list(LEVEL_FILTERS.items())
        self._filter_rects = []
        cx, cy, row_h = x, y, box + 8
        for key, label in items:
            color = {'unchecked': ORPHAN_COLORS['not checked'], 'running': BOR_ACT}.get(
                key, ORPHAN_COLORS.get(key, FG_DIM))
            t = fnt.render(label, True, color)
            iw = box + 4 + t.get_width()
            if cx > x and cx + iw > x + w:
                cx, cy = x, cy + row_h
            r = pygame.Rect(cx, cy + 2, iw, box)
            self._filter_rects.append((r, key))
            on = (panel.filters == set(LEVEL_FILTERS)) if key == 'all' else key in panel.filters
            b = pygame.Rect(cx, cy + 2, box, box)
            pygame.draw.rect(self.screen, INPUT_BG, b, border_radius=3)
            pygame.draw.rect(self.screen, BOR_ACT if on else BOR, b, 1, border_radius=3)
            if on:
                pygame.draw.line(self.screen, FG, (b.x + 3, b.centery), (b.centerx - 1, b.bottom - 4), 2)
                pygame.draw.line(self.screen, FG, (b.centerx - 1, b.bottom - 4), (b.right - 3, b.y + 3), 2)
            self.screen.blit(t, (cx + box + 4, cy + 2 + (box - t.get_height()) // 2))
            cx += iw + gap
        # refresh — re-apply the filters to rows kept after a status change
        rt = fnt.render("refresh", True, FG)
        rw = rt.get_width() + 12
        if cx > x and cx + rw > x + w:
            cx, cy = x, cy + row_h
        rb = pygame.Rect(cx, cy, rw, box + 4)
        self._filter_rects.append((rb, 'refresh'))
        stale = bool(panel.pinned)
        hov = rb.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(self.screen, (BTN_HOV if hov else BTN_BG) if stale else DROP_BG,
                         rb, border_radius=4)
        pygame.draw.rect(self.screen, BOR, rb, 1, border_radius=4)
        self.screen.blit(rt, (rb.centerx - rt.get_width() // 2, rb.centery - rt.get_height() // 2))
        return cy + row_h - y + 4

    def _toggle_level_filter(self, key):
        panel = self._levels_panel()
        panel.clear_pins()
        if key == 'refresh':
            return
        if key == 'all':
            panel.filters = set() if panel.filters == set(LEVEL_FILTERS) else set(LEVEL_FILTERS)
        else:
            panel.filters ^= {key}
        self._save_prefs()

    def _unsaved_open_level(self, names):
        """Name of the editor's level if it is in `names` and has unsaved changes."""
        if self._inline_editor is None or not self._has_unsaved_changes():
            return None
        name = os.path.splitext(os.path.basename(self._inline_editor._file_path))[0]
        return name if name in names else None

    def _ask_save_before_check(self, name, then):
        """The check reads the file: an unsaved level must be saved first."""
        self._confirm_dialog = ConfirmDialog(
            f"{name} is not saved — save it first",
            buttons=[('save', 'Save & check', True), ('cancel', 'Cancel', False)],
        )
        self._pending_action = then
        self._pending_cancel = None

    def _request_check(self, name):
        """Start (or stop) the orphan check of `name`, asking first when the
        level has unsaved edits or already passed the check."""
        panel = self._levels_panel()
        def _toggle():
            if panel.toggle_check(name):
                self.status = f"Checking {name} for unused tiles…"
            else:
                self.status = f"Check of {name} stopped"
        running = name in panel._checks and panel._checks[name].running
        if not running and self._unsaved_open_level({name}):
            self._ask_save_before_check(name, _toggle)
        elif panel.needs_recheck_confirm(name):
            self._confirm_dialog = ConfirmDialog(
                f"{name}: orphan check already passed",
                buttons=[('run', 'Run again', True), ('cancel', 'Cancel', False)],
            )
            self._pending_action = _toggle
            self._pending_cancel = None
        else:
            _toggle()

    def _editor_locked(self):
        """True while an orphan check of the level open in the editor runs."""
        if self._inline_editor is None:
            return False
        name  = os.path.splitext(os.path.basename(self._inline_editor._file_path))[0]
        check = self._levels_panel()._checks.get(name)
        return bool(check and check.running)

    def _finish_check(self, panel, name, check):
        """Store a finished check in the level's metadata; returns a status line."""
        if check.error:
            return self._check_status(name, check)
        path = os.path.join(LEVELS_DIR, f"{name}.json")
        try:
            changed = os.path.getmtime(path) != check.mtime
        except OSError:
            changed = True
        if changed:
            return f"{name}: level changed during the check — result not saved"
        from generate import write_orphan_check
        write_orphan_check(path, check.unused, check.timeouts)
        ed = self._inline_editor
        if ed is not None and os.path.abspath(ed._file_path) == os.path.abspath(path):
            ed._orphan_check  = ed.read_orphan_check()
            ed._original_meta = dict(ed._original_meta, orphans=ed._orphan_check)
        panel._checks.pop(name, None)
        panel.reload()
        return self._check_status(name, check)

    @staticmethod
    def _check_status(name, check):
        if check.error:
            return f"{name}: check failed — {check.error}"
        took = f" ({check.elapsed:.1f}s)" if check.elapsed is not None else ""
        if check.unused:
            cells = ", ".join(f"({r},{c})" for r, c in check.unused)
            early = " — stopped early, more may exist" if check.stopped_early else ""
            return f"{name}: tiles can stay unpowered in a win: {cells}{early}{took}"
        if check.timeouts:
            cells = ", ".join(f"({r},{c})" for r, c in check.timeouts)
            return f"{name}: limit achieved on tile {cells} — check stopped{took}"
        return f"{name}: success — no win leaves tiles unused{took}"

    def _request_update(self):
        """Update button: re-read levels from disk and reload the open level."""
        def _reload():
            panel = self._actions[self._sel].panel
            if panel:
                panel.reload()
            if self._inline_editor is not None:
                path = self._inline_editor._file_path
                if os.path.exists(path):
                    self._open_editor(os.path.splitext(os.path.basename(path))[0])
                else:
                    self._inline_editor = None
                    if self._shuffled_win:
                        self._shuffled_win.close()
                        self._shuffled_win = None
            self.status = "Levels reloaded from disk"

        if self._has_unsaved_changes():
            self._confirm_dialog = ConfirmDialog("Level has unsaved changes.")
            self._pending_action = _reload
            self._pending_cancel = None
        else:
            _reload()

    def _open_editor(self, level_name):
        from generate import load_level_file
        path = os.path.join(LEVELS_DIR, f"{level_name}.json")
        data_map, shuffled_data, version = load_level_file(path)

        if self._shuffled_win:
            self._shuffled_win.close()
            self._shuffled_win = None

        def _on_tile_changed(r, c, name, frame_type):
            if self._shuffled_win and self._shuffled_win.alive:
                self._shuffled_win.update_tile(r, c, name, frame_type)
            self._inline_editor.update_shuffled_tile(r, c, name, frame_type)

        self._inline_editor = InlineEditor(data_map, path, version,
                                           shuffled_data=shuffled_data,
                                           on_tile_changed=_on_tile_changed)
        if self._show_shuffled and shuffled_data:
            self._shuffled_win = ShuffledView(shuffled_data)

    def _delete_level(self, name):
        m = re.match(r'level_(\d+)$', name)
        if not m:
            return
        num = int(m.group(1))

        # levels after the deleted one get renumbered — their checks no longer apply
        for a in self._actions:
            if a.panel:
                a.panel.forget_checks(
                    [l['name'] for l in a.panel._levels
                     if (mm := re.match(r'level_(\d+)$', l['name'])) and int(mm.group(1)) >= num])

        deleted_path = os.path.join(LEVELS_DIR, f"{name}.json")
        if self._inline_editor and self._inline_editor._file_path == deleted_path:
            self._inline_editor = None
            if self._shuffled_win:
                self._shuffled_win.close()
                self._shuffled_win = None

        for suffix in ('.json', '.png', '_shuffled.png'):
            p = os.path.join(LEVELS_DIR, f"{name}{suffix}")
            if os.path.exists(p):
                os.remove(p)

        try:
            files = os.listdir(LEVELS_DIR)
        except Exception:
            files = []
        nums = sorted(
            int(re.match(r'level_(\d+)\.json$', f).group(1))
            for f in files if re.match(r'level_\d+\.json$', f)
        )
        for n in (x for x in nums if x > num):
            old_stem = f"level_{n:03d}"
            new_stem = f"level_{n - 1:03d}"
            for suffix in ('.json', '.png', '_shuffled.png'):
                old_p = os.path.join(LEVELS_DIR, f"{old_stem}{suffix}")
                new_p = os.path.join(LEVELS_DIR, f"{new_stem}{suffix}")
                if os.path.exists(old_p):
                    os.rename(old_p, new_p)
            old_json = os.path.join(LEVELS_DIR, f"{old_stem}.json")
            if self._inline_editor and self._inline_editor._file_path == old_json:
                self._inline_editor._file_path = os.path.join(LEVELS_DIR, f"{new_stem}.json")

        cur_panel = self._actions[self._sel].panel
        if cur_panel:
            cur_panel.reload()
        self.status = f"Deleted: {name}"

    def _save_prefs(self):
        try:
            with open(PREFS_FILE) as f:
                data = json.load(f)
        except Exception:
            data = {}
        data["window_size"] = list(self.screen.get_size())
        data["selected"]    = self._sel
        data.setdefault("Edit Levels", {})
        data["Edit Levels"]["list_col_w"]    = self._list_col_w
        data["Edit Levels"]["show_shuffled"] = self._show_shuffled
        data["Edit Levels"]["parallel"]      = self._parallel_input.value
        data["Edit Levels"]["filters"]       = sorted(self._levels_panel().filters)
        for action in self._actions:
            data[action.label] = data.get(action.label, {})
            for label, widget in action.inputs:
                if isinstance(widget, TextInput):
                    data[action.label][label] = widget.value
                elif isinstance(widget, Dropdown):
                    data[action.label][label] = widget.selected
                elif isinstance(widget, Checkbox):
                    data[action.label][label] = widget.checked
        try:
            with open(PREFS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _load_prefs(self):
        try:
            with open(PREFS_FILE) as f:
                data = json.load(f)
        except Exception:
            return
        edit_prefs          = data.get("Edit Levels", {})
        self._list_col_w    = edit_prefs.get("list_col_w", None)
        self._show_shuffled = edit_prefs.get("show_shuffled", True)
        self._parallel_input.value = edit_prefs.get("parallel", "")
        saved = edit_prefs.get("filters")
        if saved is not None:
            if 'checked' in saved:   # before success/failed/limit were split
                saved = list(saved) + ['success', 'failed', 'limit achieved']
            saved = ['limit achieved' if f == 'incomplete' else f for f in saved]
            self._levels_panel().filters = {f for f in saved if f in LEVEL_FILTERS}
        sel = data.get("selected", 0)
        if 0 <= sel < len(self._actions):
            self._sel = sel
            if self._actions[sel].panel:
                self._actions[sel].panel._refresh()
        for action in self._actions:
            prefs = data.get(action.label, {})
            for label, widget in action.inputs:
                if label not in prefs:
                    continue
                if isinstance(widget, TextInput):
                    widget.value = prefs[label]
                elif isinstance(widget, Dropdown):
                    widget.selected = prefs[label]
                elif isinstance(widget, Checkbox):
                    widget.checked = prefs[label]

    def _run_selected(self):
        if self._busy:
            return
        self._save_prefs()
        self._busy  = True
        self.status = "Running…"
        threading.Thread(target=self._actions[self._sel].run_fn, daemon=True).start()

    def _get_icon(self, path, size):
        key = (path, size)
        if key not in self._meta_icons:
            try:
                img = pygame.image.load(path).convert()
                self._meta_icons[key] = pygame.transform.scale(img, (size, size))
            except Exception:
                self._meta_icons[key] = None
        return self._meta_icons[key]

    def _draw_map_caption(self, text, x, y, w):
        t = self._font_sm.render(text, True, FG_DIM)
        self.screen.blit(t, (x + (w - t.get_width()) // 2, y + (CAPTION_H - t.get_height()) // 2))

    def _draw_meta_line(self, font, label, meta, x, y, color):
        icon_sz = font.size("A")[1]
        cx = x
        # label
        t = font.render(label, True, color)
        self.screen.blit(t, (cx, y)); cx += t.get_width() + 6
        # size (text only)
        t = font.render(f"size: {meta['size']}  ", True, color)
        self.screen.blit(t, (cx, y)); cx += t.get_width()
        # fields: (icon_path_or_None, fallback_text, value, gap_after)
        fields = [
            ("src/battery/bat_270.jpg", "battery:", meta['battery'],  "  "),
            ("src/target/off_0.jpg",  "target:",   meta['target'],   "  "),
            ("src/l180.jpg",          "pipeline:", meta['pipeline'], "  "),
            (None,                    "wall:",     meta['wall'],     ""),
        ]
        for icon_path, fallback, value, gap in fields:
            if icon_path:
                icon = self._get_icon(icon_path, icon_sz)
                if icon:
                    self.screen.blit(icon, (cx, y)); cx += icon_sz + 2
                else:
                    t = font.render(fallback, True, color)
                    self.screen.blit(t, (cx, y)); cx += t.get_width() + 2
            else:
                t = font.render(fallback, True, color)
                self.screen.blit(t, (cx, y)); cx += t.get_width() + 2
            t = font.render(value + gap, True, color)
            self.screen.blit(t, (cx, y)); cx += t.get_width()
        orphan = meta.get('orphans', 'not checked')
        t = font.render(f"  orphans: {orphan}", True, ORPHAN_COLORS.get(orphan, color))
        self.screen.blit(t, (cx, y))

    # ── drawing ───────────────────────────────────────────────────────────────

    def _draw(self, nav_hov, run_hov):
        sw, sh = self.screen.get_size()
        self._orphan_rect = pygame.Rect(0, 0, 0, 0)   # set again if the badge is clickable
        self.screen.fill(BG)

        # header — title + tabs
        pygame.draw.rect(self.screen, HEADER, (0, 0, sw, HEADER_H))
        t = self.font_h.render("ConnectorGame", True, FG)
        self.screen.blit(t, (PAD, (HEADER_H - t.get_height()) // 2))

        nav_rects = []
        tx = PAD + t.get_width() + PAD * 3
        for i, action in enumerate(self._actions):
            txt = self.font.render(action.label, True, FG)
            r = pygame.Rect(tx, 0, txt.get_width() + PAD * 3, HEADER_H)
            nav_rects.append(r)
            if i == self._sel:
                bg = NAV_SEL
            elif nav_hov == i:
                bg = NAV_HOV
            else:
                bg = HEADER
            pygame.draw.rect(self.screen, bg, r)
            # accent bar on selected
            if i == self._sel:
                pygame.draw.rect(self.screen, BTN_BG, (r.x, r.bottom - 3, r.width, 3))
            self.screen.blit(txt, (r.centerx - txt.get_width() // 2,
                                   r.centery - txt.get_height() // 2))
            tx = r.right

        action   = self._actions[self._sel]
        right_x  = PAD
        right_w  = sw - PAD * 2
        content_h_inner = sh - HEADER_H - STATUS_H - PAD * 2
        run_rect = pygame.Rect(0, 0, 0, 0)

        if action.panel is not None:
            # two-column panel layout
            if self._list_col_w is not None:
                col_w = max(100, min(right_w // 2, self._list_col_w))
            else:
                col_w = min(right_w // 2, max(260, int(right_w * 0.30)))
            detail_x = right_x + col_w + PAD
            detail_w = sw - detail_x - PAD
            filt_h   = self._draw_level_filters(action.panel, right_x, HEADER_H + PAD, col_w)
            list_y   = HEADER_H + PAD + filt_h
            list_h   = content_h_inner - filt_h - (RUN_H + PAD) * 2
            action.panel.draw(self.screen, self.font, right_x, list_y, col_w, list_h)
            # Update button — below the list, re-reads levels from disk
            self._update_rect = pygame.Rect(right_x, list_y + list_h + PAD, col_w, RUN_H)
            pygame.draw.rect(self.screen, BTN_HOV if self._update_hov else BTN_BG,
                             self._update_rect, border_radius=6)
            ut = self.font.render("Update", True, FG)
            self.screen.blit(ut, (self._update_rect.centerx - ut.get_width() // 2,
                                  self._update_rect.centery - ut.get_height() // 2))
            # batch orphan check of unchecked levels + how many run in parallel
            num_w = STEP_W * 2 + 36
            by    = self._update_rect.bottom + PAD
            self._batch_rect = pygame.Rect(right_x, by, col_w - num_w - PAD // 2, RUN_H)
            if self._batch:
                b_col = (140, 105, 50) if self._batch_hov else (110, 85, 40)
            else:
                b_col = BTN_HOV if self._batch_hov else BTN_BG
            pygame.draw.rect(self.screen, b_col, self._batch_rect, border_radius=6)
            bt = self.font.render(self._batch_label(self._batch_rect.width - 12), True, FG)
            clip = self.screen.get_clip()
            self.screen.set_clip(self._batch_rect.inflate(-8, 0))
            self.screen.blit(bt, (max(self._batch_rect.x + 6,
                                      self._batch_rect.centerx - bt.get_width() // 2),
                                  self._batch_rect.centery - bt.get_height() // 2))
            self.screen.set_clip(clip)
            self._parallel_input.draw(self.screen, self.font,
                                      self._batch_rect.right + PAD // 2,
                                      by + (RUN_H - INPUT_H) // 2, num_w)
            # resize handle — 10px hit area, 3px visual stripe at right edge of list column
            handle_rect = pygame.Rect(right_x + col_w - 5, HEADER_H + PAD, 10, list_h)
            self._resize_handle = handle_rect
            if self._resize_hov or self._col_resizing:
                hcol = BOR_ACT
            else:
                hcol = (70, 100, 70)
            pygame.draw.rect(self.screen, hcol,
                             pygame.Rect(right_x + col_w - 1, HEADER_H + PAD, 3, list_h))
            # separator
            sep_x = right_x + col_w + PAD // 2
            pygame.draw.line(self.screen, SEP,
                             (sep_x, HEADER_H + PAD),
                             (sep_x, sh - STATUS_H - PAD))
            # Show Shuffled checkbox — always visible when Edit Levels tab is active
            chk_sz = INPUT_H
            chk_x  = detail_x
            chk_y  = HEADER_H + PAD + (RUN_H - chk_sz) // 2
            self._show_shuffled_rect = pygame.Rect(chk_x, chk_y, chk_sz, chk_sz)
            pygame.draw.rect(self.screen, INPUT_BG, self._show_shuffled_rect, border_radius=4)
            pygame.draw.rect(self.screen, BOR,      self._show_shuffled_rect, 1, border_radius=4)
            if self._show_shuffled:
                m = 5; r = self._show_shuffled_rect
                pygame.draw.line(self.screen, FG,
                                 (r.x + m, r.centery), (r.centerx - 1, r.bottom - m), 2)
                pygame.draw.line(self.screen, FG,
                                 (r.centerx - 1, r.bottom - m), (r.right - m, r.y + m), 2)
            chk_lbl = self.font.render("Show Shuffled", True, FG_DIM)
            self.screen.blit(chk_lbl, (chk_x + chk_sz + 6,
                                       chk_y + (chk_sz - chk_lbl.get_height()) // 2))
            save_x = chk_x + chk_sz + 6 + chk_lbl.get_width() + PAD

            # right detail column — save button + inline editor
            if self._inline_editor is not None:
                has_changes = self._has_unsaved_changes()
                if has_changes and not self._editor_locked():
                    save_col = BTN_HOV if self._save_hov else BTN_BG
                    save_fg  = FG
                else:
                    save_col = BTN_DIS
                    save_fg  = FG_DIS
                self._save_rect = pygame.Rect(save_x, HEADER_H + PAD, 70, RUN_H)
                pygame.draw.rect(self.screen, save_col, self._save_rect, border_radius=6)
                st = self.font.render("Save", True, save_fg)
                self.screen.blit(st, (self._save_rect.centerx - st.get_width() // 2,
                                      self._save_rect.centery - st.get_height() // 2))

                new_meta = self._inline_editor._compute_meta()

                # orphan status badge, coloured by the current status; clickable
                # (start / stop the check) unless the level already passed
                orphan = new_meta['orphans']
                level_name = os.path.splitext(os.path.basename(self._inline_editor._file_path))[0]
                locked = self._editor_locked()
                ob_col = (60, 90, 130) if locked else ORPHAN_BADGE_COLORS.get(orphan, BTN_DIS)
                ob_fg  = FG
                if locked:
                    ob_label = "Checking…"
                elif has_changes and orphan != 'success':
                    ob_label = "Save & Orphan"   # saves, then checks — the check reads the file
                else:
                    ob_label = "Orphan"
                ot = self.font.render(ob_label, True, ob_fg)
                ob_rect = pygame.Rect(self._save_rect.right + PAD, HEADER_H + PAD,
                                      max(96, ot.get_width() + 24), RUN_H)
                # clickable (start / stop the check) unless the level already passed
                self._orphan_rect = ob_rect if (locked or orphan != 'success') else pygame.Rect(0, 0, 0, 0)
                if self._orphan_hov and self._orphan_rect.collidepoint(pygame.mouse.get_pos()):
                    ob_col = tuple(min(255, v + 30) for v in ob_col)
                pygame.draw.rect(self.screen, ob_col, ob_rect, border_radius=6)
                if self._orphan_rect.width:
                    pygame.draw.rect(self.screen, FG_DIM, ob_rect, 1, border_radius=6)
                self.screen.blit(ot, (ob_rect.centerx - ot.get_width() // 2,
                                      ob_rect.centery - ot.get_height() // 2))

                # meta comparison: before / new — to the right of the badge
                fnt = self._font_sm
                lh  = fnt.size("A")[1]
                mx  = ob_rect.right + PAD
                by0 = self._save_rect.y + (RUN_H - lh * 2 - 2) // 2
                self._draw_meta_line(fnt, "before:", self._inline_editor._original_meta,
                                     mx, by0, FG_DIM)
                self._draw_meta_line(fnt, "new:    ", new_meta,
                                     mx, by0 + lh + 2, FG if has_changes else FG_DIM)
                editor_y = HEADER_H + PAD + RUN_H + PAD + NAME_H
                if locked:
                    editor_y += LOCK_H   # room for the lock info above the maps
                editor_h = sh - STATUS_H - editor_y - PAD
                ed_x, ed_w = detail_x, detail_w
                if self._shuffled_win:
                    # shuffled on the left, solved (editable) on the right
                    half = (detail_w - PAD) // 2
                    self._shuffled_win.marks = self._inline_editor.orphan_marks()
                    self._shuffled_win.draw(self.screen, detail_x, editor_y + CAPTION_H,
                                            half, editor_h - CAPTION_H)
                    sr = self._shuffled_win.rect
                    self._draw_map_caption("shuffled", sr.x, sr.y - CAPTION_H, sr.width)
                    ed_x, ed_w = detail_x + half + PAD, detail_w - half - PAD
                    editor_y += CAPTION_H
                    editor_h -= CAPTION_H
                self._inline_editor.draw(self.screen, ed_x, editor_y, ed_w, editor_h)
                maps = [self._inline_editor.rect]
                if self._shuffled_win:
                    er = self._inline_editor.rect
                    self._draw_map_caption("solved", er.x, er.y - CAPTION_H, er.width)
                    maps.append(self._shuffled_win.rect)
                # level name — centred above the maps (and their captions);
                # while locked, the check progress sits between the name and the maps
                top  = min(r.y for r in maps) - (CAPTION_H if self._shuffled_win else 0)
                left = min(r.x for r in maps); right = max(r.right for r in maps)
                if locked:
                    top -= LOCK_H
                    _dim_locked(self.screen, self._inline_editor.rect)
                    check = self._levels_panel()._checks.get(level_name)
                    badge, above = check.progress_lines()
                    _draw_lock_banner(self.screen, (left + right) // 2, top, badge,
                                      "editing is locked — press Stop in the list to edit now",
                                      above)
                nt = self.font_h.render(level_name, True, FG)
                self.screen.blit(nt, ((left + right - nt.get_width()) // 2,
                                      top - NAME_H + (NAME_H - nt.get_height()) // 2))
        else:
            self._update_rect = pygame.Rect(0, 0, 0, 0)
            # right panel — params (fixed-width, centred horizontally)
            row_w  = LABEL_W + INP_W
            row_x  = (sw - row_w) // 2
            inp_x  = row_x + LABEL_W
            y      = HEADER_H + PAD
            for label, widget in action.inputs:
                lbl = self.font.render(label, True, FG_DIM)
                self.screen.blit(lbl, (row_x, y + (INPUT_H - lbl.get_height()) // 2))
                widget.draw(self.screen, self.font, inp_x, y, INP_W)
                y += ROW_H

            # run button — bottom of the window, but never over the last input row
            run_y    = max(sh - STATUS_H - PAD - RUN_H, y + PAD)
            run_rect = pygame.Rect(row_x, run_y, row_w, RUN_H)
            if self._busy:
                run_color, run_fg = BTN_DIS, FG_DIS
            elif run_hov:
                run_color, run_fg = BTN_HOV, FG
            else:
                run_color, run_fg = BTN_BG, FG
            pygame.draw.rect(self.screen, run_color, run_rect, border_radius=6)
            rt = self.font.render(action.label, True, run_fg)
            self.screen.blit(rt, (run_rect.centerx - rt.get_width() // 2,
                                   run_rect.centery - rt.get_height() // 2))

            # dropdown overlays on top
            for _, widget in action.inputs:
                if isinstance(widget, Dropdown):
                    widget.draw_overlay(self.screen, self.font)

        # status bar
        pygame.draw.rect(self.screen, HEADER, (0, sh - STATUS_H, sw, STATUS_H))
        if self.status:
            st = self.font.render(self.status, True, FG_STATUS)
            self.screen.blit(st, (PAD, sh - STATUS_H + (STATUS_H - st.get_height()) // 2))

        # inline editor context menu — drawn on top of everything
        if self._inline_editor and action.panel:
            self._inline_editor.draw_overlay(self.screen)

        # confirm dialog — drawn last, blocks everything below
        if self._confirm_dialog:
            self._confirm_dialog.draw(self.screen)

        return nav_rects, run_rect

    # ── loop ─────────────────────────────────────────────────────────────────

    def run(self):
        clock     = pygame.time.Clock()
        nav_rects = []
        run_rect  = pygame.Rect(0, 0, 0, 0)
        nav_hov   = -1
        run_hov   = False

        while True:
            for event in pygame.event.get():
                # ── confirm dialog captures all input while visible ────────────
                if self._confirm_dialog:
                    if event.type == pygame.QUIT:
                        self._save_prefs()
                        if self._shuffled_win:
                            self._shuffled_win.close()
                        pygame.quit()
                        sys.exit()
                    self._confirm_dialog.handle(event)
                    if self._confirm_dialog.answered:
                        result  = self._confirm_dialog._result
                        action  = self._pending_action
                        cancel  = self._pending_cancel
                        self._confirm_dialog = None
                        self._pending_action  = None
                        self._pending_cancel  = None
                        if result == 'save' and self._inline_editor:
                            self._do_save_editor()
                        if result in ('save', 'discard', 'delete', 'run') and action:
                            action()
                        elif result == 'cancel' and cancel:
                            cancel()
                    continue

                if event.type == pygame.QUIT:
                    if self._has_unsaved_changes():
                        def _quit():
                            self._save_prefs()
                            if self._shuffled_win:
                                self._shuffled_win.close()
                            pygame.quit()
                            sys.exit()
                        self._confirm_dialog = ConfirmDialog("Level has unsaved changes.")
                        self._pending_action = _quit
                        self._pending_cancel = None
                        continue
                    self._save_prefs()
                    if self._shuffled_win:
                        self._shuffled_win.close()
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                    self._save_prefs()
                    continue
                cur_action = self._actions[self._sel]

                if event.type == pygame.MOUSEMOTION:
                    pos = event.pos
                    nav_hov = next((i for i, r in enumerate(nav_rects)
                                    if r.collidepoint(pos)), -1)
                    run_hov = run_rect.collidepoint(pos)
                    self._save_hov  = self._save_rect.collidepoint(pos)
                    self._update_hov = self._update_rect.collidepoint(pos)
                    self._batch_hov  = self._batch_rect.collidepoint(pos)
                    self._orphan_hov = self._orphan_rect.collidepoint(pos)
                    if cur_action.panel:
                        self._parallel_input.handle(event)
                    self._resize_hov = self._resize_handle.collidepoint(pos)
                    if self._resize_hov or self._col_resizing:
                        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_SIZEWE)
                    else:
                        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                    if self._col_resizing:
                        sw2, _ = self.screen.get_size()
                        new_w = pos[0] - PAD
                        self._list_col_w = max(100, min((sw2 - PAD * 2) // 2, new_w))
                    for _, w in cur_action.inputs:
                        w.handle(event)
                    if self._inline_editor and cur_action.panel:
                        self._inline_editor.handle(event)

                if event.type == pygame.MOUSEWHEEL:
                    if cur_action.panel:
                        cur_action.panel.handle(event)

                if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    if self._col_resizing:
                        self._col_resizing = False
                        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                        self._save_prefs()

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    if self._resize_handle.collidepoint(pos):
                        self._col_resizing = True
                        continue
                    if self._show_shuffled_rect.collidepoint(pos):
                        self._show_shuffled = not self._show_shuffled
                        self._save_prefs()
                        if not self._show_shuffled and self._shuffled_win:
                            self._shuffled_win.close()
                            self._shuffled_win = None
                        elif self._show_shuffled and self._inline_editor \
                                and self._shuffled_win is None:
                            # re-open shuffled window for current level
                            cur_panel = self._actions[self._sel].panel
                            name = cur_panel.selected_name() if cur_panel else None
                            if name:
                                from generate import load_level_file
                                _, shuffled_data, _ = load_level_file(
                                    os.path.join(LEVELS_DIR, f"{name}.json"))
                                if shuffled_data:
                                    self._shuffled_win = ShuffledView(shuffled_data)
                        continue
                    for i, r in enumerate(nav_rects):
                        if r.collidepoint(pos):
                            def _do_nav(idx=i):
                                self._sel = idx
                                self._inline_editor = None
                                if self._shuffled_win:
                                    self._shuffled_win.close()
                                    self._shuffled_win = None
                                if self._actions[idx].panel:
                                    self._actions[idx].panel._refresh()
                                self._save_prefs()
                            if self._has_unsaved_changes():
                                self._confirm_dialog = ConfirmDialog("Level has unsaved changes.")
                                self._pending_action = _do_nav
                                self._pending_cancel = None
                            else:
                                _do_nav()
                            break
                    else:
                        if cur_action.panel:
                            self._parallel_input.handle(event)   # focus / − / +
                            if self._parallel_input.rect.collidepoint(pos) or \
                                    self._parallel_input._minus.collidepoint(pos) or \
                                    self._parallel_input._plus.collidepoint(pos):
                                continue
                        if cur_action.panel and self._update_rect.collidepoint(pos):
                            self._request_update()
                            continue
                        if cur_action.panel and self._inline_editor and \
                                self._orphan_rect.collidepoint(pos):
                            name = os.path.splitext(os.path.basename(self._inline_editor._file_path))[0]
                            if not self._editor_locked() and self._has_unsaved_changes():
                                # "Save & Orphan": save and check right away, no dialog
                                self._do_save_editor()
                                if self._levels_panel().toggle_check(name):
                                    self.status = f"Saved and checking {name} for unused tiles…"
                            else:
                                self._request_check(name)
                            continue
                        if cur_action.panel and self._batch_rect.collidepoint(pos):
                            self._toggle_batch_check()
                            continue
                        if cur_action.panel:
                            hit = next((k for r, k in self._filter_rects if r.collidepoint(pos)), None)
                            if hit:
                                self._toggle_level_filter(hit)
                                continue
                        if cur_action.panel:
                            panel_result = cur_action.panel.handle(event)
                            if panel_result is not None:
                                kind, level_name = panel_result
                                if kind == 'open':
                                    prev_sel = cur_action.panel._prev_selected
                                    def _open(name=level_name):
                                        self._open_editor(name)
                                    if self._has_unsaved_changes():
                                        panel_ref = cur_action.panel
                                        self._confirm_dialog = ConfirmDialog("Level has unsaved changes.")
                                        self._pending_action = _open
                                        self._pending_cancel = (
                                            lambda ps=prev_sel, p=panel_ref: setattr(p, 'selected', ps)
                                        )
                                    else:
                                        _open()
                                elif kind == 'check':
                                    self._request_check(level_name)
                                elif kind == 'delete':
                                    def _do_delete(name=level_name):
                                        self._delete_level(name)
                                    self._confirm_dialog = ConfirmDialog(
                                        f"Delete {level_name}?",
                                        buttons=[('delete', 'Delete', True),
                                                 ('cancel', 'Cancel', False)],
                                    )
                                    self._pending_action = _do_delete
                                    self._pending_cancel = None
                            elif self._inline_editor:
                                # an open context menu belongs to the editor, even over the shuffled map
                                on_shuffled = (self._shuffled_win is not None and
                                               self._shuffled_win.rect.collidepoint(pos) and
                                               not self._inline_editor._context_menu.visible)
                                if self._editor_locked():
                                    if self._save_rect.collidepoint(pos) or on_shuffled or \
                                            self._inline_editor.rect.collidepoint(pos):
                                        self.status = "Can't edit: orphan check of this level is running — press Stop in the list to edit"
                                elif self._save_rect.collidepoint(pos) and \
                                        self._has_unsaved_changes():
                                    self._do_save_editor()
                                elif on_shuffled:
                                    self._shuffled_win.handle(event)
                                else:
                                    self._inline_editor.handle(event)
                        elif run_rect.collidepoint(pos):
                            self._run_selected()
                            continue
                        else:
                            consumed = False
                            for _, w in cur_action.inputs:
                                if isinstance(w, Dropdown):
                                    consumed = w.handle(event) or consumed
                            if not consumed:
                                for _, w in cur_action.inputs:
                                    w.handle(event)
                    continue

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                    if self._inline_editor and cur_action.panel:
                        if self._editor_locked():
                            self.status = "Can't edit: orphan check of this level is running — press Stop in the list to edit"
                        else:
                            self._inline_editor.handle(event)

                if cur_action.panel and event.type == pygame.KEYDOWN:
                    self._parallel_input.handle(event)

                if not cur_action.panel:
                    consumed = False
                    for _, w in cur_action.inputs:
                        if isinstance(w, Dropdown):
                            consumed = w.handle(event) or consumed
                    if not consumed:
                        for _, w in cur_action.inputs:
                            w.handle(event)

            if self._pending_edit_level and not self._busy:
                level_name = self._pending_edit_level
                self._pending_edit_level = None
                self._sel = 1  # Edit Levels tab
                panel = self._actions[1].panel
                panel._refresh()
                names = [l['name'] for l in panel._levels]
                if level_name in names:
                    panel.selected = names.index(level_name)
                self._open_editor(level_name)

            if self._pending_check_level and not self._busy:
                level_name = self._pending_check_level
                self._pending_check_level = None
                panel = self._actions[1].panel
                panel.reload()
                if level_name not in panel._checks and panel.toggle_check(level_name):
                    self.status = f"Checking {level_name} for unused tiles…"

            self._pump_batch()
            locked = self._editor_locked()
            if locked and self._inline_editor._context_menu.visible:
                self._inline_editor._context_menu.hide()
            if self._shuffled_win and self._shuffled_win.alive:
                self._shuffled_win.set_locked(locked)
            for a in self._actions:
                if a.panel:
                    for name, check in a.panel.poll_checks():
                        self.status = self._finish_check(a.panel, name, check)

            nav_rects, run_rect = self._draw(nav_hov, run_hov)
            pygame.display.flip()
            clock.tick(30)


if __name__ == "__main__":
    Launcher().run()
