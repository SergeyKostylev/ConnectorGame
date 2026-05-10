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
        self._levels  = []   # list of {'name': str, 'meta': dict}
        self.selected = -1
        self._rects   = []
        self._scroll  = 0    # pixel offset
        self._list_h  = 0    # updated each draw, used in handle
        self._font_sm = None
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
            for i, r in enumerate(self._rects):
                if r.collidepoint(event.pos):
                    self.selected = i
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
            self._rects.append(r)

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


# ── launcher ──────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self):
        pygame.init()
        win_size      = self._read_window_size()
        self.screen   = pygame.display.set_mode(win_size, pygame.RESIZABLE)
        pygame.display.set_caption("ConnectorGame")
        self.font     = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 15)
        self.font_h   = pygame.font.SysFont("helveticaneue,helvetica,arial,sans", 19)
        self.status   = ""
        self._busy    = False
        self._sel     = 0
        self._actions = self._build_actions()
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

    def _do_edit_levels(self):
        self._busy = False

    def _save_prefs(self):
        data = {"window_size": list(self.screen.get_size()), "selected": self._sel}
        for action in self._actions:
            data[action.label] = {}
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
            col_w = min(right_w // 2, max(260, int(right_w * 0.30)))
            action.panel.draw(self.screen, self.font,
                              right_x, HEADER_H + PAD, col_w, content_h_inner)
            # separator
            sep_x = right_x + col_w + PAD // 2
            pygame.draw.line(self.screen, SEP,
                             (sep_x, HEADER_H + PAD),
                             (sep_x, sh - STATUS_H - PAD))
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
                if event.type == pygame.QUIT:
                    self._save_prefs()
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
                    for _, w in cur_action.inputs:
                        w.handle(event)

                if event.type == pygame.MOUSEWHEEL:
                    if cur_action.panel:
                        cur_action.panel.handle(event)

                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    for i, r in enumerate(nav_rects):
                        if r.collidepoint(pos):
                            self._sel = i
                            if self._actions[i].panel:
                                self._actions[i].panel._refresh()
                            self._save_prefs()
                            break
                    else:
                        if cur_action.panel:
                            cur_action.panel.handle(event)
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
            clock.tick(30)


if __name__ == "__main__":
    Launcher().run()
