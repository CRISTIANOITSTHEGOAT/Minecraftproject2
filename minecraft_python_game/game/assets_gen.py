"""
Procedural asset generator and safe loader for textures, item icons, GUI widgets,
sounds, and models.

Everything is generated as original Minecraft-*style* pixel art (16x16 block tiles,
32x32 item icons, an 18px-scale GUI widget sheet) with NumPy/Pillow - no external
or proprietary assets are required.
"""

import math
import os
import struct
import wave
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

from game.blocks import (
    ATLAS_COLS,
    ATLAS_ROWS,
    BLOCKS_BY_KEY,
    ITEMS,
    TILE_COORDS,
    TILE_PIXEL_SIZE,
)

ROOT_DIR = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT_DIR / "assets"
TEXTURES_DIR = ASSETS_DIR / "textures"
ICONS_DIR = TEXTURES_DIR / "icons"
SOUNDS_DIR = ASSETS_DIR / "sounds"
MODELS_DIR = ASSETS_DIR / "models"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clamp(v: float) -> int:
    return max(0, min(255, int(round(v))))


def _rgb(base: Tuple[int, int, int], dv: float) -> Tuple[int, int, int, int]:
    return (_clamp(base[0] + dv), _clamp(base[1] + dv), _clamp(base[2] + dv), 255)


def _shade(rgb: Tuple[int, int, int], f: float) -> Tuple[int, int, int]:
    return (_clamp(rgb[0] * f), _clamp(rgb[1] * f), _clamp(rgb[2] * f))


# ---------------------------------------------------------------------------
# 16x16 block / mob / effect tiles
# ---------------------------------------------------------------------------


def _noise_fill(px, rng, base, var=8, x0=0, y0=0, x1=16, y1=16):
    for y in range(y0, y1):
        for x in range(x0, x1):
            px[x, y] = _rgb(base, int(rng.randint(-var, var + 1)))


def _blobs(px, rng, colors, count=14, size=2):
    for _ in range(count):
        cx, cy = int(rng.randint(0, 16)), int(rng.randint(0, 16))
        c = colors[int(rng.randint(0, len(colors))) % len(colors)]
        for dy in range(size):
            for dx in range(size):
                px[(cx + dx) % 16, (cy + dy) % 16] = (c[0], c[1], c[2], 255)


def _stone_base(px, rng):
    _noise_fill(px, rng, (125, 125, 125), 6)
    for _ in range(10):
        x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
        px[x, y] = _rgb((105, 105, 105), int(rng.randint(-4, 5)))


def _generate_tile_image(tile_name: str, seed: int = 1337) -> Image.Image:
    """Create a 16x16 RGBA pixel-art tile for the given tile name."""
    rng = np.random.RandomState(seed + (abs(hash(tile_name)) % 10000))
    img = Image.new("RGBA", (TILE_PIXEL_SIZE, TILE_PIXEL_SIZE), (128, 128, 128, 255))
    px = img.load()

    # ------------------------------ terrain ------------------------------
    if tile_name == "grass_top":
        _noise_fill(px, rng, (116, 178, 74), 10)
        for _ in range(26):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((96, 152, 58), int(rng.randint(-6, 7)))
        for _ in range(16):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((134, 196, 92), int(rng.randint(-5, 6)))
    elif tile_name == "dirt":
        _noise_fill(px, rng, (134, 96, 67), 10)
        _blobs(px, rng, [(110, 78, 53), (155, 115, 85), (120, 86, 60)], 12, 1)
        _blobs(px, rng, [(110, 78, 53)], 5, 2)
    elif tile_name == "grass_side":
        _noise_fill(px, rng, (134, 96, 67), 10)
        _blobs(px, rng, [(110, 78, 53), (155, 115, 85)], 10, 1)
        for x in range(16):
            fringe = 2 + int(rng.randint(0, 3))
            if rng.random() < 0.35:
                fringe += 2
            for y in range(min(6, fringe)):
                dv = int(rng.randint(-8, 9))
                px[x, y] = (_clamp(106 + dv), _clamp(164 + dv), _clamp(66 + dv), 255)
    elif tile_name == "stone":
        _stone_base(px, rng)
    elif tile_name == "cobblestone":
        seeds = [(2, 2), (8, 1), (13, 3), (1, 8), (7, 7), (12, 9), (3, 13), (9, 12), (14, 14)]
        palette = [
            (148, 148, 148), (122, 122, 122), (158, 158, 158), (112, 112, 112),
            (136, 136, 136), (150, 150, 150), (118, 118, 118), (140, 140, 140), (128, 128, 128),
        ]
        for y in range(16):
            for x in range(16):
                d1, d2, idx = 99.0, 99.0, 0
                for i, (sx, sy) in enumerate(seeds):
                    d = math.hypot(x - sx, y - sy)
                    if d < d1:
                        d1, d2, idx = d, d1, i
                    elif d < d2:
                        d2 = d
                if d2 - d1 < 1.1:
                    px[x, y] = _rgb((86, 86, 86), int(rng.randint(-5, 6)))
                else:
                    px[x, y] = _rgb(palette[idx], int(rng.randint(-7, 8)))
    elif tile_name == "sand":
        _noise_fill(px, rng, (219, 207, 163), 8)
        for _ in range(20):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((202, 190, 144), int(rng.randint(-4, 5)))
        for _ in range(14):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((235, 225, 182), int(rng.randint(-4, 5)))
    elif tile_name == "gravel":
        _noise_fill(px, rng, (131, 127, 126), 10)
        _blobs(px, rng, [(95, 90, 89), (160, 155, 154), (75, 72, 71), (142, 138, 137), (110, 105, 104)], 16, 2)
    elif tile_name == "water":
        for y in range(16):
            for x in range(16):
                w = math.sin((x * 0.9) + math.sin(y * 1.4) * 1.4) * 9
                dv = int(rng.randint(-4, 5)) + int(w)
                px[x, y] = (_clamp(52 + dv), _clamp(106 + dv), _clamp(198 + dv), 178)
    elif tile_name == "bedrock":
        _noise_fill(px, rng, (66, 66, 66), 16)
        _blobs(px, rng, [(38, 38, 38), (92, 92, 92), (24, 24, 24), (110, 110, 110)], 22, 2)

    # ------------------------------- wood --------------------------------
    elif tile_name == "wood_side":
        col_shade = [0, -14, 6, -8, 10, -12, 2, -6, 8, -10, 4, -14, 6, -4, 10, -8]
        for x in range(16):
            for y in range(16):
                dv = col_shade[x] + int(rng.randint(-4, 5))
                px[x, y] = _rgb((102, 81, 51), dv)
        for _ in range(4):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 14))
            px[x, y] = (70, 55, 34, 255)
            px[x, y + 1] = (70, 55, 34, 255)
    elif tile_name == "wood_top":
        for y in range(16):
            for x in range(16):
                d = max(abs(x - 7.5), abs(y - 7.5))
                if d > 6.5:
                    px[x, y] = _rgb((102, 81, 51), int(rng.randint(-6, 7)))
                else:
                    ring = int(d) % 3
                    base = [(188, 155, 98), (167, 136, 83), (146, 118, 71)][ring]
                    px[x, y] = _rgb(base, int(rng.randint(-5, 6)))
    elif tile_name == "birch_side":
        _noise_fill(px, rng, (216, 213, 202), 5)
        for x in range(16):
            dv = int(rng.randint(-4, 5)) + (4 if x % 5 == 0 else 0)
            for y in range(16):
                px[x, y] = _rgb((214, 211, 199), dv + int(rng.randint(-3, 4)))
        for _ in range(7):
            x0, y0 = int(rng.randint(0, 12)), int(rng.randint(0, 16))
            ln = int(rng.randint(2, 5))
            for x in range(x0, min(16, x0 + ln)):
                px[x, y0] = (64, 61, 52, 255)
    elif tile_name == "birch_top":
        for y in range(16):
            for x in range(16):
                d = max(abs(x - 7.5), abs(y - 7.5))
                if d > 6.5:
                    px[x, y] = _rgb((214, 211, 199), int(rng.randint(-6, 6)))
                else:
                    ring = int(d) % 3
                    base = [(226, 218, 198), (206, 197, 176), (186, 176, 154)][ring]
                    px[x, y] = _rgb(base, int(rng.randint(-4, 5)))
    elif tile_name == "planks":
        _noise_fill(px, rng, (162, 130, 78), 6)
        for y in range(16):
            for x in range(16):
                if rng.random() < 0.06:
                    px[x, y] = _rgb((180, 148, 94), int(rng.randint(-4, 5)))
        for row in range(4):
            y = row * 4 + 3
            for x in range(16):
                px[x, y] = _rgb((112, 88, 50), int(rng.randint(-4, 5)))
            seam = (row * 5 + 2) % 16
            for y in range(row * 4, row * 4 + 3):
                px[seam, y] = (112, 88, 50, 255)
    elif tile_name == "leaves":
        _noise_fill(px, rng, (58, 122, 34), 14)
        for _ in range(30):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((34, 82, 20), int(rng.randint(-6, 7)))
        for _ in range(14):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((88, 158, 52), int(rng.randint(-6, 7)))
    elif tile_name == "wool":
        _noise_fill(px, rng, (233, 233, 233), 6)
        for y in range(0, 16, 4):
            for x in range(0, 16, 4):
                px[(x + 1) % 16, (y + 1) % 16] = (208, 208, 208, 255)
                px[(x + 2) % 16, (y + 2) % 16] = (246, 246, 246, 255)
    elif tile_name == "glass":
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        for i in range(16):
            px[i, 0] = px[0, i] = (214, 244, 248, 255)
            px[i, 15] = px[15, i] = (188, 224, 232, 255)
        px[1, 1] = px[14, 1] = px[1, 14] = px[14, 14] = (255, 255, 255, 255)
        for i in range(4, 9):
            px[i, 12 - i] = (255, 255, 255, 150)
            px[i + 1, 13 - i] = (255, 255, 255, 110)
        for i in range(10, 13):
            px[i, 15 - i + 8] = (255, 255, 255, 120)
    elif tile_name in ("coal_ore", "iron_ore", "gold_ore", "diamond_ore"):
        _stone_base(px, rng)
        ore = {
            "coal_ore": ((52, 52, 52), (30, 30, 30), (78, 78, 78)),
            "iron_ore": ((216, 178, 146), (168, 132, 104), (236, 208, 182)),
            "gold_ore": ((250, 214, 80), (204, 168, 42), (255, 236, 130)),
            "diamond_ore": ((82, 232, 232), (44, 172, 172), (168, 255, 252)),
        }[tile_name]
        for sx, sy in [(3, 3), (10, 4), (5, 10), (11, 11)]:
            px[sx, sy] = (ore[0][0], ore[0][1], ore[0][2], 255)
            px[sx + 1, sy] = (ore[0][0], ore[0][1], ore[0][2], 255)
            px[sx, sy + 1] = (ore[0][0], ore[0][1], ore[0][2], 255)
            px[sx + 1, sy + 1] = (ore[1][0], ore[1][1], ore[1][2], 255)
            px[sx - 1, sy] = (ore[2][0], ore[2][1], ore[2][2], 255)

    # ---------------------------- utility blocks --------------------------
    elif tile_name == "crafting_top":
        _noise_fill(px, rng, (156, 122, 70), 5)
        for i in range(16):
            px[i, 0] = px[0, i] = px[i, 15] = px[15, i] = (86, 60, 30, 255)
        for g in (5, 10):
            for i in range(1, 15):
                px[g, i] = (96, 68, 34, 255)
                px[i, g] = (96, 68, 34, 255)
        for cx, cy in [(2, 2), (12, 2), (2, 12), (12, 12)]:
            px[cx, cy] = (190, 152, 96, 255)
    elif tile_name == "crafting_side":
        _noise_fill(px, rng, (162, 130, 78), 6)
        for y in range(4):
            for x in range(16):
                px[x, y] = _rgb((104, 76, 42), int(rng.randint(-4, 5)))
        for y in range(6, 13):
            for x in (3, 4, 5, 10, 11, 12):
                px[x, y] = (92, 66, 36, 255)
        for x in range(3, 13):
            px[x, 9] = (162, 130, 78, 255)
    elif tile_name in ("furnace_front", "furnace_lit"):
        _stone_base(px, rng)
        for x in range(16):
            px[x, 0] = (98, 98, 98, 255)
        for y in range(9, 14):
            for x in range(4, 12):
                px[x, y] = (26, 26, 26, 255)
        for x in range(3, 13):
            px[x, 8] = (90, 90, 90, 255)
            px[x, 14] = (90, 90, 90, 255)
        if tile_name == "furnace_lit":
            fire = [(255, 176, 32), (255, 220, 90), (255, 140, 20), (255, 244, 160)]
            for y in range(10, 14):
                for x in range(5, 11):
                    c = fire[int(rng.randint(0, 4)) % 4]
                    px[x, y] = (c[0], c[1], c[2], 255)
    elif tile_name in ("furnace_side", "furnace_top"):
        _stone_base(px, rng)
        for i in range(16):
            px[i, 0] = px[0, i] = px[i, 15] = px[15, i] = (96, 96, 96, 255)
    elif tile_name == "torch":
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        for y in range(7, 16):
            px[7, y] = (109, 84, 52, 255)
            px[8, y] = (130, 102, 64, 255)
        for y in range(3, 7):
            px[7, y] = px[8, y] = (255, 224, 120, 255)
            px[6, y] = px[9, y] = (255, 164, 44, 255)
        px[7, 2] = px[8, 2] = (255, 244, 184, 255)
        px[6, 3] = px[9, 3] = (255, 200, 80, 255)
    elif tile_name in ("chest_front", "chest_side", "chest_top"):
        _noise_fill(px, rng, (111, 74, 34), 6)
        for i in range(16):
            px[i, 0] = px[0, i] = px[i, 15] = px[15, i] = (62, 40, 16, 255)
        if tile_name != "chest_top":
            for x in range(16):
                px[x, 9] = (58, 37, 15, 255)
                px[x, 10] = (86, 56, 24, 255)
        if tile_name == "chest_front":
            for y in range(7, 11):
                px[7, y] = px[8, y] = (148, 148, 150, 255)
            px[7, 7] = px[8, 7] = (190, 190, 192, 255)
        if tile_name == "chest_top":
            for i in range(1, 15):
                px[i, 1] = px[1, i] = px[i, 14] = px[14, i] = (86, 56, 24, 255)

    # ------------------------- break crack stages -------------------------
    elif tile_name.startswith("crack_"):
        stage = int(tile_name.split("_")[1])
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        strokes = 3 + stage * 3
        for _ in range(strokes):
            x, y = int(rng.randint(4, 12)), int(rng.randint(4, 12))
            steps = int(rng.randint(3, 7))
            for _s in range(steps):
                px[x, y] = (20, 20, 20, 200)
                if rng.random() < 0.4:
                    px[max(0, x - 1), y] = (20, 20, 20, 140)
                dx, dy = int(rng.randint(-1, 2)), int(rng.randint(-1, 2))
                x = max(1, min(14, x + dx))
                y = max(1, min(14, y + dy))
    elif tile_name == "selection":
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        for i in range(16):
            px[i, 0] = px[i, 15] = px[0, i] = px[15, i] = (0, 0, 0, 210)

    # ------------------------------ mob skins -----------------------------
    elif tile_name == "pig_side":
        _noise_fill(px, rng, (240, 177, 172), 6)
    elif tile_name == "pig_face":
        _noise_fill(px, rng, (240, 177, 172), 6)
        px[3, 6] = px[12, 6] = (20, 20, 20, 255)
        for y in range(8, 12):
            for x in range(5, 11):
                px[x, y] = _rgb((232, 152, 148), int(rng.randint(-4, 5)))
        px[6, 9] = px[9, 9] = (150, 90, 90, 255)
        px[6, 10] = px[9, 10] = (150, 90, 90, 255)
    elif tile_name == "cow_side":
        _noise_fill(px, rng, (66, 48, 30), 8)
        _blobs(px, rng, [(222, 218, 210)], 4, 3)
    elif tile_name == "cow_face":
        _noise_fill(px, rng, (66, 48, 30), 8)
        px[3, 6] = px[12, 6] = (16, 16, 16, 255)
        for y in range(9, 14):
            for x in range(4, 12):
                px[x, y] = _rgb((222, 218, 210), int(rng.randint(-5, 6)))
        px[6, 11] = px[9, 11] = (60, 44, 40, 255)
        px[0, 3] = px[0, 4] = px[15, 3] = px[15, 4] = (214, 208, 190, 255)
    elif tile_name == "sheep_side":
        _noise_fill(px, rng, (227, 227, 227), 7)
        for _ in range(12):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = (200, 200, 200, 255)
    elif tile_name == "sheep_face":
        _noise_fill(px, rng, (214, 177, 164), 6)
        for y in range(4):
            for x in range(16):
                px[x, y] = _rgb((227, 227, 227), int(rng.randint(-6, 7)))
        px[3, 7] = px[12, 7] = (20, 20, 20, 255)
    elif tile_name == "zombie_head":
        _noise_fill(px, rng, (58, 118, 62), 8)
        for y in (6, 7):
            for x in (3, 4, 11, 12):
                px[x, y] = (18, 32, 18, 255)
        px[4, 7] = px[12, 7] = (10, 14, 10, 255)
        for y in range(10, 13):
            for x in range(5, 10):
                px[x, y] = (40, 78, 42, 255)
        for x in range(5, 10, 2):
            px[x, 11] = (24, 48, 26, 255)
    elif tile_name == "zombie_body":
        _noise_fill(px, rng, (0, 148, 148), 8)
        for y in range(12, 16):
            for x in range(16):
                px[x, y] = _rgb((0, 120, 122), int(rng.randint(-5, 6)))
    elif tile_name == "zombie_legs":
        _noise_fill(px, rng, (52, 52, 148), 8)
        for y in range(13, 16):
            for x in range(16):
                px[x, y] = (36, 36, 96, 255)
    elif tile_name == "zombie_arm":
        _noise_fill(px, rng, (58, 118, 62), 8)
    elif tile_name == "skeleton_face":
        _noise_fill(px, rng, (198, 198, 198), 6)
        for y in (6, 7):
            for x in (3, 4, 11, 12):
                px[x, y] = (24, 24, 24, 255)
        px[7, 9] = px[8, 9] = px[7, 10] = px[8, 10] = (60, 60, 60, 255)
        for x in range(4, 12):
            px[x, 12] = (70, 70, 70, 255)
        for x in range(4, 12, 2):
            px[x, 11] = px[x, 13] = (70, 70, 70, 255)
    elif tile_name == "skeleton_body":
        _noise_fill(px, rng, (198, 198, 198), 6)
        for y in (4, 6, 8, 10):
            for x in range(2, 14):
                px[x, y] = (120, 120, 120, 255)
        for y in range(2, 14):
            px[7, y] = px[8, y] = (150, 150, 150, 255)
    elif tile_name == "creeper_face":
        _noise_fill(px, rng, (58, 168, 58), 12)
        for y in range(4, 7):
            for x in list(range(3, 6)) + list(range(10, 13)):
                px[x, y] = (10, 10, 10, 255)
        for y in range(7, 11):
            for x in range(6, 10):
                px[x, y] = (10, 10, 10, 255)
        for y in range(9, 13):
            for x in list(range(4, 6)) + list(range(10, 12)):
                px[x, y] = (10, 10, 10, 255)
    elif tile_name == "creeper_skin":
        _noise_fill(px, rng, (58, 168, 58), 16)
        for _ in range(18):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((30, 120, 30), int(rng.randint(-8, 9)))
        for _ in range(12):
            x, y = int(rng.randint(0, 16)), int(rng.randint(0, 16))
            px[x, y] = _rgb((110, 220, 110), int(rng.randint(-8, 9)))

    return img


def generate_atlas_image() -> Image.Image:
    """Create the full 256x256 RGBA block texture atlas."""
    atlas_w = ATLAS_COLS * TILE_PIXEL_SIZE
    atlas_h = ATLAS_ROWS * TILE_PIXEL_SIZE
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (255, 0, 255, 255))
    for tile_name, (col, row) in TILE_COORDS.items():
        tile_img = _generate_tile_image(tile_name)
        atlas.paste(tile_img, (col * TILE_PIXEL_SIZE, row * TILE_PIXEL_SIZE))
    return atlas


# ---------------------------------------------------------------------------
# GUI widget sheet (Minecraft-style container widgets)
# ---------------------------------------------------------------------------

GUI_RECTS: Dict[str, Tuple[int, int, int, int]] = {
    "slot": (0, 0, 18, 18),
    "slot_hover": (26, 36, 18, 18),
    "hotbar": (20, 0, 182, 22),
    "select": (0, 24, 24, 24),
    "heart_full": (26, 24, 9, 9),
    "heart_half": (36, 24, 9, 9),
    "heart_empty": (46, 24, 9, 9),
    "hunger_full": (56, 24, 9, 9),
    "hunger_half": (66, 24, 9, 9),
    "hunger_empty": (76, 24, 9, 9),
    "xp_empty": (0, 50, 182, 5),
    "xp_full": (0, 56, 182, 5),
    "crosshair": (0, 64, 15, 15),
    "button": (0, 84, 200, 20),
    "button_hover": (0, 106, 200, 20),
    "flame": (208, 0, 14, 14),
    "flame_empty": (208, 16, 14, 14),
    "arrow": (224, 0, 22, 9),
    "arrow_empty": (224, 12, 22, 9),
}


def _draw_gui_sheet() -> Image.Image:
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    px = img.load()

    def rect(x0, y0, x1, y1, c):
        for y in range(y0, y1):
            for x in range(x0, x1):
                px[x, y] = c

    # --- sunken slot 18x18 ---
    x0, y0 = 0, 0
    rect(x0, y0, x0 + 18, y0 + 18, (139, 139, 139, 255))
    for i in range(18):
        px[x0 + i, y0] = px[x0, y0 + i] = (55, 55, 55, 255)
        px[x0 + i, y0 + 17] = px[x0 + 17, y0 + i] = (255, 255, 255, 255)
        px[x0 + i, y0 + 1] = (110, 110, 110, 255) if i > 0 else (55, 55, 55, 255)
        px[x0 + 1, y0 + i] = (110, 110, 110, 255) if i > 0 else (55, 55, 55, 255)
        px[x0 + i, y0 + 16] = (168, 168, 168, 255)
        px[x0 + 16, y0 + i] = (168, 168, 168, 255)

    # --- slot hover highlight ---
    x0, y0 = 26, 36
    for i in range(18):
        px[x0 + i, y0] = px[x0, y0 + i] = px[x0 + i, y0 + 17] = px[x0 + 17, y0 + i] = (255, 255, 255, 110)

    # --- hotbar 182x22 ---
    x0, y0 = 20, 0
    rect(x0, y0, x0 + 182, y0 + 22, (139, 139, 139, 255))
    for i in range(182):
        px[x0 + i, y0] = px[x0 + i, y0 + 21] = (30, 30, 30, 255)
    for i in range(22):
        px[x0, y0 + i] = px[x0 + 181, y0 + i] = (30, 30, 30, 255)
    for i in range(1, 181):
        px[x0 + i, y0 + 1] = (200, 200, 200, 255)
        px[x0 + i, y0 + 20] = (90, 90, 90, 255)
    for s in range(9):
        sx = x0 + 1 + s * 20
        for i in range(20):
            px[sx + i, y0 + 1] = px[sx, y0 + 1 + i] = (55, 55, 55, 255) if i > 0 else (55, 55, 55, 255)
            px[sx + i, y0 + 20] = px[sx + 19, y0 + 1 + i] = (255, 255, 255, 255)
        rect(sx + 1, y0 + 2, sx + 19, y0 + 20, (139, 139, 139, 255))
        for i in range(1, 19):
            px[sx + i, y0 + 2] = (110, 110, 110, 255)
            px[sx + 1, y0 + 1 + i] = (110, 110, 110, 255)

    # --- selection highlight 24x24 ---
    x0, y0 = 0, 24
    for i in range(24):
        for t in (0, 1):
            px[x0 + i, y0 + t] = px[x0 + i, y0 + 23 - t] = (255, 255, 255, 255)
            px[x0 + t, y0 + i] = px[x0 + 23 - t, y0 + i] = (255, 255, 255, 255)

    # --- hearts / hunger 9x9 ---
    heart_shape = [
        ".XX...XX.",
        "XFFX.XFFX",
        "XFFFFFFFX",
        "XFFFFFFFX",
        ".XFFFFFX.",
        "..XFFFX..",
        "...XFX...",
        "....X....",
        ".........",
    ]
    hunger_shape = [
        "...XXXX..",
        "..XFFFFX.",
        ".XFFFFFFX",
        ".XFFFFFFX",
        "..XFFFFX.",
        "...XFFX..",
        "..XWWX...",
        ".XWWX....",
        ".XWX.....",
    ]

    def draw_sprite(sx, sy, shape, cmap):
        for ry, row in enumerate(shape):
            for rx, ch in enumerate(row):
                if ch == ".":
                    continue
                c = cmap.get(ch)
                if c:
                    px[sx + rx, sy + ry] = c

    hx = {"X": (64, 0, 0, 255), "F": (255, 42, 42, 255)}
    draw_sprite(26, 24, heart_shape, hx)
    px[28, 25] = px[29, 25] = (255, 168, 168, 255)
    px[27, 26] = (255, 168, 168, 255)
    draw_sprite(36, 24, heart_shape, {"X": (64, 0, 0, 255), "F": (58, 4, 4, 255)})
    for ry, row in enumerate(heart_shape):
        for rx, ch in enumerate(row):
            if ch == "F" and rx <= 4:
                px[36 + rx, 24 + ry] = (255, 42, 42, 255)
    px[38, 25] = px[39, 25] = (255, 168, 168, 255)
    draw_sprite(46, 24, heart_shape, {"X": (40, 40, 40, 255), "F": (66, 8, 8, 255)})

    hg = {"X": (48, 24, 12, 255), "F": (198, 120, 62, 255), "W": (240, 240, 240, 255)}
    draw_sprite(56, 24, hunger_shape, hg)
    px[59, 25] = px[60, 25] = (230, 170, 110, 255)
    draw_sprite(66, 24, hunger_shape, {"X": (48, 24, 12, 255), "F": (52, 40, 30, 255), "W": (70, 70, 70, 255)})
    for ry, row in enumerate(hunger_shape):
        for rx, ch in enumerate(row):
            if ch == "F" and rx <= 4:
                px[66 + rx, 24 + ry] = (198, 120, 62, 255)
    draw_sprite(76, 24, hunger_shape, {"X": (36, 36, 36, 255), "F": (58, 52, 46, 255), "W": (66, 66, 66, 255)})

    # --- xp bar 182x5 ---
    for i in range(182):
        px[i, 50] = px[i, 54] = (0, 0, 0, 255)
        px[i, 51] = px[i, 53] = (64, 64, 64, 255)
        px[i, 52] = (46, 46, 46, 255)
        px[i, 56] = px[i, 60] = (0, 0, 0, 255)
        px[i, 57] = px[i, 59] = (86, 179, 42, 255)
        px[i, 58] = (128, 255, 32, 255)

    # --- crosshair 15x15 ---
    for i in range(3, 12):
        px[7, i] = (255, 255, 255, 235)
        px[i, 7] = (255, 255, 255, 235)

    # --- buttons 200x20 ---
    for (bx, by), fill_top, fill_bot, edge in (
        ((0, 84), (118, 118, 118), (96, 96, 96), (0, 0, 0)),
        ((0, 106), (140, 152, 178), (110, 122, 150), (10, 10, 10)),
    ):
        rect(bx, by, bx + 200, by + 20, (fill_top[0], fill_top[1], fill_top[2], 255))
        for y in range(by, by + 20):
            t = (y - by) / 19.0
            c = (
                _clamp(fill_top[0] + (fill_bot[0] - fill_top[0]) * t),
                _clamp(fill_top[1] + (fill_bot[1] - fill_top[1]) * t),
                _clamp(fill_top[2] + (fill_bot[2] - fill_top[2]) * t),
            )
            for x in range(bx, bx + 200):
                px[x, y] = (c[0], c[1], c[2], 255)
        for i in range(200):
            px[bx + i, by] = px[bx + i, by + 19] = (edge[0], edge[1], edge[2], 255)
        for i in range(200):
            px[bx + i, by + 1] = _shade(fill_top, 1.28) + (255,)
            px[bx + i, by + 18] = _shade(fill_bot, 0.72) + (255,)
        for i in range(20):
            px[bx, by + i] = px[bx + 199, by + i] = (edge[0], edge[1], edge[2], 255)
            px[bx + 1, by + i] = _shade(fill_top, 1.28) + (255,)
            px[bx + 198, by + i] = _shade(fill_bot, 0.72) + (255,)

    # --- furnace flame 14x14 (lit + empty) ---
    flame_shape = [
        "......XX......",
        ".....XFFX.....",
        ".....XFFX.....",
        "....XFFFX....",
        "....XFFFX....",
        "...XFFFFFX...",
        "...XFFFFFX...",
        "..XFFFFFFX..",
        "..XFFFFFFX..",
        "..XFFFFFFX..",
        "...XFFFFFX...",
        "....XFFFX....",
        ".....XXX.....",
        "..............",
    ]
    for ry, row in enumerate(flame_shape):
        for rx, ch in enumerate(row):
            if ch == "X":
                px[208 + rx, 0 + ry] = (120, 28, 0, 255)
                px[208 + rx, 16 + ry] = (40, 40, 40, 255)
            elif ch == "F":
                px[208 + rx, 0 + ry] = (255, 164, 28, 255)
                px[208 + rx, 16 + ry] = (60, 60, 60, 255)
    for ry in range(6, 12):
        for rx in range(6, 8):
            px[208 + rx, ry] = (255, 236, 120, 255)

    # --- furnace arrow 22x9 ---
    for ry in range(9):
        for rx in range(22):
            inside = False
            if 3 <= ry <= 5 and rx <= 13:
                inside = True
            if rx == 14 and (2 <= ry <= 6):
                inside = True
            if rx == 15 and (3 <= ry <= 5):
                inside = True
            if rx == 16 and (2 <= ry <= 6):
                inside = True
            if rx == 17 and (3 <= ry <= 5):
                inside = True
            if rx == 18 and (4 == ry):
                inside = True
            if inside:
                px[224 + rx, 0 + ry] = (235, 235, 235, 255)
                px[224 + rx, 12 + ry] = (60, 60, 60, 255)
    return img


def generate_container_image() -> Image.Image:
    """176x166 Minecraft-style raised container panel (inventory/crafting/furnace window)."""
    w, h = 176, 166
    img = Image.new("RGBA", (w, h), (198, 198, 198, 255))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (198, 198, 198, 255)
    for x in range(w):
        px[x, 0] = (255, 255, 255, 255)
        px[x, 1] = (232, 232, 232, 255)
        px[x, h - 1] = (85, 85, 85, 255)
        px[x, h - 2] = (120, 120, 120, 255)
    for y in range(h):
        px[0, y] = (255, 255, 255, 255)
        px[1, y] = (232, 232, 232, 255)
        px[w - 1, y] = (85, 85, 85, 255)
        px[w - 2, y] = (120, 120, 120, 255)
    return img


# ---------------------------------------------------------------------------
# Item icons (drawn at 16x16, saved at 32x32 nearest-neighbour)
# ---------------------------------------------------------------------------

_TOOL_MATERIALS = {
    "wooden": ((155, 117, 51),),
    "stone": ((150, 150, 150),),
    "iron": ((222, 222, 222),),
    "diamond": ((62, 222, 216),),
}


def _draw_tool_icon(img: Image.Image, kind: str, mat: Tuple[int, int, int]) -> None:
    px = img.load()
    M = mat
    D = _shade(M, 0.68)
    L = _shade(M, 1.25)
    H = (167, 131, 84)
    HD = (120, 92, 56)

    def P(x, y, c):
        if 0 <= x < 16 and 0 <= y < 16:
            px[x, y] = (c[0], c[1], c[2], 255)

    if kind == "pickaxe":
        # arched head across the top
        for x in range(2, 14):
            t = (x - 2) / 11.0
            y = int(4.6 - math.sin(t * math.pi) * 3.4)
            P(x, y, M)
            P(x, y + 1, D if x % 3 == 0 else M)
            P(x, y - 1, L) if y - 1 >= 0 else None
        P(2, 5, M)
        P(2, 6, D)
        P(13, 5, M)
        P(13, 6, D)
        for i in range(8):
            P(3 + i, 13 - i, H)
            P(4 + i, 13 - i, HD)
    elif kind == "axe":
        wedge = {1: (4, 8), 2: (3, 9), 3: (2, 9), 4: (2, 8), 5: (3, 7), 6: (4, 6)}
        for y, (xa, xb) in wedge.items():
            for x in range(xa, xb + 1):
                P(x, y, M)
        # light cutting edge (left/top) and dark outline (right/bottom)
        for y, (xa, xb) in wedge.items():
            P(xa, y, L)
            P(xb, y, D)
        for x in range(4, 9):
            P(x, 1, L)
        P(9, 2, D)
        P(8, 5, D)
        P(7, 6, D)
        P(5, 7, D)
        for i in range(7):
            P(6 + i, 7 + i, H)
            P(7 + i, 7 + i, HD)
    elif kind == "sword":
        for i in range(9):
            P(5 + i, 9 - i, M)
            P(6 + i, 9 - i, L if i < 7 else M)
            P(5 + i, 8 - i, D)
        P(14, 1, M)
        P(14, 0, L)
        # crossguard
        for i in range(5):
            P(3 + i, 7 + i, D)
            P(4 + i, 7 + i, M)
        # grip + pommel
        P(3, 11, H)
        P(2, 12, H)
        P(2, 13, HD)
        P(1, 13, H)
        P(1, 14, HD)


def _draw_food_icon(img: Image.Image, kind: str) -> None:
    draw = ImageDraw.Draw(img)
    px = img.load()
    if kind == "apple":
        draw.ellipse([4, 5, 12, 13], fill=(222, 42, 38), outline=(120, 16, 14))
        draw.ellipse([5, 6, 11, 12], fill=(235, 60, 52))
        px[6, 7] = (255, 140, 130, 255)
        px[7, 6] = (255, 140, 130, 255)
        px[8, 4] = (110, 76, 40, 255)
        px[8, 3] = (110, 76, 40, 255)
        px[9, 3] = (90, 160, 60, 255)
        px[10, 3] = (90, 160, 60, 255)
    elif kind in ("raw_pork", "cooked_pork"):
        meat = (232, 130, 122) if kind == "raw_pork" else (186, 108, 62)
        dark = (150, 70, 66) if kind == "raw_pork" else (110, 58, 30)
        draw.ellipse([3, 4, 12, 12], fill=meat, outline=dark)
        draw.ellipse([5, 6, 10, 10], fill=_shade(meat, 1.15))
        px[3, 11] = px[2, 12] = px[2, 11] = (240, 240, 240, 255)
        px[3, 12] = (210, 210, 210, 255)
    elif kind in ("raw_beef", "cooked_beef"):
        meat = (214, 62, 62) if kind == "raw_beef" else (128, 72, 40)
        dark = (140, 30, 30) if kind == "raw_beef" else (80, 42, 22)
        draw.rounded_rectangle([3, 4, 12, 12], radius=2, fill=meat, outline=dark)
        if kind == "raw_beef":
            px[5, 6] = px[8, 8] = px[6, 10] = (240, 180, 175, 255)
        else:
            px[5, 6] = px[8, 8] = px[6, 10] = (170, 106, 62, 255)
            draw.line([(4, 5), (11, 5)], fill=(96, 52, 26), width=1)
    elif kind == "rotten_flesh":
        draw.rounded_rectangle([3, 5, 12, 11], radius=2, fill=(146, 88, 62), outline=(80, 48, 30))
        px[5, 7] = px[9, 9] = (110, 130, 70, 255)
        px[7, 8] = (170, 110, 80, 255)
    elif kind in ("iron_ingot", "gold_ingot"):
        c = (222, 222, 222) if kind == "iron_ingot" else (250, 212, 62)
        d = _shade(c, 0.66)
        l = _shade(c, 1.2)
        draw.polygon([(4, 6), (12, 6), (13, 10), (3, 10)], fill=c, outline=d)
        draw.line([(4, 6), (12, 6)], fill=l, width=1)
    elif kind == "diamond":
        c = (78, 232, 232)
        draw.polygon([(6, 3), (10, 3), (13, 6), (8, 13), (3, 6)], fill=c, outline=(30, 150, 150))
        draw.polygon([(6, 4), (10, 4), (11, 6), (8, 10), (5, 6)], fill=(168, 255, 252))
    elif kind == "coal":
        draw.polygon([(4, 5), (9, 3), (13, 6), (11, 11), (5, 12), (3, 8)], fill=(42, 42, 46), outline=(20, 20, 22))
        px[6, 6] = px[9, 8] = (90, 90, 96, 255)
    elif kind == "bone":
        draw.line([(5, 11), (11, 5)], fill=(238, 236, 226), width=2)
        for cx, cy in ((4, 11), (5, 12), (11, 4), (12, 5)):
            px[cx, cy] = (238, 236, 226, 255)
        px[3, 12] = px[12, 3] = (200, 198, 188, 255)
    elif kind == "stick":
        draw.line([(4, 12), (11, 4)], fill=(167, 131, 84), width=2)
        px[5, 12] = px[12, 4] = (120, 92, 56, 255)
    elif kind == "gunpowder":
        draw.rounded_rectangle([4, 7, 12, 12], radius=2, fill=(110, 110, 110), outline=(70, 70, 70))
        for x, y in ((5, 6), (8, 5), (11, 6), (6, 9), (9, 10)):
            px[x, y] = (150, 150, 150, 255)
    elif kind == "torch":
        draw.rectangle([7, 6, 8, 14], fill=(130, 102, 64))
        draw.rectangle([6, 3, 9, 6], fill=(255, 164, 44))
        draw.rectangle([7, 2, 8, 5], fill=(255, 224, 120))
        px[7, 1] = px[8, 1] = (255, 244, 184, 255)
    elif kind == "glasspane":
        draw.rectangle([4, 2, 11, 13], outline=(208, 240, 244))
        px[4, 2] = px[11, 2] = px[4, 13] = px[11, 13] = (255, 255, 255, 255)
        for i in range(4):
            px[6 + i, 9 - i] = (255, 255, 255, 160)
        for i in range(3):
            px[8 + i, 5 - i] = (255, 255, 255, 130)


def _iso_block_icon(img: Image.Image, side_tile: str, top_tile: str) -> None:
    """Compose a Minecraft-style isometric block preview from two atlas tiles."""
    top = _generate_tile_image(top_tile)
    side = _generate_tile_image(side_tile)

    def affine_face(tile: Image.Image, ox: float, oy: float, ux: float, uy: float, vx: float, vy: float, shade_f: float) -> Image.Image:
        # dest = o + (s/16)*u + (t/16)*v  ->  invert for PIL (source = A*dest + b)
        import numpy as _np
        M = _np.array([[ux / 16.0, vx / 16.0], [uy / 16.0, vy / 16.0]])
        Minv = _np.linalg.inv(M)
        t = _np.array([ox, oy])
        a, b = Minv[0, 0], Minv[0, 1]
        d, e = Minv[1, 0], Minv[1, 1]
        c, f = -(Minv @ t)
        out = tile.convert("RGBA").transform((16, 16), Image.AFFINE, (a, b, c, d, e, f), resample=Image.Resampling.NEAREST)
        if shade_f != 1.0:
            data = out.getdata()
            out.putdata([(_clamp(r * shade_f), _clamp(g * shade_f), _clamp(bl * shade_f), al) for (r, g, bl, al) in data])
        return out

    faces = [
        affine_face(top, 8, 0.5, 7, 3.5, -7, 3.5, 1.0),
        affine_face(side, 1, 4, 7, 4, 0, 7.5, 0.80),
        affine_face(side, 8, 8, 7, -4, 0, 7.5, 0.62),
    ]
    for f in faces:
        img.paste(f, (0, 0), f)


def generate_item_icon(item_key: str) -> Image.Image:
    """Create a 32x32 RGBA pixel-art icon for an inventory item, block, tool, or food."""
    item = ITEMS.get(item_key)
    small = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    if item is None:
        draw = ImageDraw.Draw(small)
        draw.rectangle([4, 4, 11, 11], fill=(180, 180, 180, 255))
        return small.resize((32, 32), Image.Resampling.NEAREST)

    if item_key in ("torch", "glass"):
        # Transparent tiles do not isometric-project well: draw dedicated 2D icons
        _draw_food_icon(small, "torch" if item_key == "torch" else "glasspane")
        return small.resize((32, 32), Image.Resampling.NEAREST)

    if item.category == "block" and item_key in BLOCKS_BY_KEY:
        bdef = BLOCKS_BY_KEY[item_key]
        side_tile = bdef.faces.get("north", bdef.faces.get("side", "stone"))
        top_tile = bdef.faces.get("top", side_tile)
        _iso_block_icon(small, side_tile, top_tile)
        return small.resize((32, 32), Image.Resampling.NEAREST)

    if item.tool_type in ("pickaxe", "axe", "sword"):
        mat_key = item_key.split("_")[0]
        mat = _TOOL_MATERIALS.get(mat_key, ((200, 200, 200),))[0]
        _draw_tool_icon(small, item.tool_type, mat)
        return small.resize((32, 32), Image.Resampling.NEAREST)

    _draw_food_icon(small, item.key)
    return small.resize((32, 32), Image.Resampling.NEAREST)


# ---------------------------------------------------------------------------
# Sounds
# ---------------------------------------------------------------------------


def _write_wav(filepath: Path, samples: np.ndarray, sample_rate: int = 22050) -> None:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(filepath), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def generate_sound_files() -> None:
    """Generate procedural WAV sound effects in assets/sounds/."""
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    sr = 22050
    rng = np.random.RandomState(42)

    t = np.linspace(0, 0.14, int(sr * 0.14), endpoint=False)
    env = np.exp(-t * 22)
    dig = (rng.uniform(-0.7, 0.7, len(t)) + 0.3 * np.sin(2 * np.pi * 140 * t)) * env
    _write_wav(SOUNDS_DIR / "dig.wav", dig * 0.5, sr)

    t = np.linspace(0, 0.12, int(sr * 0.12), endpoint=False)
    env = np.exp(-t * 28)
    place = (0.6 * np.sin(2 * np.pi * 110 * t) + 0.4 * rng.uniform(-0.5, 0.5, len(t))) * env
    _write_wav(SOUNDS_DIR / "place.wav", place * 0.55, sr)

    t = np.linspace(0, 0.08, int(sr * 0.08), endpoint=False)
    env = np.exp(-t * 35)
    step = rng.uniform(-0.4, 0.4, len(t)) * env
    _write_wav(SOUNDS_DIR / "step.wav", step * 0.35, sr)

    t = np.linspace(0, 0.20, int(sr * 0.20), endpoint=False)
    env = np.exp(-t * 14)
    hurt = (0.7 * np.sin(2 * np.pi * (220 - 600 * t) * t) + 0.3 * rng.uniform(-0.5, 0.5, len(t))) * env
    _write_wav(SOUNDS_DIR / "hurt.wav", hurt * 0.6, sr)

    t = np.linspace(0, 0.12, int(sr * 0.12), endpoint=False)
    env = np.sin(np.pi * t / 0.12)
    swing = rng.uniform(-0.5, 0.5, len(t)) * env * 0.4
    _write_wav(SOUNDS_DIR / "swing.wav", swing, sr)

    t = np.linspace(0, 0.18, int(sr * 0.18), endpoint=False)
    env = np.abs(np.sin(2 * np.pi * 8 * t)) * np.exp(-t * 8)
    eat = rng.uniform(-0.6, 0.6, len(t)) * env * 0.45
    _write_wav(SOUNDS_DIR / "eat.wav", eat * 0.45, sr)

    t = np.linspace(0, 0.22, int(sr * 0.22), endpoint=False)
    env = np.exp(-t * 12)
    craft = (0.5 * np.sin(2 * np.pi * 523.25 * t) + 0.5 * np.sin(2 * np.pi * 659.25 * t)) * env * 0.45
    _write_wav(SOUNDS_DIR / "craft.wav", craft, sr)

    t = np.linspace(0, 0.25, int(sr * 0.25), endpoint=False)
    env = np.exp(-t * 10)
    splash = rng.uniform(-0.6, 0.6, len(t)) * env * 0.4
    _write_wav(SOUNDS_DIR / "splash.wav", splash, sr)

    # item pickup pop
    t = np.linspace(0, 0.10, int(sr * 0.10), endpoint=False)
    freq = 620.0 + 500.0 * t / 0.10
    pop = np.sin(2 * np.pi * freq * t) * np.exp(-t * 26) * 0.5
    _write_wav(SOUNDS_DIR / "pop.wav", pop, sr)

    # creeper fuse hiss
    t = np.linspace(0, 1.1, int(sr * 1.1), endpoint=False)
    hiss = rng.uniform(-0.5, 0.5, len(t)) * (0.25 + 0.55 * (t / 1.1))
    _write_wav(SOUNDS_DIR / "hiss.wav", hiss * 0.5, sr)

    # explosion
    t = np.linspace(0, 0.9, int(sr * 0.9), endpoint=False)
    boom = rng.uniform(-1.0, 1.0, len(t)) * np.exp(-t * 5.0)
    boom += 0.6 * np.sin(2 * np.pi * 55 * t) * np.exp(-t * 7.0)
    _write_wav(SOUNDS_DIR / "explode.wav", boom * 0.7, sr)

    # level-up chime
    t = np.linspace(0, 0.5, int(sr * 0.5), endpoint=False)
    lvl = np.zeros_like(t)
    for i, f0 in enumerate((523.25, 659.25, 783.99, 1046.5)):
        t0 = i * 0.09
        m = t >= t0
        lvl[m] += 0.35 * np.sin(2 * np.pi * f0 * (t[m] - t0)) * np.exp(-(t[m] - t0) * 9)
    _write_wav(SOUNDS_DIR / "levelup.wav", lvl * 0.5, sr)


def generate_model_files() -> None:
    """Generate simple Wavefront OBJ models in assets/models/."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    cube_obj = """# Unit voxel cube
v 0.0 0.0 0.0
v 1.0 0.0 0.0
v 1.0 1.0 0.0
v 0.0 1.0 0.0
v 0.0 0.0 1.0
v 1.0 0.0 1.0
v 1.0 1.0 1.0
v 0.0 1.0 1.0
f 1 2 3 4
f 5 8 7 6
f 1 5 6 2
f 2 6 7 3
f 3 7 8 4
f 5 1 4 8
"""
    (MODELS_DIR / "cube_block.obj").write_text(cube_obj, encoding="utf-8")


def ensure_all_assets() -> None:
    """Ensure all procedural textures, icons, sounds, and models exist on disk."""
    try:
        TEXTURES_DIR.mkdir(parents=True, exist_ok=True)
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        MODELS_DIR.mkdir(parents=True, exist_ok=True)

        atlas_path = TEXTURES_DIR / "atlas.png"
        if not atlas_path.exists():
            generate_atlas_image().save(atlas_path)
        gui_path = TEXTURES_DIR / "gui.png"
        if not gui_path.exists():
            _draw_gui_sheet().save(gui_path)
        container_path = TEXTURES_DIR / "container.png"
        if not container_path.exists():
            generate_container_image().save(container_path)

        for item_key in ITEMS:
            icon_path = ICONS_DIR / f"{item_key}.png"
            if not icon_path.exists():
                generate_item_icon(item_key).save(icon_path)

        if not (SOUNDS_DIR / "dig.wav").exists():
            generate_sound_files()
        if not (MODELS_DIR / "cube_block.obj").exists():
            generate_model_files()
    except Exception as exc:
        print(f"[Assets] Warning while writing asset files: {exc}")


# ---------------------------------------------------------------------------
# Runtime texture loaders (cached Ursina Texture objects)
# ---------------------------------------------------------------------------

_CACHED_ATLAS_TEX = None
_CACHED_GUI_TEX: Dict[str, object] = {}
_CACHED_ICON_TEX: Dict[str, object] = {}
_CACHED_CONTAINER_TEX = None


def _tex_from_image(img: Image.Image):
    from ursina import Texture
    tex = Texture(img)
    tex.filtering = "nearest"
    return tex


def get_atlas_texture():
    global _CACHED_ATLAS_TEX
    if _CACHED_ATLAS_TEX is not None:
        return _CACHED_ATLAS_TEX
    atlas_path = TEXTURES_DIR / "atlas.png"
    try:
        img = Image.open(atlas_path).convert("RGBA") if atlas_path.exists() else generate_atlas_image()
    except Exception:
        img = generate_atlas_image()
    _CACHED_ATLAS_TEX = _tex_from_image(img)
    return _CACHED_ATLAS_TEX


def get_gui_texture(widget: str):
    """Return a cached Ursina Texture for a named GUI widget sprite."""
    if widget in _CACHED_GUI_TEX:
        return _CACHED_GUI_TEX[widget]
    gui_path = TEXTURES_DIR / "gui.png"
    try:
        if gui_path.exists():
            sheet = Image.open(gui_path).convert("RGBA")
        else:
            sheet = _draw_gui_sheet()
            sheet.save(gui_path)
    except Exception:
        sheet = _draw_gui_sheet()
    x, y, w, h = GUI_RECTS[widget]
    crop = sheet.crop((x, y, x + w, y + h))
    tex = _tex_from_image(crop)
    _CACHED_GUI_TEX[widget] = tex
    return tex


def get_container_texture():
    global _CACHED_CONTAINER_TEX
    if _CACHED_CONTAINER_TEX is not None:
        return _CACHED_CONTAINER_TEX
    path = TEXTURES_DIR / "container.png"
    try:
        img = Image.open(path).convert("RGBA") if path.exists() else generate_container_image()
    except Exception:
        img = generate_container_image()
    _CACHED_CONTAINER_TEX = _tex_from_image(img)
    return _CACHED_CONTAINER_TEX


def get_item_icon_texture(item_key: Optional[str]):
    if not item_key:
        return None
    if item_key in _CACHED_ICON_TEX:
        return _CACHED_ICON_TEX[item_key]
    icon_path = ICONS_DIR / f"{item_key}.png"
    try:
        img = Image.open(icon_path).convert("RGBA") if icon_path.exists() else generate_item_icon(item_key)
    except Exception:
        img = generate_item_icon(item_key)
    tex = _tex_from_image(img)
    _CACHED_ICON_TEX[item_key] = tex
    return tex


def play_game_sound(name: str, settings=None) -> None:
    """Play a game sound effect safely if sound effects are enabled and audio is available."""
    if settings is not None:
        if not getattr(settings, "sound_effects", True):
            return
        vol = float(getattr(settings, "volume", 0.7))
        if vol <= 0.01:
            return
    else:
        vol = 0.7
    try:
        from ursina import Audio, application
        if hasattr(application, "base") and application.base is not None:
            am = getattr(application.base, "sfxManagerList", None)
            if not am:
                return
        wav_path = SOUNDS_DIR / f"{name}.wav"
        if wav_path.exists():
            Audio(f"assets/sounds/{name}.wav", volume=vol, autoplay=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Textured box helper (per-face atlas UVs) used by mobs & the player viewmodel
# ---------------------------------------------------------------------------

_FACE_SHADES = {"top": 1.0, "bottom": 0.55, "north": 0.86, "south": 0.82, "east": 0.74, "west": 0.70}


def box_mesh_data(tiles: Dict[str, str], size: Tuple[float, float, float] = (1.0, 1.0, 1.0)):
    """
    Build (vertices, triangles, uvs, colors) for a centered box whose six faces
    sample individual tiles from the block atlas.
    Face keys: top, bottom, north(+Z), south(-Z), east(+X), west(-X).
    """
    from game.blocks import get_tile_uvs

    sx, sy, sz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    verts, tris, uvs, cols = [], [], [], []

    def add_quad(v0, v1, v2, v3, tile_name, face):
        from game.blocks import TILE_COORDS
        col, row = TILE_COORDS.get(tile_name, (3, 0))
        uv4 = get_tile_uvs(col, row)
        base = len(verts)
        verts.extend((v0, v1, v2, v3))
        tris.extend((base, base + 1, base + 2, base, base + 2, base + 3))
        uvs.extend(uv4)
        s = _FACE_SHADES.get(face, 1.0)
        from ursina import color as ucolor
        c = ucolor.rgb(s, s, s)
        cols.extend((c, c, c, c))

    default = next(iter(tiles.values()), "stone")
    add_quad((-sx, sy, -sz), (sx, sy, -sz), (sx, sy, sz), (-sx, sy, sz), tiles.get("top", default), "top")
    add_quad((-sx, -sy, sz), (sx, -sy, sz), (sx, -sy, -sz), (-sx, -sy, -sz), tiles.get("bottom", default), "bottom")
    add_quad((sx, -sy, sz), (-sx, -sy, sz), (-sx, sy, sz), (sx, sy, sz), tiles.get("north", default), "north")
    add_quad((-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz), tiles.get("south", default), "south")
    add_quad((sx, -sy, -sz), (sx, -sy, sz), (sx, sy, sz), (sx, sy, -sz), tiles.get("east", default), "east")
    add_quad((-sx, -sy, sz), (-sx, -sy, -sz), (-sx, sy, -sz), (-sx, sy, sz), tiles.get("west", default), "west")
    return verts, tris, uvs, cols


def make_textured_box(parent=None, size=(1.0, 1.0, 1.0), tiles=None, position=(0, 0, 0), rotation=(0, 0, 0)):
    """Create an Ursina Entity box with per-face atlas textures (Minecraft model parts)."""
    from ursina import Entity, Mesh

    verts, tris, uvs, cols = box_mesh_data(tiles or {}, size)
    mesh = Mesh(vertices=verts, triangles=tris, uvs=uvs, colors=cols, static=True)
    ent = Entity(parent=parent, model=mesh, texture=get_atlas_texture(), position=position, rotation=rotation, double_sided=True)
    return ent
