# usage: solo.py <base_url> <prefix> [width] [height]
# a short solo game: guess screen, map grown, score screen, last screen
import sys, asyncio
from playwright.async_api import async_playwright
base, prefix = sys.argv[1].rstrip('/') + '/', sys.argv[2]
w = int(sys.argv[3]) if len(sys.argv) > 3 else 1440
h = int(sys.argv[4]) if len(sys.argv) > 4 else 900
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        ctx = await b.new_context(viewport={'width': w, 'height': h})
        pg = await ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        q = 'game?mode=classic&province=wynn&province=gavel&province=corkus&province=ocean&province=silent-expanse&rounds=3&time-limit-checkbox=on&time-limit=90'
        await pg.goto(base + q, wait_until='networkidle')
        await pg.wait_for_timeout(4000)
        await pg.screenshot(path=prefix + '-guess.png')
        box = await pg.locator('#map').bounding_box()
        await pg.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        await pg.wait_for_timeout(800)
        await pg.screenshot(path=prefix + '-guess-hover.png')
        for r in range(3):
            box = await pg.locator('#map').bounding_box()
            await pg.mouse.click(box['x'] + box['width'] * 0.45, box['y'] + box['height'] * 0.5)
            await pg.wait_for_timeout(300)
            await pg.click('#guess-button')
            await pg.wait_for_timeout(2000)
            if r == 0:
                await pg.screenshot(path=prefix + '-score.png')
            await pg.click('#next-button')
            await pg.wait_for_timeout(3000)
        await pg.screenshot(path=prefix + '-final.png')
        print('errors', errors)
        await b.close()
asyncio.run(main())
