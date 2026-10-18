"""Cut the map (static/map-2026.webp, one pixel per block, 4608 x 6144) into
256 px tiles for Leaflet: static/map-2026/<zoom>/<x>_<y>.webp, zoom 0 at one
pixel per block, -1 to -3 shrunk by 2, 4, 8. A page then loads only what it
shows (a few hundred kB) instead of the whole 8.7 MB image. The numbers
follow Leaflet's CRS.Simple: at zoom z a point (lat, lng) is at
(lng * 2^z, -lat * 2^z), and tile (x, y) covers 256 px from (256x, 256y).
The map's corners: lat 0 to 6144, lng -2560 to 2048 (BOUNDS in the pages).
Zoom 0 in lossless WebP: the map is pixel art, and a block must be aimed at
exactly; the smaller ones in WebP at 90 (shrunk, they have no exact pixel
left: lossless made zoom -1 8.2 MB, 90 makes it a fraction of that).
Run: python3 tools/map_tiles.py [zooms...] (all four by default; zoom 0 takes
some twenty minutes)"""
import math, os, shutil, sys
from PIL import Image

static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
TOP, LEFT = 6144, -2560
TILE = 256
src = Image.open(os.path.join(static, 'map-2026.webp')).convert('RGBA')
out = os.path.join(static, 'map-2026')
zooms = [int(z) for z in sys.argv[1:]] or [0, -1, -2, -3]
total = 0
for z in zooms:
    shutil.rmtree(os.path.join(out, str(z)), ignore_errors=True)
    s = 2 ** z
    img = src if z == 0 else src.resize((round(src.width * s), round(src.height * s)), Image.Resampling.LANCZOS)
    x0, y0 = LEFT * s, -TOP * s           # where the image's top left corner falls, in pixels of zoom z
    os.makedirs(os.path.join(out, str(z)))
    for tx in range(math.floor(x0 / TILE), math.ceil((x0 + img.width) / TILE)):
        for ty in range(math.floor(y0 / TILE), math.ceil((y0 + img.height) / TILE)):
            tile = Image.new('RGBA', (TILE, TILE), (0, 0, 0, 0))
            tile.paste(img.crop((round(tx * TILE - x0), round(ty * TILE - y0), round(tx * TILE - x0) + TILE, round(ty * TILE - y0) + TILE)), (0, 0))
            path = os.path.join(out, str(z), f'{tx}_{ty}.webp')
            if z == 0:
                tile.save(path, 'WEBP', lossless=True, quality=100, method=6)
            else:
                tile.save(path, 'WEBP', quality=90, method=6)
            total += os.path.getsize(path)
    print(z, len(os.listdir(os.path.join(out, str(z)))), 'tiles')
print(round(total / 1e6, 1), 'MB in all')
