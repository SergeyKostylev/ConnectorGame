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

W, H      = 480, 340
LEFT_W    = 195
HEADER_H  = 50
STATUS_H  = 30
RUN_H     = 34
PAD       = 12
ROW_H     = 38
INPUT_H   = 24
LABEL_W   = 110
INP_W     = 160
STEP_W    = 22

BG        = (30,  30,  30 )
HEADER    = (45,  45,  45 )
LEFT_BG   = (38,  38,  38 )
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
    ITEM_H = 76

    def __init__(self):
        self._levels      = []   # list of {'name': str, 'meta': dict}
        self.selected     = -1
        self.editing      = -1   # index of level whose edit panel is open
        self._prev_selected = -1
        self._rects       = []
        self._edit_rects  = []
        self._scroll      = 0    # pixel offset
        self._list_h      = 0
        self._font_sm     = None
        self._refresh()

    def _refresh(self):
        self.selected = -1
        self._scroll  = 0
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
            meta = {}
            try:
                with open(os.path.join(LEVELS_DIR, f)) as fp:
                    meta = json.load(fp).get('metadata', {})
            except Exception:
                pass
            levels.append({'name': name, 'meta': meta})
        self._levels = levels

    def handle(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for r, li in self._rects:
                if r.collidepoint(event.pos):
                    self._prev_selected = self.selected
                    self.selected = li
                    self.editing  = li
                    return self._levels[li]['name']
        elif event.type == pygame.MOUSEWHEEL:
            max_scroll = max(0, len(self._levels) * self.ITEM_H - self._list_h)
            self._scroll = max(0, min(max_scroll, self._scroll - event.y * 20))

    def draw(self, surf, font, x, y, w, h):
        if self._font_sm is None:
            self._font_sm = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 12)

        SB_W = 8  # scrollbar width
        list_w = w - SB_W - 2

        pygame.draw.rect(surf, INPUT_BG, (x, y, w, h), border_radius=4)
        pygame.draw.rect(surf, BOR,      (x, y, w, h), 1, border_radius=4)

        self._list_h = h - 2
        self._rects  = []
        clip = surf.get_clip()
        surf.set_clip(pygame.Rect(x + 1, y + 1, list_w, h - 2))

        mouse = pygame.mouse.get_pos()
        ih    = self.ITEM_H
        pad   = 8

        for li, entry in enumerate(self._levels):
            ry = y + 1 + li * ih - self._scroll
            if ry + ih < y + 1:
                continue
            if ry > y + h - 1:
                break
            r = pygame.Rect(x + 1, ry, list_w, ih)
            self._rects.append((r, li))

            if li == self.selected:
                bg = NAV_SEL
            elif r.collidepoint(mouse):
                bg = DROP_HOV
            else:
                bg = INPUT_BG
            pygame.draw.rect(surf, bg, r)

            # name
            ty = ry + pad
            txt = font.render(entry['name'], True, FG)
            surf.blit(txt, (r.x + pad, ty))
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

            # separator
            sep_y = ry + ih - 1
            pygame.draw.line(surf, SEP, (x + 1, sep_y), (x + list_w, sep_y))

        surf.set_clip(clip)

        # scrollbar
        total_h = len(self._levels) * ih
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

    def __init__(self, message):
        self._message = message
        self._result  = None   # None / 'save' / 'discard' / 'cancel'
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
        bx = dx + (self.W - btn_w * 3 - gap * 2) // 2
        by = dy + self.H - btn_h - 22
        for k, label, primary in [
            ('save',    'Save',    True),
            ('discard', 'Discard', False),
            ('cancel',  'Cancel',  False),
        ]:
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
        self._original_meta = self._compute_meta()
        self._ox = 0   # screen offset, updated in draw()
        self._oy = 0
        self._scale = 1.0

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

        scaled = pygame.transform.scale(self._surf, (sw, sh)) if scale < 1.0 else self._surf
        dest.blit(scaled, (bx, by))

    def draw_overlay(self, dest):
        """Draw context menu directly on dest (launcher screen) at screen coords."""
        self._context_menu.draw(dest)

    def save(self):
        if self._file_path is None:
            return
        import copy
        from generate import save_level_to, save_image
        from app.services.helper import unsort_map

        data = [
            [{'name': f.name, 'rotation': f.rotation,
              'type': 'battery' if f.is_battery() else 'target' if f.is_target() else 'pipeline'}
             for f in row]
            for row in self._matrix.frames_map
        ]
        shuffled = self._shuffled_data if self._shuffled_data else unsort_map(copy.deepcopy(data))
        save_level_to(data, shuffled, self._file_path, self._version)
        stem = os.path.splitext(os.path.basename(self._file_path))[0]
        save_image(data, stem)
        if shuffled:
            save_image(shuffled, stem + '_shuffled')
        self._saved_state = self._snapshot()


# ── shuffled window (separate process) ────────────────────────────────────────

def _shuffled_worker(shuffled_data, update_queue, response_queue, dirty, position, sys_path, prefs_file, ready=None):
    """Runs in a child process: its own pygame loop for the shuffled view."""
    import sys, json, queue as _queue, os
    for p in reversed(sys_path):
        if p not in sys.path:
            sys.path.insert(0, p)

    import pygame
    from app.models.Matrix import Matrix
    from app.services.render import MF_SIZE, Cursor, Render

    MF = MF_SIZE
    matrix = Matrix(frame_map_data=shuffled_data)
    shape  = matrix.get_shape()
    w, h   = shape[1] * MF, shape[0] * MF

    if position:
        os.environ['SDL_VIDEO_WINDOW_POS'] = f"{position[0]},{position[1]}"

    pygame.init()
    screen = pygame.display.set_mode((w, h))
    pygame.display.set_caption("Shuffled")
    cursor = Cursor((0, 0), w, h)
    render = Render(matrix, cursor, surface=screen, show_cursor=False)
    render.render()
    pygame.display.flip()
    if ready is not None:
        ready.set()
    clock  = pygame.time.Clock()

    while True:
        # apply tile changes sent from the main process
        try:
            while True:
                msg = update_queue.get_nowait()
                if msg[0] == '__get_state__':
                    state = [
                        [{'name': f.name, 'rotation': f.rotation,
                          'type': ('battery' if f.is_battery()
                                   else 'target' if f.is_target()
                                   else 'pipeline')}
                         for f in row]
                        for row in matrix.frames_map
                    ]
                    response_queue.put(state)
                else:
                    r, c, name, frame_type = msg
                    cur_rot = matrix.frames_map[r][c].rotation
                    matrix.replace_frame(r, c, name, cur_rot, frame_type)
        except _queue.Empty:
            pass

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return
            elif event.type == pygame.WINDOWMOVED:
                try:
                    try:
                        with open(prefs_file) as _f:
                            _d = json.load(_f)
                    except Exception:
                        _d = {}
                    _d.setdefault("Edit Levels", {})["shuffled_pos"] = [event.x, event.y]
                    with open(prefs_file, 'w') as _f:
                        json.dump(_d, _f, indent=2)
                except Exception:
                    pass
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                r2 = event.pos[1] // MF
                c2 = event.pos[0] // MF
                if 0 <= r2 < shape[0] and 0 <= c2 < shape[1]:
                    matrix.turn_frame(r2, c2)
                    dirty.value = True

        render.render()
        pygame.display.flip()
        clock.tick(30)


class ShuffledWindow:
    def __init__(self, shuffled_data, position=None):
        import sys, multiprocessing, threading
        self._queue          = multiprocessing.Queue()
        self._response_queue = multiprocessing.Queue()
        self._dirty          = multiprocessing.Value('b', False)
        ready = multiprocessing.Event()
        self._proc  = multiprocessing.Process(
            target=_shuffled_worker,
            args=(shuffled_data, self._queue, self._response_queue,
                  self._dirty, position, sys.path, PREFS_FILE, ready),
            daemon=True,
        )
        self._proc.start()
        self._alive = True
        # Get NSWindow pointer now (main thread, before spawning refocus thread)
        wm_info    = pygame.display.get_wm_info()
        ns_win_ptr = wm_info.get('window')
        def _refocus():
            ready.wait(timeout=5.0)
            if not ns_win_ptr:
                return
            try:
                import ctypes, ctypes.util
                objc = ctypes.CDLL(ctypes.util.find_library('objc'))
                objc.sel_registerName.restype  = ctypes.c_void_p
                objc.sel_registerName.argtypes = [ctypes.c_char_p]
                objc.objc_msgSend.restype  = ctypes.c_void_p
                objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                              ctypes.c_void_p]
                sel = objc.sel_registerName(b'makeKeyAndOrderFront:')
                objc.objc_msgSend(ctypes.c_void_p(ns_win_ptr), sel,
                                  ctypes.c_void_p(0))
            except Exception:
                pass
        threading.Thread(target=_refocus, daemon=True).start()

    def update_tile(self, r, c, name, frame_type):
        if self._alive:
            self._queue.put((r, c, name, frame_type))

    def get_state(self, timeout=1.0):
        if not self._alive:
            return None
        self._queue.put(('__get_state__',))
        try:
            return self._response_queue.get(timeout=timeout)
        except Exception:
            return None

    def has_shuffled_changes(self):
        return self._alive and bool(self._dirty.value)

    def mark_saved(self):
        self._dirty.value = False

    def handle_event(self, event):
        pass  # worker process handles its own events

    def render(self):
        pass  # worker process renders its own window

    def close(self):
        if self._alive:
            self._alive = False
            try:
                self._proc.terminate()
            except Exception:
                pass

    @property
    def alive(self):
        if self._alive and not self._proc.is_alive():
            self._alive = False
        return self._alive


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
        self._pending_action  = None
        self._pending_cancel  = None
        self._save_rect           = pygame.Rect(0, 0, 0, 0)
        self._save_hov            = False
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
        ]
        return [
            Action("Generate v3",  gen_inputs,         self._do_generate),
            Action("Edit Levels",  [],                 self._do_edit_levels,
                   panel=LevelListPanel()),
        ]

    # ── generate v3 ───────────────────────────────────────────────────────────

    def _do_generate(self):
        inputs = dict(self._actions[0].inputs)
        rows = inputs["rows"].get()
        cols = inputs["cols"].get()
        bat  = inputs["batteries %"].get()
        tgt  = inputs["targets %"].get()
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

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            out    = result.stdout + result.stderr
            saved  = next((l for l in out.splitlines() if "Saved:" in l and ".json" in l), None)
            self.status = saved.strip() if saved else (result.stderr.strip() or "Done")
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
        self._inline_editor._original_meta = self._inline_editor._compute_meta()
        cur_panel = self._actions[self._sel].panel
        if cur_panel:
            cur_panel._refresh()
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

    @staticmethod
    def _load_shuffled_pos():
        try:
            with open(PREFS_FILE) as f:
                data = json.load(f)
            pos = data.get("Edit Levels", {}).get("shuffled_pos")
            if pos:
                return (pos[0], pos[1])
        except Exception:
            pass
        return None

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
            self._shuffled_win = ShuffledWindow(shuffled_data,
                                                position=self._load_shuffled_pos())

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
            ("src/target/off_0.jpg",  "bat:",      meta['battery'],  "  "),
            ("src/battery/bat_270.jpg", "battery:", meta['target'],   "  "),
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

    # ── drawing ───────────────────────────────────────────────────────────────

    def _draw(self, nav_hov, run_hov):
        sw, sh = self.screen.get_size()
        self.screen.fill(BG)

        # header
        pygame.draw.rect(self.screen, HEADER, (0, 0, sw, HEADER_H))
        t = self.font_h.render("ConnectorGame", True, FG)
        self.screen.blit(t, (PAD, (HEADER_H - t.get_height()) // 2))

        # left nav panel
        content_h = sh - HEADER_H - STATUS_H
        pygame.draw.rect(self.screen, LEFT_BG, (0, HEADER_H, LEFT_W, content_h))
        pygame.draw.line(self.screen, SEP, (LEFT_W, HEADER_H), (LEFT_W, sh - STATUS_H))

        nav_rects = []
        for i, action in enumerate(self._actions):
            r = pygame.Rect(0, HEADER_H + i * 48, LEFT_W, 48)
            nav_rects.append(r)
            if i == self._sel:
                bg = NAV_SEL
            elif nav_hov == i:
                bg = NAV_HOV
            else:
                bg = LEFT_BG
            pygame.draw.rect(self.screen, bg, r)
            # accent bar on selected
            if i == self._sel:
                pygame.draw.rect(self.screen, BTN_BG, (0, r.y, 3, r.height))
            txt = self.font.render(action.label, True, FG)
            self.screen.blit(txt, (PAD + 6, r.centery - txt.get_height() // 2))

        action   = self._actions[self._sel]
        right_x  = LEFT_W + PAD
        right_w  = sw - LEFT_W - PAD * 2
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
            action.panel.draw(self.screen, self.font,
                              right_x, HEADER_H + PAD, col_w, content_h_inner)
            # resize handle — 10px hit area, 3px visual stripe at right edge of list column
            handle_rect = pygame.Rect(right_x + col_w - 5, HEADER_H + PAD, 10, content_h_inner)
            self._resize_handle = handle_rect
            if self._resize_hov or self._col_resizing:
                hcol = BOR_ACT
            else:
                hcol = (70, 100, 70)
            pygame.draw.rect(self.screen, hcol,
                             pygame.Rect(right_x + col_w - 1, HEADER_H + PAD, 3, content_h_inner))
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
                if has_changes:
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

                # meta comparison: before / new — to the right of Save button
                fnt = self._font_sm
                lh  = fnt.size("A")[1]
                mx  = self._save_rect.right + PAD
                by0 = self._save_rect.y + (RUN_H - lh * 2 - 2) // 2
                self._draw_meta_line(fnt, "before:", self._inline_editor._original_meta,
                                     mx, by0, FG_DIM)
                self._draw_meta_line(fnt, "new:    ", self._inline_editor._compute_meta(),
                                     mx, by0 + lh + 2, FG if has_changes else FG_DIM)
                editor_y = HEADER_H + PAD + RUN_H + PAD
                self._inline_editor.draw(
                    self.screen, detail_x, editor_y, detail_w,
                    sh - STATUS_H - editor_y - PAD
                )
        else:
            # right panel — params (fixed-width, centred horizontally)
            row_w  = LABEL_W + INP_W
            row_x  = LEFT_W + (sw - LEFT_W - row_w) // 2
            inp_x  = row_x + LABEL_W
            y      = HEADER_H + PAD
            for label, widget in action.inputs:
                lbl = self.font.render(label, True, FG_DIM)
                self.screen.blit(lbl, (row_x, y + (INPUT_H - lbl.get_height()) // 2))
                widget.draw(self.screen, self.font, inp_x, y, INP_W)
                y += ROW_H

            # run button
            run_rect = pygame.Rect(row_x, sh - STATUS_H - PAD - RUN_H, row_w, RUN_H)
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
                        if result in ('save', 'discard') and action:
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
                    self._resize_hov = self._resize_handle.collidepoint(pos)
                    if self._resize_hov or self._col_resizing:
                        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_SIZEWE)
                    else:
                        pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_ARROW)
                    if self._col_resizing:
                        sw2, _ = self.screen.get_size()
                        new_w = pos[0] - (LEFT_W + PAD)
                        self._list_col_w = max(100, min((sw2 - LEFT_W - PAD * 2) // 2, new_w))
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
                                    self._shuffled_win = ShuffledWindow(
                                        shuffled_data, position=self._load_shuffled_pos())
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
                            panel_result = cur_action.panel.handle(event)
                            if panel_result is not None:
                                level_name = panel_result
                                prev_sel   = cur_action.panel._prev_selected
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
                            elif self._inline_editor:
                                if self._save_rect.collidepoint(pos) and \
                                        self._has_unsaved_changes():
                                    self._do_save_editor()
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
                        self._inline_editor.handle(event)

                if not cur_action.panel:
                    consumed = False
                    for _, w in cur_action.inputs:
                        if isinstance(w, Dropdown):
                            consumed = w.handle(event) or consumed
                    if not consumed:
                        for _, w in cur_action.inputs:
                            w.handle(event)

            nav_rects, run_rect = self._draw(nav_hov, run_hov)
            pygame.display.flip()
            if self._shuffled_win:
                if self._shuffled_win.alive:
                    self._shuffled_win.render()
                else:
                    self._shuffled_win = None
            clock.tick(30)


if __name__ == "__main__":
    Launcher().run()
