"""Draw the Survival potions: static/potions.png (one 12x12 bottle per effect,
in the order of POTIONS below, coloured like Minecraft's effects) and
static/potion-throw.gif, a TEMPORARY animation of a bottle thrown and
breaking, shown before the potion is revealed. Yasuro will draw the real
one: replace the gif with the same name (and set THROW_MS in survival.js to
its length). Run: python3 tools/potions.py"""
import os
from PIL import Image, ImageDraw

POTIONS = ['swiftness', 'mining_fatigue', 'wither', 'regeneration', 'nausea', 'darkness', 'blindness']
COLOUR = {   # Minecraft's effect colours, a little brighter where they were too dark to read
    'swiftness': (124, 175, 198), 'mining_fatigue': (110, 98, 40), 'wither': (92, 74, 68),
    'regeneration': (205, 92, 171), 'nausea': (125, 45, 110), 'darkness': (70, 66, 80), 'blindness': (45, 45, 55),
}
BOTTLE = """
....oooo....
....oCCo....
....oGGo....
...oGGGGo...
..oGLLLLGo..
.oGLLLLLLGo.
.oLwLLLLLLo.
.oLLLLLLLLo.
.oLLLLLLLdo.
..oLLLLLdo..
...oooooo...
............
"""

def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

def bottle(colour):
    ink = {'.': None, 'o': (24, 14, 18), 'C': (140, 98, 58), 'G': (214, 228, 236), 'w': (255, 255, 255),
           'L': colour, 'd': shade(colour, .65)}
    img = Image.new('RGBA', (12, 12), (0, 0, 0, 0))
    for y, row in enumerate(BOTTLE.strip('\n').split('\n')):
        for x, ch in enumerate(row):
            if ink[ch]:
                img.putpixel((x, y), ink[ch] + (255,))
    return img

static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
sheet = Image.new('RGBA', (12 * len(POTIONS), 12), (0, 0, 0, 0))
for i, name in enumerate(POTIONS):
    sheet.alpha_composite(bottle(COLOUR[name]), (12 * i, 0))
sheet.save(os.path.join(static, 'potions.png'))

# the temporary throw: the bottle flies up in an arc, spinning, then breaks
# into drops; 32 x 32 pixels, drawn big (x4) and sharp
glass = bottle((150, 150, 165))
frames = []
for t in range(8):
    f = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    x, y = 2 + t * 3, int(22 - 18 * (t / 7) * (2 - t / 7))
    f.alpha_composite(glass.rotate(-t * 40, resample = Image.NEAREST), (x, y))
    frames.append(f)
drops = [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, -1), (-1, 0), (1, 0), (0, 1)]
for t in range(1, 7):
    f = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(f)
    for k, (dx, dy) in enumerate(drops):
        r = t * 2 + k % 2
        px, py = 16 + dx * r, 8 + dy * r + t // 2
        colour = (220, 220, 235) if k % 3 else (255, 255, 255)
        if t < 6 or k % 2:   # they get smaller, then fewer (a GIF cannot fade them)
            d.rectangle([px, py, px + (1 if t < 4 else 0), py + (1 if t < 4 else 0)], fill = colour + (255,))
    frames.append(f)
big = [fr.resize((128, 128), Image.NEAREST) for fr in frames]
# a GIF has one transparent colour, and one palette for every frame (one
# palette per frame moved the transparent colour around: magenta drops)
keyed = []
for fr in big:
    p = Image.new('RGBA', fr.size, (255, 0, 255, 255))
    p.alpha_composite(fr)
    keyed.append(p.convert('RGB'))
strip = Image.new('RGB', (128 * len(keyed), 128))
for i, fr in enumerate(keyed):
    strip.paste(fr, (128 * i, 0))
palette = strip.quantize(colors = 64)
out = [fr.quantize(palette = palette) for fr in keyed]
key = out[0].getpixel((0, 0))
out[0].save(os.path.join(static, 'potion-throw.gif'), save_all = True, append_images = out[1:],
            duration = [70] * 8 + [80] * 6, transparency = key, disposal = 2)
print('potions.png, potion-throw.gif')
