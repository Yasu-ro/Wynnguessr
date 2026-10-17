# Blob textures for the site background, drawn here (not taken from anywhere):
# a tile of soft irregular stones, a little lighter or darker than the base,
# wrapped at the edges so the tile repeats without seams.
import math, random, sys, urllib.parse

def blob(rnd, cx, cy, r):
    n = rnd.randint(7, 10)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n + rnd.uniform(-.25, .25)
        rr = r * rnd.uniform(.7, 1.15)
        pts.append((cx + rr * math.cos(a), cy + rr * .8 * math.sin(a)))
    return pts

def tile(seed, size, base, shades, count):
    rnd = random.Random(seed)
    shapes = []
    for _ in range(count):
        cx, cy, r = rnd.uniform(0, size), rnd.uniform(0, size), rnd.uniform(10, 34)
        fill = rnd.choice(shades)
        pts = blob(rnd, cx, cy, r)
        for dx in (-size, 0, size):
            for dy in (-size, 0, size):
                moved = [(x + dx, y + dy) for x, y in pts]
                if all(x < -2 or x > size + 2 for x, _ in moved) or all(y < -2 or y > size + 2 for _, y in moved):
                    continue
                d = 'M' + ' '.join('%.0f %.0f' % p for p in moved) + 'z'
                shapes.append("<path fill='%s' d='%s'/>" % (fill, d))
    return ("<svg xmlns='http://www.w3.org/2000/svg' width='%d' height='%d'><rect width='%d' height='%d' fill='%s'/>%s</svg>"
            % (size, size, size, size, base, ''.join(shapes)))

def url(svg):
    return 'url("data:image/svg+xml,' + svg.replace('#', '%23') + '")'

stone = tile(7, 260, '#1d1c19', ['#22211e', '#201f1b', '#1a1916'], 16)
dirt = tile(11, 260, '#1f1a12', ['#241e15', '#221c14', '#1c1710'], 16)
print('--tex-stone: ' + url(stone) + ';')
print('--tex-dirt: ' + url(dirt) + ';')
print(len(url(stone)), len(url(dirt)), file=sys.stderr)
