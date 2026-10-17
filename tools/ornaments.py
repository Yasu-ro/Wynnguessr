# Small drawings for the stylesheet, as CSS custom properties (data URIs):
# the cut facets of buttons, the nails of a sign, a row of cartoon stones.
import urllib.parse

def url(svg):
    return 'url("data:image/svg+xml,' + svg.replace('#', '%23') + '")'

NS = "xmlns='http://www.w3.org/2000/svg'"

# light sliver top-left, dark sliver bottom-right; works on any base colour
facet = (f"<svg {NS} viewBox='0 0 100 30' preserveAspectRatio='none'>"
         "<path d='M0 0H82L7 4.5 2.5 30H0Z' fill='#fff' fill-opacity='.24'/>"
         "<path d='M100 2.5 96.5 26.5 11 30H100Z' fill='#000' fill-opacity='.17'/></svg>")

# big buttons: the same, plus a light band across
facet_big = (f"<svg {NS} viewBox='0 0 160 50' preserveAspectRatio='none'>"
             "<path d='M0 0H160L9 5.5 4 50H0Z' fill='#fff' fill-opacity='.3'/>"
             "<path d='M57 50 66 0H83L74 50Z' fill='#fff' fill-opacity='.17'/>"
             "<path d='M160 4 155.5 46 22 50H160Z' fill='#000' fill-opacity='.13'/></svg>")

# a nail head in each corner of a sign
stud = (f"<svg {NS} viewBox='0 0 20 20'>"
        "<path d='M10 1.8 18.2 10 10 18.2 1.8 10Z' fill='#a9a69d' stroke='#3f2724' stroke-width='2.4' stroke-linejoin='round'/>"
        "<path d='M10 4.6 15.2 10H10Z' fill='#d6d3ca'/></svg>")

# a row of stones along the bottom of the home picture: hand-cut shapes,
# chipped corners, a lit top edge, a thick dark outline
import random
def stone(rnd, x0, x1, top, b=43):
    j = lambda: rnd.uniform(-1.4, 1.4)
    pts = [(x0 + 1 + j(), top + 5 + j()), (x0 + 6 + j(), top + j()), (x1 - 6 + j(), top + 1 + j()),
           (x1 - 1 + j(), top + 6 + j()), (x1 + j(), b - 4 + j()), (x1 - 4 + j(), b), (x0 + 4 + j(), b),
           (x0 + j(), b - 5 + j())]
    d = 'M' + ' '.join('%.1f %.1f' % p for p in pts) + 'Z'
    s = f"<path d='{d}' fill='#6b6a63'/>"
    s += (f"<path d='M{x0 + 5:.1f} {top + 4:.1f}L{x1 - 6:.1f} {top + 4.5:.1f} {x1 - 9:.1f} {top + 8.5:.1f} "
          f"{x0 + 7:.1f} {top + 9:.1f}Z' fill='#8c8b83'/>")
    s += f"<path d='M{x0 + 2:.1f} {b - 8:.1f}L{x1 - 2:.1f} {b - 9:.1f} {x1 - 3:.1f} {b - 1:.1f} {x0 + 3:.1f} {b - 1:.1f}Z' fill='#55544e'/>"
    s += f"<path d='{d}' fill='none' stroke='#141412' stroke-width='3' stroke-linejoin='round'/>"
    return s

rnd = random.Random(5)
bricks = (f"<svg {NS} viewBox='0 0 360 46'>"
          "<path d='M0 26H360V46H0Z' fill='#141412'/>"
          + stone(rnd, 2, 79, 11) + stone(rnd, 83, 134, 13) + stone(rnd, 138, 233, 10)
          + stone(rnd, 237, 300, 12) + stone(rnd, 304, 357, 11)
          + "</svg>")

for name, svg in (('facet', facet), ('facet-big', facet_big), ('stud', stud), ('bricks', bricks)):
    print(f'    --{name}: {url(svg)};')
