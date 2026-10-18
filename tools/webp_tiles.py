"""Write next to every JPEG tile of the locations (and the home page's demo)
the same tile in WebP 90: about 30 % lighter, no visible difference (Yasuro
chose it on a side-by-side comparison, 2026-10-18). The JPEGs stay until the
site no longer asks for them. Resumes where it stopped (a WebP already there
is kept); 4 processes at the lowest priority, so the game servers do not
feel it. Run: python3 tools/webp_tiles.py [folder...] (default: every
location in static/tiles, and static/demo)"""
import os, sys, time
from multiprocessing import Pool
from PIL import Image

static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

def convert(jpg):
    webp = jpg[:-4] + '.webp'
    if os.path.exists(webp):
        return 0
    tmp = webp + '.tmp'
    Image.open(jpg).save(tmp, 'WEBP', quality=90, method=6)
    os.replace(tmp, webp)   # never half a file under the real name
    return 1

def jpgs(folder):
    for root, _, files in os.walk(folder):
        for f in files:
            if f.endswith('.jpg'):
                yield os.path.join(root, f)

if __name__ == '__main__':
    os.nice(19)
    tiles = os.path.realpath(os.path.join(static, 'tiles'))
    folders = sys.argv[1:] or [os.path.join(tiles, d) for d in sorted(os.listdir(tiles))] + [os.path.join(static, 'demo')]
    start, done = time.time(), 0
    with Pool(4) as pool:
        for i, folder in enumerate(folders, 1):
            done += sum(pool.map(convert, list(jpgs(folder)), chunksize=16))
            if i % 25 == 0 or i == len(folders):
                print(f'{i}/{len(folders)} folders, {done} tiles written, {(time.time() - start) / 60:.0f} min', flush=True)
