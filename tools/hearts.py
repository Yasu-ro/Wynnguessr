"""Draw the Survival hearts into static/hearts.png: one row of 9x9 frames,
full, half, empty, then the same three for Hardcore. Drawn pixel by pixel
after a screenshot of the old Wynncraft hearts (bright red, a pink and white
glint top left, a dark outline; an empty heart is black inside). To retouch
a heart, change its grid below and run: python3 tools/hearts.py"""
import os
from PIL import Image

INK = {
    '.': None,
    'o': (24, 6, 8),        # outline
    'R': (231, 34, 42),     # red
    'r': (163, 19, 26),     # shade, bottom and right
    'p': (255, 140, 146),   # glint, pink
    'w': (255, 255, 255),   # glint, white
    'k': (16, 16, 18),      # inside of an empty heart
    'g': (70, 70, 74),      # outline of an empty heart
    'H': (196, 18, 26),     # Hardcore red, darker
    'h': (120, 8, 14),      # Hardcore shade
    'e': (255, 214, 214),   # Hardcore glints, one in each half
}

FULL = """
.oo...oo.
opwo.oRRo
owpRoRRRo
opRRRRRro
oRRRRRRro
.oRRRRro.
..oRRro..
...oro...
....o....
"""
EMPTY = """
.gg...gg.
gkkg.gkkg
gkkkgkkkg
gkkkkkkkg
gkkkkkkkg
.gkkkkkg.
..gkkkg..
...gkg...
....g....
"""
# Hardcore: horns on the outline and a glint in each half, darker red
HARD = """
o.o...o.o
oewo.oewo
oeHHoHHHo
oHHHHHHho
oHHHHHHho
.oHHHHho.
..oHHho..
...oho...
....o....
"""
HARD_EMPTY = """
g.g...g.g
gkkg.gkkg
gkkkgkkkg
gkkkkkkkg
gkkkkkkkg
.gkkkkkg.
..gkkkg..
...gkg...
....g....
"""

def grid(text):
    rows = [r for r in text.strip('\n').split('\n')]
    assert len(rows) == 9 and all(len(r) == 9 for r in rows), text
    return rows

def half(full, empty):
    # the left half filled (columns 0 to 4), the right half empty
    return [f[:5] + e[5:] for f, e in zip(grid(full), grid(empty))]

frames = [grid(FULL), half(FULL, EMPTY), grid(EMPTY), grid(HARD), half(HARD, HARD_EMPTY), grid(HARD_EMPTY)]
img = Image.new('RGBA', (9 * len(frames), 9), (0, 0, 0, 0))
for i, rows in enumerate(frames):
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if INK[ch]:
                img.putpixel((i * 9 + x, y), INK[ch] + (255,))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'hearts.png')
img.save(out)
print(out)
