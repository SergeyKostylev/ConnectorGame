import sys
import json
import subprocess
import threading
import pygame
import app.config as config
from app.services.DataMapGeneratorV3 import DEFAULT_TARGETS_PCT

PREFS_FILE = ".launcher_prefs.json"

W, H      = 480, 340
LEFT_W    = 130
HEADER_H  = 50
STATUS_H  = 30
RUN_H     = 34
PAD       = 12
ROW_H     = 38
INPUT_H   = 24
LABEL_W   = 100
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


# ── action definition ─────────────────────────────────────────────────────────

class Action:
    def __init__(self, label, inputs, run_fn):
        self.label  = label
        self.inputs = inputs   # list of (label_str, widget)
        self.run_fn = run_fn


# ── launcher ──────────────────────────────────────────────────────────────────

class Launcher:
    def __init__(self):
        pygame.init()
        self.screen   = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        pygame.display.set_caption("ConnectorGame")
        self.font     = pygame.font.SysFont(None, 19)
        self.font_h   = pygame.font.SysFont(None, 24)
        self.status   = ""
        self._busy    = False
        self._sel     = 0
        self._actions = self._build_actions()
        self._load_prefs()

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
        ]
        return [
            Action("Generate v3", gen_inputs, self._do_generate),
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

    def _save_prefs(self):
        data = {}
        for action in self._actions:
            data[action.label] = {}
            for label, widget in action.inputs:
                if isinstance(widget, TextInput):
                    data[action.label][label] = widget.value
                elif isinstance(widget, Dropdown):
                    data[action.label][label] = widget.selected
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
        for action in self._actions:
            prefs = data.get(action.label, {})
            for label, widget in action.inputs:
                if label not in prefs:
                    continue
                if isinstance(widget, TextInput):
                    widget.value = prefs[label]
                elif isinstance(widget, Dropdown):
                    widget.selected = prefs[label]

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
            for j, line in enumerate(action.label.split()):
                txt = self.font.render(line, True, FG)
                self.screen.blit(txt, (PAD + 6, r.y + 10 + j * 17))

        # right panel — params
        x0    = LEFT_W + PAD
        inp_x = x0 + LABEL_W
        inp_w = sw - inp_x - PAD
        y     = HEADER_H + PAD
        for label, widget in self._actions[self._sel].inputs:
            lbl = self.font.render(label, True, FG_DIM)
            self.screen.blit(lbl, (x0, y + (INPUT_H - lbl.get_height()) // 2))
            widget.draw(self.screen, self.font, inp_x, y, inp_w)
            y += ROW_H

        # run button
        run_rect = pygame.Rect(x0, sh - STATUS_H - PAD - RUN_H, sw - x0 - PAD, RUN_H)
        if self._busy:
            run_color, run_fg = BTN_DIS, FG_DIS
        elif run_hov:
            run_color, run_fg = BTN_HOV, FG
        else:
            run_color, run_fg = BTN_BG, FG
        pygame.draw.rect(self.screen, run_color, run_rect, border_radius=6)
        run_label = self._actions[self._sel].label
        rt = self.font.render(run_label, True, run_fg)
        self.screen.blit(rt, (run_rect.centerx - rt.get_width() // 2,
                               run_rect.centery - rt.get_height() // 2))

        # status bar
        pygame.draw.rect(self.screen, HEADER, (0, sh - STATUS_H, sw, STATUS_H))
        if self.status:
            st = self.font.render(self.status, True, FG_STATUS)
            self.screen.blit(st, (PAD, sh - STATUS_H + (STATUS_H - st.get_height()) // 2))

        # dropdown overlays on top
        for _, widget in self._actions[self._sel].inputs:
            if isinstance(widget, Dropdown):
                widget.draw_overlay(self.screen, self.font)

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
                    pygame.quit()
                    sys.exit()
                if event.type == pygame.VIDEORESIZE:
                    self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
                    continue
                if event.type == pygame.MOUSEMOTION:
                    pos = event.pos
                    nav_hov = next((i for i, r in enumerate(nav_rects)
                                    if r.collidepoint(pos)), -1)
                    run_hov = run_rect.collidepoint(pos)
                    for _, w in self._actions[self._sel].inputs:
                        w.handle(event)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    pos = event.pos
                    for i, r in enumerate(nav_rects):
                        if r.collidepoint(pos):
                            self._sel = i
                            break
                    else:
                        if run_rect.collidepoint(pos):
                            self._run_selected()
                            continue
                    consumed = False
                    for _, w in self._actions[self._sel].inputs:
                        if isinstance(w, Dropdown):
                            consumed = w.handle(event) or consumed
                    if not consumed:
                        for _, w in self._actions[self._sel].inputs:
                            w.handle(event)
                    continue

                consumed = False
                for _, w in self._actions[self._sel].inputs:
                    if isinstance(w, Dropdown):
                        consumed = w.handle(event) or consumed
                if not consumed:
                    for _, w in self._actions[self._sel].inputs:
                        w.handle(event)

            nav_rects, run_rect = self._draw(nav_hov, run_hov)
            pygame.display.flip()
            clock.tick(30)


if __name__ == "__main__":
    Launcher().run()
