# usage: xpsolo.py <base_url> <prefix> <user> [rounds] [aim:1|0]
# a zz_ account plays a solo game aiming at the answer, then the end screen is
# photographed while the XP bar fills
import sys, asyncio
from playwright.async_api import async_playwright
base, prefix, user = sys.argv[1].rstrip('/') + '/', sys.argv[2], sys.argv[3]
rounds = sys.argv[4] if len(sys.argv) > 4 else '3'
aim = (sys.argv[5] if len(sys.argv) > 5 else '1') == '1'
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        ctx = await b.new_context(viewport={'width': 1440, 'height': 900})
        pg = await ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        await pg.goto(base + 'login', wait_until='networkidle')
        await pg.fill('input[name=username]', user)
        await pg.fill('input[name=password]', 'zz-test-password')
        await pg.click('button[type=submit]')
        await pg.wait_for_load_state('networkidle')
        if 'Invalid' in await pg.content():
            await pg.goto(base + 'register', wait_until='networkidle')
            await pg.fill('input[name=username]', user)
            await pg.fill('input[name=password]', 'zz-test-password')
            await pg.fill('input[name=confirmation]', 'zz-test-password')
            await pg.click('button[type=submit]')
            await pg.wait_for_load_state('networkidle')
        q = 'game?mode=classic&province=wynn&province=gavel&province=corkus&province=ocean&province=silent-expanse&rounds=' + rounds
        await pg.goto(base + q, wait_until='networkidle')
        await pg.wait_for_timeout(2500)
        for r in range(int(rounds)):
            box = await pg.locator('#map').bounding_box()
            await pg.mouse.move(box['x'] + 30, box['y'] + 30)
            await pg.wait_for_timeout(500)
            box = await pg.locator('#map').bounding_box()
            if aim:
                await pg.evaluate("(() => { var l = images[round - 1]; map.invalidateSize(); map.setView([-l.Z + 4, l.X + 3], 0, {animate: false}); })()")
                await pg.wait_for_timeout(200)
            pt = [box['width'] * 0.5, box['height'] * 0.5]
            await pg.mouse.click(box['x'] + pt[0], box['y'] + pt[1])
            await pg.wait_for_timeout(300)
            await pg.click('#guess-button')
            await pg.wait_for_timeout(1500)
            await pg.click('#next-button')
        for i, t in enumerate((300, 600, 600, 600, 2000)):
            await pg.wait_for_timeout(t)
            await pg.screenshot(path='%s-%d.png' % (prefix, i), clip={'x': 420, 'y': 600, 'width': 600, 'height': 300})
        print('score:', await pg.inner_text('#score'), '| errors', errors)
        await b.close()
asyncio.run(main())
