"""Draw the playing cards' pieces (Worlds, the Play menu):
- static/cards.png: the pips, 9x9 like the hearts, in a row: heart,
  Hardcore heart (both taken from hearts.png), pin, sword, crown, milk bucket,
  then the pin in four room colours (the Joker's);
- static/card-ranks.png: the ranks in a 5x7 pixel font, red then ink;
- static/felt.png: the card table's felt;
- static/card-back.png: one tile of the back, a red lattice;
- static/card-wear.webp: four ways a card wears, side by side, 2x the card's
  size (190x266): grime along the edges, strongest at the corners and
  uneven, a few chips where the coating went, a faint grain. Each card on a
  page takes one, so no two look handled the same.
Run: python3 tools/cards.py"""
import math
import os
import random
from PIL import Image

static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

def draw(pattern, ink):
    rows = pattern.strip('\n').split('\n')
    assert len(rows) == 9 and all(len(r) == 9 for r in rows), pattern
    img = Image.new('RGBA', (9, 9), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ink.get(ch):
                img.putpixel((x, y), ink[ch] + (255,))
    return img

# a map pin, lit top left like the hearts (a white dot reads as a cross
# at this size), shaded bottom right
PIN = """
..ooooo..
.owlPPPo.
owlPPPPdo
olPPPPPdo
oPPPPPPdo
.oPPPPdo.
..oPPdo..
...oPo...
....o....
"""
# a sword the way Minecraft shows one, point to the top right (point up,
# it read as a little cross)
SWORD = """
.......oo
......oLo
.....oLso
....oLso.
oo.oLso..
oGooso...
.oGGo....
.oHoGo...
oHo.oo...
"""
# a crown, two jewels
CROWN = """
.........
o...o...o
oo.oGo.oo
oGoGGGoGo
oGGGGGGgo
oGRGGGBgo
oGGGGGGgo
ooooooooo
.........
"""
# the milk bucket, smaller than the shop's
BUCKET = """
..ooooo..
.o.....o.
ooooooooo
oMMMMMMmo
ohSSSSSdo
.oSsssdo.
.oSsssdo.
..oSsdo..
..ooooo..
"""

OUTLINE = (24, 14, 18)
def pin(colour):
    shade = tuple(int(c * .72) for c in colour)
    light = tuple(int(c + (255 - c) * .45) for c in colour)
    return draw(PIN, {'o': OUTLINE, 'P': colour, 'd': shade, 'l': light, 'w': (255, 255, 255)})

hearts = Image.open(os.path.join(static, 'hearts.png')).convert('RGBA')
frames = [
    hearts.crop((0, 0, 9, 9)),                      # 0 heart
    hearts.crop((27, 0, 36, 9)),                    # 1 Hardcore heart
    pin((52, 58, 74)),                              # 2 pin: the cards' black suit
    draw(SWORD, {'o': OUTLINE, 'L': (226, 230, 236), 's': (150, 156, 168), 'G': (236, 186, 58),
                 'H': (120, 78, 44)}),             # 3 sword
    draw(CROWN, {'o': OUTLINE, 'G': (240, 196, 64), 'g': (196, 146, 34), 'R': (214, 40, 52),
                 'B': (58, 116, 220)}),            # 4 crown
    draw(BUCKET, {'o': OUTLINE, 'M': (246, 244, 236), 'm': (214, 210, 198), 'h': (196, 200, 206),
                  'S': (172, 176, 184), 's': (140, 144, 152), 'd': (104, 108, 116)}),   # 5 milk
    pin((230, 25, 75)), pin((255, 225, 25)), pin((67, 99, 216)), pin((60, 180, 75)),     # 6-9
]
sheet = Image.new('RGBA', (9 * len(frames), 9), (0, 0, 0, 0))
for i, f in enumerate(frames):
    sheet.alpha_composite(f, (9 * i, 0))
sheet.save(os.path.join(static, 'cards.png'))

# the ranks, a 5x7 pixel font of our own (the pips are pixel art: a printed
# font beside them looked flat): one row in the hearts' red, one in ink
GLYPHS = {
    'A': ".###.|#...#|#...#|#####|#...#|#...#|#...#",
    'K': "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#",
    'Q': ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#",
    'J': "..###|...#.|...#.|...#.|#..#.|#..#.|.##..",
    'O': ".###.|#...#|#...#|#...#|#...#|#...#|.###.",
    'E': "#####|#....|#....|####.|#....|#....|#####",
    'R': "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
    '0': ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",
    '1': "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
    '2': ".###.|#...#|....#|...#.|..#..|.#...|#####",
    '3': ".###.|#...#|....#|..##.|....#|#...#|.###.",
    '4': "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
    '5': "#####|#....|####.|....#|....#|#...#|.###.",
    '6': "..##.|.#...|#....|####.|#...#|#...#|.###.",
    '7': "#####|....#|...#.|..#..|.#...|.#...|.#...",
    '8': ".###.|#...#|#...#|.###.|#...#|#...#|.###.",
    '9': ".###.|#...#|#...#|.####|....#|...#.|.##..",
}
ranks = Image.new('RGBA', (5 * len(GLYPHS), 14), (0, 0, 0, 0))
for i, rows in enumerate(GLYPHS.values()):
    for y, row in enumerate(rows.split('|')):
        for x, ch in enumerate(row):
            if ch == '#':
                ranks.putpixel((5 * i + x, y), (184, 35, 42, 255))
                ranks.putpixel((5 * i + x, 7 + y), (43, 29, 27, 255))
ranks.save(os.path.join(static, 'card-ranks.png'))

# the felt of the card table: a dark green, each pixel a little off
rnd = random.Random(7)
felt = Image.new('RGB', (64, 64))
for y in range(64):
    for x in range(64):
        k = rnd.uniform(-.05, .05) + (-.07 if rnd.random() < .04 else 0)
        felt.putpixel((x, y), tuple(int(c * (1 + k)) for c in (46, 96, 62)))
felt.save(os.path.join(static, 'felt.png'))

# the back: a lattice, two reds, like the backs of old decks
tile = Image.new('RGB', (8, 8), (158, 40, 36))
for i in range(8):
    tile.putpixel((i, i), (196, 84, 72))
    tile.putpixel((i, 7 - i), (196, 84, 72))
tile.save(os.path.join(static, 'card-back.png'))

# wear, at 2x: 380 x 532, corners of radius 20 (the card's 10 px)
W, H, R = 380, 532, 20
GRIME = (92, 68, 46)

def edge_distance(x, y):
    dx, dy = min(x, W - 1 - x), min(y, H - 1 - y)
    if dx < R and dy < R:
        return R - math.hypot(R - dx, R - dy)
    return min(dx, dy)

def mottle(rnd, step):
    # a coarse random grid, smoothly interpolated: grime is never even
    gw, gh = W // step + 2, H // step + 2
    g = [[rnd.uniform(.45, 1.55) for _ in range(gw)] for _ in range(gh)]
    def at(x, y):
        fx, fy = x / step, y / step
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        tx, ty = tx * tx * (3 - 2 * tx), ty * ty * (3 - 2 * ty)
        top = g[iy][ix] * (1 - tx) + g[iy][ix + 1] * tx
        bottom = g[iy + 1][ix] * (1 - tx) + g[iy + 1][ix + 1] * tx
        return top * (1 - ty) + bottom * ty
    return at

def wear(seed):
    rnd = random.Random(seed)
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    px = img.load()
    spots = mottle(rnd, 46)
    # how much each corner was handled: the bottom ones, held in a hand, more
    corners = {(0, 0): rnd.uniform(.6, 1.1), (W - 1, 0): rnd.uniform(.6, 1.1),
               (0, H - 1): rnd.uniform(.9, 1.6), (W - 1, H - 1): rnd.uniform(.9, 1.6)}
    strength = rnd.uniform(.15, .21)
    for y in range(H):
        for x in range(W):
            d = edge_distance(x, y)
            if d < 0:
                continue
            near = max(k * math.exp(-math.hypot(x - cx, y - cy) / 34) for (cx, cy), k in corners.items())
            a = strength * math.exp(-d / 4.5) * (1 + 1.6 * near) * spots(x, y)
            # the grain: a little everywhere
            a += rnd.uniform(0, .022)
            px[x, y] = GRIME + (min(255, int(a * 255)),)
    # chips: the coating gone in a few places, close to the edges, mostly at corners
    for _ in range(rnd.randint(5, 9)):
        (cx, cy), _k = rnd.choice(list(corners.items()))
        t = rnd.uniform(0, 1) ** 2
        along = int(t * 90)
        x = min(max(cx + (along if cx == 0 else -along) * rnd.choice((0, 1)), 2), W - 3)
        y = min(max(cy + (along if cy == 0 else -along) * (x in (2, W - 3) or rnd.random() < .5), 2), H - 3)
        for _ in range(rnd.randint(3, 7)):
            sx, sy = x + rnd.randint(-2, 2), y + rnd.randint(-2, 2)
            if 0 <= sx < W and 0 <= sy < H and edge_distance(sx, sy) >= 0:
                px[sx, sy] = (255, 252, 244, rnd.randint(150, 210))
    return img

sheet = Image.new('RGBA', (W * 4, H), (0, 0, 0, 0))
for i in range(4):
    sheet.alpha_composite(wear(1000 + i), (W * i, 0))
sheet.save(os.path.join(static, 'card-wear.webp'), 'WEBP', quality = 82, alpha_quality = 80, method = 6)
print('cards.png, card-ranks.png, felt.png, card-back.png, card-wear.webp:', os.path.getsize(os.path.join(static, 'card-wear.webp')) // 1024, 'KB')
