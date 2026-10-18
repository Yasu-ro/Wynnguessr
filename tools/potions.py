"""Draw the Survival potions: static/potions.png, one 12x12 bottle per effect,
in the order of POTIONS below, coloured like Minecraft's effects. (The throw
animation, static/potion-throw.gif, is Yasuro's: not drawn here; its timings
are in survival.js.) Run: python3 tools/potions.py"""
import os
from PIL import Image

POTIONS = ['swiftness', 'mining_fatigue', 'wither', 'regeneration', 'nausea', 'darkness', 'blindness',
           'shaky', 'spin', 'tunnel', 'mirror']   # the last four: candidates to replace Nausea
COLOUR = {   # Minecraft's effect colours, a little brighter where they were too dark to read
    'swiftness': (124, 175, 198), 'mining_fatigue': (110, 98, 40), 'wither': (92, 74, 68),
    'regeneration': (205, 92, 171), 'nausea': (125, 45, 110), 'darkness': (70, 66, 80), 'blindness': (45, 45, 55),
    'shaky': (78, 147, 49), 'spin': (186, 150, 220), 'tunnel': (61, 61, 140), 'mirror': (196, 204, 214),
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

print('potions.png')
