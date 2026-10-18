# usage: xpsolo.py <base_url> <prefix> <user> [rounds] [aim:1|0] [database]
# a zz_ account plays a solo game aiming at the answer, then the end screen is
# photographed while the XP bar fills. The page no longer knows the answer
# (the game is played on the server): to aim, give the path of the site's
# database, the answer is read there
import sys, asyncio, sqlite3
from playwright.async_api import async_playwright
base, prefix, user = sys.argv[1].rstrip('/') + '/', sys.argv[2], sys.argv[3]
rounds = sys.argv[4] if len(sys.argv) > 4 else '3'
aim = (sys.argv[5] if len(sys.argv) > 5 else '1') == '1'
database = sys.argv[6] if len(sys.argv) > 6 else None
aim = aim and database is not None

def answer():
    # the round being played: the last solo game's location
    c = sqlite3.connect('file:' + database + '?mode=ro', uri = True)
    return c.execute("""SELECT l.x_position, l.z_position FROM solo_games g
        JOIN locations l ON l.location_id = g.location_id ORDER BY g.id DESC LIMIT 1""").fetchone()
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
                X, Z = answer()
                await pg.evaluate("map.invalidateSize(); map.setView([%f, %f], 0, {animate: false})" % (-Z + 4, X + 3))
                await pg.wait_for_timeout(200)
            pt = [box['width'] * 0.5, box['height'] * 0.5]
            await pg.mouse.click(box['x'] + pt[0], box['y'] + pt[1])
            await pg.wait_for_timeout(300)
            await pg.click('#guess-button')
            await pg.wait_for_timeout(1500)
            await pg.click('#next-button')
            await pg.wait_for_timeout(1200)
        for i, t in enumerate((300, 600, 600, 600, 2000)):
            await pg.wait_for_timeout(t)
            await pg.screenshot(path='%s-%d.png' % (prefix, i), clip={'x': 420, 'y': 600, 'width': 600, 'height': 300})
        print('score:', await pg.inner_text('#score'), '| errors', errors)
        await b.close()
asyncio.run(main())
