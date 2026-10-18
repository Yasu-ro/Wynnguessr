"""Draw the Survival potions: static/potions.png, one 12x12 bottle per effect,
in the order of POTIONS below, coloured like Minecraft's effects;
static/buckets.png, the milk bucket, then the same bucket empty once drunk;
static/emerald.png, Wynncraft's money (Survival with friends).
(The throw animation, static/potion-throw.gif, is Yasuro's: not drawn here;
its timings are in survival.js.) Run: python3 tools/potions.py"""
import os
from PIL import Image

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

# a bucket seen from a little above, like Minecraft's: the handle, the milk
# (or the dark inside, M -> i), the iron
BUCKET = """
...oooooo...
..o......o..
.oooooooooo.
.oMMMMMMMMo.
.oMMMMMMMmo.
.ohSSSSSSdo.
..oSssssdo..
..oSssssdo..
..oSsssddo..
...oSsddo...
...oooooo...
............
"""

# a cut gem, lit from the top left
EMERALD = """
.....oo.....
....oLLo....
...oLhLMo...
..oLhLLMMo..
.oLhLLLMMdo.
.oLLLLMMMdo.
.oLLLMMMddo.
.oMLMMMMddo.
..oMMMMddo..
...oMMddo...
....oddo....
.....oo.....
"""

def shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)

def draw(pattern, ink):
    img = Image.new('RGBA', (12, 12), (0, 0, 0, 0))
    for y, row in enumerate(pattern.strip('\n').split('\n')):
        for x, ch in enumerate(row):
            if ink[ch]:
                img.putpixel((x, y), ink[ch] + (255,))
    return img

def bottle(colour):
    return draw(BOTTLE, {'.': None, 'o': (24, 14, 18), 'C': (140, 98, 58), 'G': (214, 228, 236), 'w': (255, 255, 255),
                         'L': colour, 'd': shade(colour, .65)})

def bucket(milk):
    iron = {'.': None, 'o': (24, 14, 18), 'h': (236, 236, 240), 'S': (198, 198, 206), 's': (150, 150, 160), 'd': (98, 98, 110)}
    inside = {'M': (246, 244, 236), 'm': (214, 210, 198)} if milk else {'M': (62, 58, 64), 'm': (44, 40, 46)}
    return draw(BUCKET, {**iron, **inside})

static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
sheet = Image.new('RGBA', (12 * len(POTIONS), 12), (0, 0, 0, 0))
for i, name in enumerate(POTIONS):
    sheet.alpha_composite(bottle(COLOUR[name]), (12 * i, 0))
sheet.save(os.path.join(static, 'potions.png'))
buckets = Image.new('RGBA', (24, 12), (0, 0, 0, 0))
buckets.alpha_composite(bucket(True), (0, 0))
buckets.alpha_composite(bucket(False), (12, 0))
buckets.save(os.path.join(static, 'buckets.png'))
draw(EMERALD, {'.': None, 'o': (24, 14, 18), 'h': (214, 255, 222), 'L': (65, 222, 120), 'M': (23, 176, 72),
               'd': (12, 122, 52)}).save(os.path.join(static, 'emerald.png'))

print('potions.png, buckets.png, emerald.png')
