#!/usr/bin/env python3
"""
Black Box - a deduction game for pyglet (2.x).

Hidden spheres sit on a grid. Fire shots from the border squares and work out
where the spheres are from where the shots come out.

Ray rules
  * Head-on hit on a sphere ............ shot comes back to where it started (H)
  * Passing next to a sphere ........... shot turns 90 degrees, away from it
  * Sphere beside the entry row/column . shot is reflected straight back (R)
  * Two spheres pinching the shot ...... shot reverses

Controls
  Click a border square ... fire a shot from there
  Hover a border square ... preview the path that shot would take, treating your
                            markers as the spheres (works on fired squares too)
  Left click a cell ....... place / remove a sphere marker (your guess); the "Tokens left"
                            tray above the board shows the markers you still have to place
  Right click a cell ...... add / remove a highlight (a visual note only), even when
                            the cell was highlighted as part of a row or column
  Right click a border square ... highlight / un-highlight its whole row or column
  Enter or DONE button .... submit guess (needs exactly as many markers as spheres)
  N or NEW GAME button .... new game
  R or REVEAL button ...... give up and reveal the spheres
  Size dropdown ........... grid size, 5 to 25 (the grid is always square)
                            (the arrow keys also change it)
  Spheres dropdown ........ number of hidden spheres, 2 to 10   (+ / - also change it)
  Sound button or M ....... switch all sound on or off
  Reset Best button ....... clear the best time shown for this size / number of spheres
                            (click twice within 3 seconds to confirm)
  (changing the size or the number of spheres starts a new game)

Lower times are better. A wrong submission adds a 30 second penalty.

Best times and settings (window size, grid size, spheres, sound on/off) are saved in
~/.config/blackbox and restored the next time the game starts. Works on Linux and Windows
(on Windows "~" is your user folder, e.g. C:\\Users\\you).

Pictures and sounds are loaded from a "resources" folder next to this script (or
in the current directory). Anything that is missing is skipped: the game falls
back to simple drawn shapes and silence.

Usage: python blackbox.py [spheres] [size]      (optional; overrides the saved values)
"""
import json
import os
import random
import sys
import time

import pyglet
from pyglet import shapes, sprite
from pyglet.window import key, mouse

W, H = 760, 880             # default window size (the window is resizable)
MIN_W, MIN_H = 720, 620     # smallest allowed window
BASE_CELL = 52              # reference cell size that effects are scaled from
MAX_CELL = 90               # largest cell size in pixels
BOARD_BOTTOM = 70           # space reserved below the board (messages, help)
HEADER_H = 208              # space reserved above the board (title, timer, settings, token tray)
TOKEN_SIZE, TOKEN_STEP = 30, 36   # token tray: picture size and spacing
MIN_SIZE, MAX_SIZE = 5, 25  # allowed grid size (rows = columns)
MIN_SPHERES, MAX_SPHERES = 2, 10
DD_TITLE_W, DD_BOX_W, DD_ROW_H = 64, 74, 24   # dropdown title width, box width, list row height
SOUND_W = 110               # width of the sound toggle button
RESET_W = 120               # width of the Reset Best button
RESET_CONFIRM_SECS = 3.0    # how long the Reset Best button waits for a confirming click
SETTINGS_GAP = 36           # gap between items in the settings bar
PENALTY = 30.0              # seconds added per wrong submission
ANIM_IN, ANIM_HIDE, ANIM_OUT = 0.28, 0.40, 0.28   # shot animation phases (seconds)
ANIM_TOTAL = ANIM_IN + ANIM_HIDE + ANIM_OUT
EFFECT_TIME = 0.4           # length of the pop effect when a result lands
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "blackbox")
SCORE_FILE = os.path.join(CONFIG_DIR, "scores.json")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")
LEGACY_SCORE_FILE = os.path.join(os.path.expanduser("~"), ".blackbox_scores.json")
DEFAULT_SETTINGS = {"width": W, "height": H, "size": 10, "spheres": 5, "sound": True}
DD_VALUES = {"size": list(range(MIN_SIZE, MAX_SIZE + 1)),
             "n": list(range(MIN_SPHERES, MAX_SPHERES + 1))}

DIRS = ("up", "down", "left", "right")
IMAGE_NAMES = (["yellow_sphere", "red_sphere", "green_sphere", "blue_sphere"]
               + [f"direct_column_{d}" for d in DIRS] + [f"return_{d}" for d in DIRS])
# sound -> text its file name contains (so e.g. both "highlight.mp3" and "highligh.mp3" work)
SOUND_KEYS = {"place": "place", "remove": "remove", "highlight": "highligh", "shot": "shot",
              "start": "start", "win": "win", "wrong": "wrong"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
SOUND_EXTS = (".mp3", ".wav", ".ogg", ".flac")

PAIR_COLORS = [
    (110, 200, 255), (130, 230, 130), (255, 160, 90), (200, 140, 255),
    (255, 130, 170), (90, 220, 200), (240, 230, 110), (170, 190, 255),
    (255, 190, 140), (150, 255, 180), (220, 170, 220), (180, 220, 90),
]


def fmt_time(t):
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_json(path, data):
    """Write atomically (temp file, then rename) so a crash can't leave a half-written file."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def load_scores():
    scores = read_json(SCORE_FILE)
    migrated = False
    if scores is None:                         # first run of this version: pick up old scores
        scores = read_json(LEGACY_SCORE_FILE) or {}
        migrated = bool(scores)
    # older versions stored 10x10 scores under just the sphere count
    for k in [k for k in scores if k.isdigit()]:
        scores.setdefault(f"10x10x{k}", scores[k])
        del scores[k]
        migrated = True
    if migrated:
        write_json(SCORE_FILE, scores)
    return scores


def save_scores(scores):
    write_json(SCORE_FILE, scores)


def load_settings():
    data = read_json(SETTINGS_FILE) or {}
    out = dict(DEFAULT_SETTINGS)
    for name, lo, hi in (("width", MIN_W, 20000), ("height", MIN_H, 20000),
                         ("size", MIN_SIZE, MAX_SIZE), ("spheres", MIN_SPHERES, MAX_SPHERES)):
        v = data.get(name)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[name] = clamp(int(v), lo, hi)
    if isinstance(data.get("sound"), bool):
        out["sound"] = data["sound"]
    return out


class BlackBox(pyglet.window.Window):
    def __init__(self, nspheres=5, size=10, settings=None):
        settings = settings or dict(DEFAULT_SETTINGS)
        width, height = settings.get("width", W), settings.get("height", H)
        try:                                   # don't open bigger than the screen
            scr = pyglet.display.get_display().get_default_screen()
            width, height = min(width, scr.width), min(height, scr.height - 60)
        except Exception:
            pass
        super().__init__(max(MIN_W, width), max(MIN_H, height), "Black Box", resizable=True)
        self.set_minimum_size(MIN_W, MIN_H)
        self.g_bg = pyglet.graphics.Group(order=0)
        self.g_hl = pyglet.graphics.Group(order=1)      # cell highlights
        self.g_path = pyglet.graphics.Group(order=2)    # hover path preview
        self.g_mid = pyglet.graphics.Group(order=3)
        self.g_fg = pyglet.graphics.Group(order=4)
        self.g_text = pyglet.graphics.Group(order=5)
        self.g_pop = pyglet.graphics.Group(order=6)       # dropdown list background
        self.g_pop_item = pyglet.graphics.Group(order=7)  # dropdown row highlights
        self.g_pop_text = pyglet.graphics.Group(order=8)  # dropdown row text

        self.scores = load_scores()
        self.sound_on = settings.get("sound", True)
        self.open_dd = None        # key of the dropdown whose list is open
        self.dd_scroll = 0         # first visible row of that list
        self.players = []          # sound players kept alive while they play
        self.start_player = None
        self.load_assets()

        def label(size, y, color=(230, 230, 240, 255), bold=False):
            return pyglet.text.Label(
                "", x=W // 2, y=y, anchor_x="center", anchor_y="center",
                font_size=size, weight="bold" if bold else "normal", color=color)

        self.title_label = label(26, H - 30, bold=True)
        self.title_label.text = "BLACK BOX"
        self.timer_label = label(30, H - 75, (255, 220, 120, 255), True)
        self.info_label = label(13, H - 110, (170, 185, 210, 255))
        self.msg_label = label(14, 52, (255, 255, 255, 255))
        self.help_label = label(10, 30, (130, 145, 170, 255))
        self.help_label.text = ("Border: click = fire, right click = highlight row/column, "
                                "hover = preview   |   Cell: left = marker, right = highlight")
        self.help2_label = label(10, 14, (130, 145, 170, 255))
        self.help2_label.text = ("Enter/DONE = submit   N/NEW GAME = restart   R/REVEAL = give up   M = sound   |   "
                                 "Arrows = size   +/- = spheres")

        pyglet.clock.schedule_interval(self.tick, 0.1)
        pyglet.clock.schedule_interval(self.update, 1 / 60)
        self.new_game(nspheres, size)
        self.ready = True

    # ------------------------------------------------------------------ setup
    # ---------------------------------------------------------------- assets
    def load_assets(self):
        here = os.path.dirname(os.path.abspath(__file__))
        self.res_dir = next((d for d in (os.path.join(here, "resources"),
                                         os.path.join(os.getcwd(), "resources"))
                             if os.path.isdir(d)), None)
        self.img, self.sounds = {}, {}
        if not self.res_dir:
            print("Black Box: no 'resources' folder found - using drawn shapes and no sound.")
            return

        # index the folder by lower-case file name without extension
        imgs, snds = {}, {}
        for f in sorted(os.listdir(self.res_dir)):
            stem, ext = os.path.splitext(f)
            path = os.path.join(self.res_dir, f)
            if ext.lower() in IMAGE_EXTS:
                imgs[stem.lower()] = path
            elif ext.lower() in SOUND_EXTS:
                snds[stem.lower()] = path

        missing = []
        for name in IMAGE_NAMES:
            path = self.match_image(imgs, name)
            if not path:
                missing.append(name)
                continue
            try:
                self.img[name] = pyglet.image.load(path).get_texture()
            except Exception as e:
                print(f"Black Box: could not load {os.path.basename(path)} ({e})")
        if missing:
            print("Black Box: no picture found for: " + ", ".join(missing)
                  + f" (looked in {self.res_dir}; found: {', '.join(sorted(imgs)) or 'nothing'})")

        warned = False
        for name, needle in SOUND_KEYS.items():
            path = snds.get(needle) or next((p for st, p in snds.items() if needle in st), None)
            if not path:
                continue
            try:
                self.sounds[name] = pyglet.media.load(path, streaming=False)
            except Exception as e:
                if not warned:
                    print(f"Black Box: could not load sounds ({e}). "
                          "mp3 playback may need FFmpeg installed.")
                    warned = True

    @staticmethod
    def match_image(imgs, name):
        """Find the file for an image name, tolerating small differences in naming
        (e.g. direct_down.png or Direct_Column_Down.PNG for direct_column_down)."""
        if name in imgs:
            return imgs[name]
        first, last = name.split("_")[0], name.split("_")[-1]
        if last == "sphere":                       # e.g. yellow_sphere
            cands = [st for st in imgs if first in st and "sphere" in st] or \
                    [st for st in imgs if st.startswith(first)]
        else:                                       # e.g. direct_column_down / return_down
            cands = [st for st in imgs if st.startswith(first) and st.endswith(last)]
        return imgs[cands[0]] if cands else None

    def play(self, name):
        src = self.sounds.get(name)
        if src is None or not self.sound_on:
            return
        try:
            if name == "start" and self.start_player is not None:
                self.start_player.delete()          # don't stack up "mixing" sounds
            player = src.play()
            if name == "start":
                self.start_player = player
            self.players = (self.players + [player])[-16:]
        except Exception:
            pass

    def add_sprite(self, objs, name, x, y, size, group, opacity=255):
        """Add an image, scaled to fit `size` pixels and centred on (x, y). False if missing."""
        tex = self.img.get(name)
        if tex is None:
            return False
        s = size / max(tex.width, tex.height)
        sp = sprite.Sprite(tex, x=x - tex.width * s / 2, y=y - tex.height * s / 2,
                           batch=self.batch, group=group)
        sp.scale = s
        if opacity != 255:
            sp.opacity = opacity
        objs.append(sp)
        return True

    def port_icon(self, pid, kind):
        """Image name for a rebound result at a border square, or None if not available.

        'H' (head-on hit) uses direct_column_*; 'R' (reflection) uses return_*."""
        dx, dy = self.ports[pid][1]
        side = {(0, -1): "up", (0, 1): "down", (1, 0): "left", (-1, 0): "right"}[(dx, dy)]
        name = f"{'return' if kind == 'R' else 'direct_column'}_{side}"
        return name if name in self.img else None

    def layout(self):
        """Position everything for the current window size and grid dimensions."""
        w, h = self.width, self.height
        for lab, y in ((self.title_label, h - 30), (self.timer_label, h - 75),
                       (self.info_label, h - 110)):
            lab.x, lab.y = w // 2, y
        for lab in (self.msg_label, self.help_label, self.help2_label):
            lab.x = w // 2

        # DONE button beside the timer; settings bar centred under the info line
        self.done_btn = {"x": w - 150, "y": h - 75 - 22, "w": 120, "h": 44}
        self.new_btn = {"x": 30, "y": h - 75 - 22, "w": 120, "h": 44}
        self.reveal_btn = {"x": w - 150 - 10 - 120, "y": h - 75 - 22, "w": 120, "h": 44}
        self.settings_y = h - 150
        total = 2 * (DD_TITLE_W + DD_BOX_W) + 2 * SETTINGS_GAP + SOUND_W + 10 + RESET_W
        x0 = (w - total) // 2
        self.dropdowns = []
        for key_, title in (("size", "Size"), ("n", "Spheres")):
            self.dropdowns.append({"key": key_, "title": title, "x0": x0,
                                   "box": {"x": x0 + DD_TITLE_W, "y": self.settings_y - 14,
                                           "w": DD_BOX_W, "h": 28}})
            x0 += DD_TITLE_W + DD_BOX_W + SETTINGS_GAP
        self.sound_btn = {"x": x0, "y": self.settings_y - 14, "w": SOUND_W, "h": 28}
        self.reset_btn = {"x": x0 + SOUND_W + 10, "y": self.settings_y - 14, "w": RESET_W, "h": 28}

        # the board: as large as fits, centred between header and footer
        bw = w - 40
        bh = h - BOARD_BOTTOM - HEADER_H
        self.cell = max(8, min(MAX_CELL, bw // (self.cols + 2), bh // (self.rows + 2)))
        self.gx0 = (w - self.cols * self.cell) // 2
        self.gy0 = BOARD_BOTTOM + (bh - (self.rows + 2) * self.cell) // 2 + self.cell
        self.dirty = True

    def on_resize(self, width, height):
        super().on_resize(width, height)
        if getattr(self, "ready", False):
            self.hover = None
            self.layout()
            self.request_save()

    def build_ports(self):
        """Ports are the border squares. Each has an entry cell and a direction."""
        self.ports = []           # (entry_cell, direction, screen_cell)
        self.screen_to_port = {}
        self.exit_lookup = {}     # (cell, inward direction) -> port id

        def add(entry, d, scr):
            pid = len(self.ports)
            self.ports.append((entry, d, scr))
            self.screen_to_port[scr] = pid
            self.exit_lookup[(entry, d)] = pid

        C, R = self.cols, self.rows
        for k in range(C):
            add((k, R - 1), (0, -1), (k, R))      # top, shooting down
            add((k, 0), (0, 1), (k, -1))          # bottom, shooting up
        for k in range(R):
            add((0, k), (1, 0), (-1, k))          # left, shooting right
            add((C - 1, k), (-1, 0), (C, k))      # right, shooting left

    def new_game(self, n=None, size=None):
        size = clamp(self.cols if size is None else size, MIN_SIZE, MAX_SIZE)
        self.cols = self.rows = size              # the field is always square
        n = self.n if n is None else n
        self.n = clamp(n, MIN_SPHERES, MAX_SPHERES)
        self.open_dd = None
        self.reset_armed = 0.0                    # time until which Reset Best awaits confirmation

        self.layout()
        self.build_ports()

        cells = [(x, y) for x in range(self.cols) for y in range(self.rows)]
        self.spheres = set(random.sample(cells, self.n))
        self.guesses = set()
        self.highlights = set()   # purely visual notes, never counted as guesses
        self.preview = None       # (kind, exit port, points) for the hovered border square
        self.results = {}         # port id -> ('H'|'R'|'P', number)
        self.anims = []           # shots currently in flight
        self.pending = set()      # ports waiting for their shot animation to finish
        self.effects = []         # [x, y, color, age] pop effects
        self.next_num = 1
        self.shots = 0
        self.start = None
        self.penalty = 0.0
        self.final = 0.0
        self.state = "playing"    # playing | won | revealed
        self.hover = None
        self.msg_label.text = "Fire shots from the border squares. Mark where you think the spheres are."
        self.dirty = True
        self.play("start")

    def line_cells(self, pid):
        """Cells of the whole column (top/bottom squares) or row (left/right squares)."""
        (x, y), (dx, dy), _ = self.ports[pid]
        if dx == 0:
            return [(x, j) for j in range(self.rows)]
        return [(i, y) for i in range(self.cols)]

    def score_key(self):
        return f"{self.cols}x{self.rows}x{self.n}"

    def change_setting(self, setting, delta):
        size, n = self.cols, self.n
        if setting == "size":
            size = clamp(size + delta, MIN_SIZE, MAX_SIZE)
        else:
            n = clamp(n + delta, MIN_SPHERES, MAX_SPHERES)
        self.apply_settings(n, size)

    def apply_settings(self, n, size):
        if (size, n) != (self.cols, self.n):
            self.new_game(n, size)
            self.request_save()

    # dropdown lists ----------------------------------------------------------
    def dd_by_key(self, key_):
        return next(d for d in self.dropdowns if d["key"] == key_)

    def dd_current(self, key_):
        return self.cols if key_ == "size" else self.n

    def dd_popup(self, dd):
        """Geometry of a dropdown's list: (x, y, w, h, visible_rows). It hangs below the
        box and shows as many rows as fit in the window (scroll for the rest)."""
        box = dd["box"]
        rows = min(len(DD_VALUES[dd["key"]]), max(3, int((box["y"] - 6) // DD_ROW_H)))
        return box["x"], box["y"] - rows * DD_ROW_H, box["w"], rows * DD_ROW_H, rows

    def open_dropdown(self, key_):
        vals = DD_VALUES[key_]
        rows = self.dd_popup(self.dd_by_key(key_))[4]
        self.open_dd = key_
        self.dd_scroll = clamp(vals.index(self.dd_current(key_)) - rows // 2, 0, len(vals) - rows)
        self.dirty = True

    def pick(self, key_, idx):
        value = DD_VALUES[key_][idx]
        if key_ == "size":
            self.apply_settings(self.n, value)
        else:
            self.apply_settings(value, self.cols)

    # sound and saved settings ----------------------------------------------------
    def toggle_sound(self):
        self.sound_on = not self.sound_on
        if not self.sound_on:                     # cut off anything still playing
            for p in self.players:
                try:
                    p.delete()
                except Exception:
                    pass
            self.players, self.start_player = [], None
        self.dirty = True
        self.request_save()

    def reset_best(self):
        """Clear the saved best time(s) for the current size / sphere count.
        Needs a second click within a few seconds, since it can't be undone."""
        key_ = self.score_key()
        what = f"{self.cols}x{self.rows} grid with {self.n} spheres"
        now = time.monotonic()
        if not self.scores.get(key_):
            self.reset_armed = 0.0
            self.msg_label.text = f"No best time is saved for the {what}."
        elif now < self.reset_armed:
            del self.scores[key_]
            save_scores(self.scores)
            self.reset_armed = 0.0
            self.msg_label.text = f"Best time for the {what} cleared."
            self.play("remove")
        else:
            self.reset_armed = now + RESET_CONFIRM_SECS
            self.msg_label.text = (f"Click Reset Best again within {int(RESET_CONFIRM_SECS)} seconds "
                                   f"to clear the best time for the {what}.")
        self.dirty = True

    def save_settings(self):
        write_json(SETTINGS_FILE, {"width": int(self.width), "height": int(self.height),
                                   "size": self.cols, "spheres": self.n,
                                   "sound": self.sound_on})

    def _save_cb(self, dt):
        self.save_settings()

    def request_save(self):
        """Save shortly after the last change (so dragging a window edge isn't a flood of writes)."""
        pyglet.clock.unschedule(self._save_cb)
        pyglet.clock.schedule_once(self._save_cb, 0.6)

    def on_close(self):
        pyglet.clock.unschedule(self._save_cb)
        self.save_settings()
        super().on_close()

    # ------------------------------------------------------------------ rays
    def trace(self, pid, spheres=None, path=None):
        """Follow a shot. Returns ('H', None), ('R', None) or ('X', exit_port).

        H = head-on hit, R = reflected back, X = came out at exit_port.

        Uses the real spheres unless another set is given. If `path` is a list,
        the route is appended to it as (cx, cy) cell coordinates (floats allowed).
        """
        (x, y), (dx, dy), scr = self.ports[pid]
        sp = self.spheres if spheres is None else spheres
        pts = path if path is not None else []
        pts.append(scr)

        # Entry square itself: sphere there is a head-on hit; a sphere diagonally
        # next to it (in the row/column we fired from) reflects the shot.
        if (x, y) in sp:
            pts.append((x - 0.35 * dx, y - 0.35 * dy))
            return "H", None
        px, py = -dy, dx
        if (x + px, y + py) in sp or (x - px, y - py) in sp:
            pts.append((x - 0.5 * dx, y - 0.5 * dy))
            return "R", None
        pts.append((x, y))

        for _ in range(5000):
            ax, ay = x + dx, y + dy
            if not (0 <= ax < self.cols and 0 <= ay < self.rows):
                # leaves the grid from the cell (x, y)
                ex = self.exit_lookup[((x, y), (-dx, -dy))]
                pts.append(self.ports[ex][2])
                return "X", ex
            if (ax, ay) in sp:
                pts.append((x + 0.6 * dx, y + 0.6 * dy))
                return "H", None
            px, py = -dy, dx
            left = (ax + px, ay + py) in sp
            right = (ax - px, ay - py) in sp
            if left and right:
                dx, dy = -dx, -dy            # pinched: reverse
            elif left:
                dx, dy = -px, -py            # sphere on one side: turn away
            elif right:
                dx, dy = px, py
            else:
                x, y = ax, ay
                pts.append((x, y))
        return "R", None

    def fire(self, pid):
        if self.state != "playing" or pid in self.results or pid in self.pending:
            return
        self.start_clock()
        self.shots += 1
        self.play("shot")
        kind, ex = self.trace(pid)
        if kind == "H":
            ex, out = pid, {pid: ("H", 0)}
        elif kind == "R" or ex == pid:
            ex, out = pid, {pid: ("R", 0)}
        else:
            num = self.next_num
            self.next_num += 1
            out = {pid: ("P", num), ex: ("P", num)}
        self.pending.update(out)
        self.anims.append({"pid": pid, "ex": ex, "out": out, "t": 0.0})
        self.dirty = True

    @staticmethod
    def result_color(res):
        if res[0] == "H":
            return (220, 70, 70)
        if res[0] == "R":
            return (235, 205, 80)
        return PAIR_COLORS[(res[1] - 1) % len(PAIR_COLORS)]

    def update(self, dt):
        """Advance shot animations; apply a shot's result when its animation ends."""
        finished = []
        for a in self.anims:
            a["t"] += dt
            if a["t"] >= ANIM_TOTAL:
                finished.append(a)
        for e in self.effects:
            e[3] += dt
        self.effects = [e for e in self.effects if e[3] < EFFECT_TIME]
        for a in finished:
            self.anims.remove(a)
            for p, res in a["out"].items():
                self.pending.discard(p)
                self.results[p] = res
                x, y = self.cc(*self.ports[p][2])
                self.effects.append([x, y, self.result_color(res), 0.0])
            self.dirty = True

    # ---------------------------------------------------------------- timing
    def start_clock(self):
        if self.start is None:
            self.start = time.monotonic()

    def elapsed(self):
        if self.state != "playing":
            return self.final
        if self.start is None:
            return self.penalty
        return time.monotonic() - self.start + self.penalty

    def tick(self, dt):
        self.timer_label.text = fmt_time(self.elapsed())
        if self.reset_armed and time.monotonic() >= self.reset_armed:
            self.reset_armed = 0.0                # confirmation window ran out
            self.dirty = True

    # --------------------------------------------------------------- actions
    def submit(self):
        if self.state != "playing":
            return
        if len(self.guesses) != self.n:
            self.msg_label.text = f"Place exactly {self.n} markers before submitting ({len(self.guesses)} placed)."
            self.play("wrong")
            return
        if self.guesses == self.spheres:
            self.start_clock()
            self.final = self.elapsed()
            self.state = "won"
            key_ = self.score_key()
            old = self.scores.get(key_, [])
            times = sorted(old + [self.final])[:5]
            best = times[0] == self.final and self.final not in old
            self.scores[key_] = times
            save_scores(self.scores)
            self.msg_label.text = (f"Solved in {fmt_time(self.final)} with {self.shots} shots!"
                                   + ("  New best!" if best else "") + "  Press N for a new game.")
            self.play("win")
        else:
            self.start_clock()
            correct = len(self.guesses & self.spheres)
            self.penalty += PENALTY
            self.msg_label.text = f"{correct} of {self.n} correct. +{int(PENALTY)}s penalty - keep searching."
            self.play("wrong")
        self.dirty = True

    def reveal(self):
        if self.state == "playing":
            self.final = self.elapsed()
            self.state = "revealed"
            self.msg_label.text = "Revealed. Press N for a new game."
            self.dirty = True

    # ----------------------------------------------------------------- input
    def screen_cell(self, x, y):
        return int((x - self.gx0) // self.cell), int((y - self.gy0) // self.cell)

    def hit_test(self, x, y):
        if self.open_dd is not None:               # an open list is on top of everything
            px, py, pw, ph, rows = self.dd_popup(self.dd_by_key(self.open_dd))
            if px <= x < px + pw and py <= y < py + ph:
                k = min(int((py + ph - y) // DD_ROW_H), rows - 1)
                return "ddi", self.dd_scroll + k
        d = self.done_btn
        if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
            return "done", 0
        d = self.new_btn
        if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
            return "new", 0
        d = self.reveal_btn
        if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
            return "reveal", 0
        d = self.sound_btn
        if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
            return "sound", 0
        d = self.reset_btn
        if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
            return "reset", 0
        for dd in self.dropdowns:
            d = dd["box"]
            if d["x"] <= x < d["x"] + d["w"] and d["y"] <= y < d["y"] + d["h"]:
                return "dd", dd["key"]
        c = self.screen_cell(x, y)
        if 0 <= c[0] < self.cols and 0 <= c[1] < self.rows:
            return "cell", c
        if c in self.screen_to_port:
            return "port", self.screen_to_port[c]
        return None

    def on_mouse_motion(self, x, y, dx, dy):
        h = self.hit_test(x, y)
        if self.open_dd is not None and h and h[0] in ("cell", "port"):
            h = None                                # the open list hides what is under it
        if h != self.hover:
            self.hover = h
            self.dirty = True

    def on_mouse_scroll(self, x, y, scroll_x, scroll_y):
        if self.open_dd is None or scroll_y == 0:
            return
        vals = DD_VALUES[self.open_dd]
        rows = self.dd_popup(self.dd_by_key(self.open_dd))[4]
        step = -1 if scroll_y > 0 else 1
        self.dd_scroll = clamp(self.dd_scroll + step, 0, len(vals) - rows)
        self.dirty = True

    def on_mouse_press(self, x, y, button, modifiers):
        h = self.hit_test(x, y)
        if self.open_dd is not None:                # an open list gets the click
            name = self.open_dd
            self.open_dd = None
            self.dirty = True
            if h and h[0] == "ddi" and button == mouse.LEFT:
                self.pick(name, h[1])
            elif h and h[0] == "dd" and h[1] != name and button == mouse.LEFT:
                self.open_dropdown(h[1])
            return
        if not h:
            return
        if h[0] == "dd":                            # settings work in any state
            if button == mouse.LEFT:
                self.open_dropdown(h[1])
            return
        if h[0] == "sound":
            if button == mouse.LEFT:
                self.toggle_sound()
            return
        if h[0] == "reset":
            if button == mouse.LEFT:
                self.reset_best()
            return
        if h[0] == "reveal":                    # same as pressing R
            if button == mouse.LEFT:
                self.reveal()
            return
        if h[0] == "new":                       # same as pressing N
            if button == mouse.LEFT:
                self.new_game()
            return
        if h[0] == "done":                      # same as pressing Enter
            if button == mouse.LEFT:
                self.submit()
            return
        if button not in (mouse.LEFT, mouse.RIGHT) or self.state != "playing":
            return
        if h[0] == "port":
            if button == mouse.LEFT:
                self.fire(h[1])
            else:
                cells = set(self.line_cells(h[1]))
                if cells <= self.highlights:          # whole line lit -> clear it
                    self.highlights -= cells
                else:                                  # otherwise light the whole line
                    self.highlights |= cells
                self.play("highlight")
                self.dirty = True
        else:
            if button == mouse.LEFT:
                if h[1] in self.guesses:
                    self.guesses.discard(h[1])
                    self.play("remove")
                elif len(self.guesses) >= self.n:
                    self.msg_label.text = (f"All {self.n} markers are placed - "
                                           "remove one before placing another.")
                    return
                else:
                    self.guesses.add(h[1])
                    self.play("place")
                self.start_clock()
            else:
                self.highlights ^= {h[1]}
                self.play("highlight")
            self.dirty = True

    def on_key_press(self, symbol, modifiers):
        if symbol == key.ESCAPE and self.open_dd is not None:
            self.open_dd = None                     # Esc closes an open list first
            self.dirty = True
        elif symbol in (key.RETURN, key.ENTER):
            self.submit()
        elif symbol == key.N:
            self.new_game()
        elif symbol == key.R:
            self.reveal()
        elif symbol == key.M:
            self.toggle_sound()
        elif symbol in (key.LEFT, key.DOWN):
            self.change_setting("size", -1)
        elif symbol in (key.RIGHT, key.UP):
            self.change_setting("size", 1)
        elif symbol in (key.PLUS, key.EQUAL, key.NUM_ADD):
            self.change_setting("n", 1)
        elif symbol in (key.MINUS, key.NUM_SUBTRACT):
            self.change_setting("n", -1)
        else:
            return super().on_key_press(symbol, modifiers)

    # --------------------------------------------------------------- drawing
    def cc(self, cx, cy):
        return self.gx0 + (cx + 0.5) * self.cell, self.gy0 + (cy + 0.5) * self.cell

    def rebuild(self):
        self.batch = pyglet.graphics.Batch()
        b = self.batch
        objs = self.objs = []
        playing = self.state == "playing"
        cell = self.cell

        def text(t, x, y, size, color=(230, 230, 240, 255), weight="normal", ax="center",
                 group=None):
            objs.append(pyglet.text.Label(
                t, x=x, y=y, anchor_x=ax, anchor_y="center", font_size=size,
                weight=weight, color=color, batch=b, group=group or self.g_text))

        # DONE button
        d = self.done_btn
        if not playing:
            col = (50, 60, 75)
        elif self.hover == ("done", 0):
            col = (80, 185, 115)
        else:
            col = (60, 150, 95)
        objs.append(shapes.BorderedRectangle(
            d["x"], d["y"], d["w"], d["h"], border=2, color=col,
            border_color=(20, 40, 30), batch=b, group=self.g_mid))
        text("DONE", d["x"] + d["w"] / 2, d["y"] + d["h"] / 2, 16,
             (255, 255, 255, 255) if playing else (130, 140, 155, 255), "bold")

        # REVEAL button
        d = self.reveal_btn
        if not playing:
            col = (50, 60, 75)
        elif self.hover == ("reveal", 0):
            col = (225, 125, 80)
        else:
            col = (185, 100, 60)
        objs.append(shapes.BorderedRectangle(
            d["x"], d["y"], d["w"], d["h"], border=2, color=col,
            border_color=(50, 30, 20), batch=b, group=self.g_mid))
        text("REVEAL", d["x"] + d["w"] / 2, d["y"] + d["h"] / 2, 15,
             (255, 255, 255, 255) if playing else (130, 140, 155, 255), "bold")

        # NEW GAME button
        d = self.new_btn
        col = (90, 130, 205) if self.hover == ("new", 0) else (60, 100, 170)
        objs.append(shapes.BorderedRectangle(
            d["x"], d["y"], d["w"], d["h"], border=2, color=col,
            border_color=(20, 30, 50), batch=b, group=self.g_mid))
        text("NEW GAME", d["x"] + d["w"] / 2, d["y"] + d["h"] / 2, 14,
             (255, 255, 255, 255), "bold")

        # settings bar: dropdown boxes and the sound toggle
        for dd in self.dropdowns:
            box = dd["box"]
            if self.open_dd == dd["key"]:
                col = (80, 100, 140)
            elif self.hover == ("dd", dd["key"]):
                col = (95, 115, 160)
            else:
                col = (55, 68, 95)
            text(dd["title"], dd["x0"], self.settings_y, 12, (170, 185, 210, 255), ax="left")
            objs.append(shapes.BorderedRectangle(
                box["x"], box["y"], box["w"], box["h"], border=1, color=col,
                border_color=(20, 28, 42), batch=b, group=self.g_mid))
            text(str(self.dd_current(dd["key"])), box["x"] + (box["w"] - 18) / 2,
                 self.settings_y, 14, (255, 220, 120, 255), "bold")
            ax_, ay_ = box["x"] + box["w"] - 11, self.settings_y
            objs.append(shapes.Triangle(ax_ - 5, ay_ + 3, ax_ + 5, ay_ + 3, ax_, ay_ - 4,
                                        color=(190, 200, 220), batch=b, group=self.g_mid))
        d = self.sound_btn
        hov = self.hover == ("sound", 0)
        if self.sound_on:
            col = (80, 160, 112) if hov else (60, 125, 90)
        else:
            col = (160, 90, 90) if hov else (115, 65, 65)
        objs.append(shapes.BorderedRectangle(
            d["x"], d["y"], d["w"], d["h"], border=1, color=col,
            border_color=(20, 28, 42), batch=b, group=self.g_mid))
        text("Sound: ON" if self.sound_on else "Sound: OFF", d["x"] + d["w"] / 2,
             d["y"] + d["h"] / 2, 12, (255, 255, 255, 255), "bold")
        d = self.reset_btn
        armed = time.monotonic() < self.reset_armed
        hov = self.hover == ("reset", 0)
        if armed:
            col = (215, 85, 85) if hov else (185, 65, 65)
        else:
            col = (95, 115, 160) if hov else (55, 68, 95)
        objs.append(shapes.BorderedRectangle(
            d["x"], d["y"], d["w"], d["h"], border=1, color=col,
            border_color=(20, 28, 42), batch=b, group=self.g_mid))
        text("Confirm reset?" if armed else "Reset Best", d["x"] + d["w"] / 2,
             d["y"] + d["h"] / 2, 12, (255, 255, 255, 255), "bold")

        # token tray: one yellow sphere per marker still to place (faint = already on the board)
        w = self.width
        ty = self.height - 185
        left_n = max(0, self.n - len(self.guesses))
        x0 = (w - (100 + self.n * TOKEN_STEP)) // 2
        text("Tokens left:", x0, ty, 12, (170, 185, 210, 255), ax="left")
        for i in range(self.n):
            tx = x0 + 100 + i * TOKEN_STEP + TOKEN_SIZE / 2
            if i < left_n:
                if not self.add_sprite(objs, "yellow_sphere", tx, ty, TOKEN_SIZE, self.g_mid):
                    objs.append(shapes.Circle(tx, ty, TOKEN_SIZE * 0.42, color=(240, 200, 60),
                                              batch=b, group=self.g_mid))
                    objs.append(shapes.Circle(tx, ty, TOKEN_SIZE * 0.26, color=(30, 46, 56),
                                              batch=b, group=self.g_fg))
            elif not self.add_sprite(objs, "yellow_sphere", tx, ty, TOKEN_SIZE, self.g_mid, 45):
                objs.append(shapes.Circle(tx, ty, TOKEN_SIZE * 0.42, color=(60, 70, 90, 120),
                                          batch=b, group=self.g_mid))

        # grid
        for cx in range(self.cols):
            for cy in range(self.rows):
                col = (34, 46, 66) if (cx + cy) % 2 == 0 else (40, 54, 78)
                if playing and self.hover == ("cell", (cx, cy)):
                    col = (70, 90, 125)
                objs.append(shapes.BorderedRectangle(
                    self.gx0 + cx * cell, self.gy0 + cy * cell, cell, cell, border=1,
                    color=col, border_color=(20, 28, 42), batch=b, group=self.g_bg))

        # highlights (right click)
        for (cx, cy) in self.highlights:
            objs.append(shapes.Rectangle(
                self.gx0 + cx * cell + 2, self.gy0 + cy * cell + 2, cell - 4, cell - 4,
                color=(255, 210, 80, 95), batch=b, group=self.g_hl))

        # preview of the hovered border square's path, assuming the markers are the spheres
        self.preview = None
        if playing and self.hover and self.hover[0] == "port":
            pid = self.hover[1]
            pts = []
            kind, ex = self.trace(pid, self.guesses, pts)
            if kind == "X" and ex == pid:
                kind = "R"
            self.preview = (kind, ex, pts)
            sp = [self.cc(*p) for p in pts]
            for (x1, y1), (x2, y2) in zip(sp, sp[1:]):
                objs.append(shapes.Line(x1, y1, x2, y2, thickness=3,
                                        color=(255, 235, 140, 210), batch=b, group=self.g_path))
            for (x1, y1) in sp[1:-1]:
                objs.append(shapes.Circle(x1, y1, 2.5, color=(255, 235, 140, 210),
                                          batch=b, group=self.g_path))
            ex_, ey_ = sp[-1]
            end_col = {"H": (220, 70, 70), "R": (235, 205, 80)}.get(kind, (255, 255, 255))
            objs.append(shapes.Circle(ex_, ey_, cell * 0.17, color=(*end_col, 230),
                                      batch=b, group=self.g_path))

        size = cell * 0.88
        # spheres (only once the game is over): green when found, blue when missed
        if not playing:
            for (cx, cy) in self.spheres:
                x, y = self.cc(cx, cy)
                if (cx, cy) in self.guesses:
                    drawn = self.add_sprite(objs, "green_sphere", x, y, size, self.g_mid)
                else:                                  # a sphere that was never guessed
                    drawn = (self.add_sprite(objs, "blue_sphere", x, y, size, self.g_mid)
                             or self.add_sprite(objs, "green_sphere", x, y, size, self.g_mid, 120))
                if not drawn:
                    col = (90, 200, 120) if self.state == "won" else (210, 70, 70)
                    objs.append(shapes.Circle(x, y, cell * 0.36, color=col,
                                              batch=b, group=self.g_mid))

        # guess markers: yellow while playing; red (wrong) or green (right) once it is over
        for (cx, cy) in self.guesses:
            x, y = self.cc(cx, cy)
            if playing:
                if self.add_sprite(objs, "yellow_sphere", x, y, size, self.g_fg):
                    continue
            elif (cx, cy) in self.spheres:
                if "green_sphere" in self.img:
                    continue                      # already drawn as a green sphere above
            elif self.add_sprite(objs, "red_sphere", x, y, size, self.g_fg):
                continue
            # fallback shapes when the pictures are missing
            wrong = (not playing) and (cx, cy) not in self.spheres
            if wrong:
                r = cell * 0.28
                for a_ in ((-r, -r, r, r), (-r, r, r, -r)):
                    objs.append(shapes.Line(x + a_[0], y + a_[1], x + a_[2], y + a_[3],
                                            thickness=4, color=(255, 90, 90),
                                            batch=b, group=self.g_fg))
            else:
                objs.append(shapes.Circle(x, y, cell * 0.30, color=(100, 220, 150),
                                          batch=b, group=self.g_fg))
                objs.append(shapes.Circle(x, y, cell * 0.20, color=(30, 46, 56),
                                          batch=b, group=self.g_fg))

        # ports
        for pid, (_, _, scr) in enumerate(self.ports):
            x, y = self.cc(*scr)
            res = self.results.get(pid)
            label, tcol, icon = None, (20, 20, 20, 255), None
            if res is None:
                if pid in self.pending:
                    col = (95, 105, 135)
                elif playing and self.hover == ("port", pid):
                    col = (120, 150, 200)
                else:
                    col = (70, 80, 105)
            elif res[0] in ("H", "R"):
                icon = self.port_icon(pid, res[0])
                if icon:
                    col = (55, 66, 90)
                elif res[0] == "R":
                    col, label = (235, 205, 80), "R"
                else:
                    col, label, tcol = (200, 60, 60), "H", (255, 255, 255, 255)
            else:
                col, label = self.result_color(res), str(res[1])
            lit = all(c in self.highlights for c in self.line_cells(pid))
            objs.append(shapes.BorderedRectangle(
                x - cell / 2 + 3, y - cell / 2 + 3, cell - 6, cell - 6, border=3 if lit else 1,
                color=col, border_color=(255, 210, 80) if lit else (15, 20, 30),
                batch=b, group=self.g_mid))
            if icon:
                self.add_sprite(objs, icon, x, y, cell - 6, self.g_fg)
            if label:
                text(label, x, y, max(9, int(cell * 0.29)), tcol, "bold")

        # the open dropdown list
        if self.open_dd is not None:
            dd = self.dd_by_key(self.open_dd)
            px, py, pw, ph, rows = self.dd_popup(dd)
            vals = DD_VALUES[dd["key"]]
            self.dd_scroll = clamp(self.dd_scroll, 0, len(vals) - rows)
            cur = self.dd_current(dd["key"])
            objs.append(shapes.BorderedRectangle(
                px, py, pw, ph, border=1, color=(28, 36, 54), border_color=(120, 140, 180),
                batch=b, group=self.g_pop))
            for k in range(rows):
                i = self.dd_scroll + k
                ry = py + ph - (k + 1) * DD_ROW_H
                if self.hover == ("ddi", i):
                    objs.append(shapes.Rectangle(px + 1, ry, pw - 2, DD_ROW_H,
                                                 color=(100, 125, 175), batch=b, group=self.g_pop_item))
                elif vals[i] == cur:
                    objs.append(shapes.Rectangle(px + 1, ry, pw - 2, DD_ROW_H,
                                                 color=(60, 85, 130), batch=b, group=self.g_pop_item))
                text(str(vals[i]), px + (pw - 8) / 2, ry + DD_ROW_H / 2, 12,
                     (255, 255, 255, 255) if vals[i] != cur else (255, 220, 120, 255),
                     "bold" if vals[i] == cur else "normal", group=self.g_pop_text)
            if rows < len(vals):                    # scroll indicator
                bar_h = max(14, ph * rows / len(vals))
                frac = self.dd_scroll / (len(vals) - rows)
                objs.append(shapes.Rectangle(px + pw - 5, py + ph - bar_h - (ph - bar_h) * frac - 1,
                                             3, bar_h, color=(150, 170, 210),
                                             batch=b, group=self.g_pop_item))

        best = min(self.scores.get(self.score_key(), []), default=None)
        self.info_label.text = (
            f"Markers: {len(self.guesses)}/{self.n}    Shots: {self.shots}"
            f"    Best ({self.score_key()}): {fmt_time(best) if best is not None else '--'}")
        self.timer_label.text = fmt_time(self.elapsed())
        self.dirty = False

    def port_dot(self, pid, u):
        """Point u (0..1) of the way from a border square into the grid."""
        _, (dx, dy), scr = self.ports[pid]
        x, y = self.cc(*scr)
        return x + dx * self.cell * 0.95 * u, y + dy * self.cell * 0.95 * u

    def glow(self, x, y, color, alpha, scale=1.0):
        alpha = max(0.0, min(1.0, alpha))
        if alpha <= 0:
            return
        s = scale * self.cell / BASE_CELL
        shapes.Circle(x, y, 18 * s, color=(*color, int(70 * alpha))).draw()
        shapes.Circle(x, y, 8 * s, color=(*color, int(255 * alpha))).draw()
        shapes.Circle(x, y, 4 * s, color=(255, 255, 255, int(255 * alpha))).draw()

    def draw_overlay(self):
        """Shots fly into the box, vanish (the inside stays hidden), then emerge at their exit."""
        ease = lambda v: v * v * (3 - 2 * v)
        ray = (255, 235, 140)
        for a in self.anims:
            t = a["t"]
            if t < ANIM_IN:                                   # entering the box
                u = ease(t / ANIM_IN)
                for k in range(5, -1, -1):
                    uu = max(0.0, u - k * 0.09)
                    x, y = self.port_dot(a["pid"], uu)
                    self.glow(x, y, ray, (1 - u) * (1 - k * 0.16), 1 - k * 0.1)
            elif t < ANIM_IN + ANIM_HIDE:                     # somewhere inside...
                v = (t - ANIM_IN) / ANIM_HIDE
                x, y = self.cc(*self.ports[a["pid"]][2])
                self.glow(x, y, ray, 0.25 + 0.2 * abs(1 - 2 * ((v * 3) % 1)), 0.7)
            else:                                             # emerging at the exit
                v = (t - ANIM_IN - ANIM_HIDE) / ANIM_OUT
                u = 1 - ease(v)
                col = self.result_color(a["out"][a["ex"]])
                for k in range(6):
                    uu = min(1.0, u + k * 0.09)
                    x, y = self.port_dot(a["ex"], uu)
                    self.glow(x, y, col, v * (1 - k * 0.16), 1 - k * 0.1)
        for x, y, col, age in self.effects:
            f = age / EFFECT_TIME
            shapes.Circle(x, y, self.cell * (0.27 + 0.65 * f), color=(*col, int(150 * (1 - f)))).draw()

    def on_draw(self):
        if self.dirty:
            self.rebuild()
        pyglet.gl.glClearColor(0.07, 0.09, 0.13, 1)
        self.clear()
        self.batch.draw()
        self.draw_overlay()
        self.title_label.draw()
        self.timer_label.draw()
        self.info_label.draw()
        self.msg_label.draw()
        self.help_label.draw()
        self.help2_label.draw()


if __name__ == "__main__":
    settings = load_settings()
    nums = [int(a) for a in sys.argv[1:3] if a.isdigit()]
    n = nums[0] if len(nums) > 0 else settings["spheres"]
    size = nums[1] if len(nums) > 1 else settings["size"]
    BlackBox(n, size, settings)
    pyglet.app.run()
