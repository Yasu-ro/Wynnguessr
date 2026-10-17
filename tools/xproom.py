# usage: xproom.py <base_url> <prefix>
# two zz_ accounts play two classic rooms of 3 rounds in a row; the host aims at
# the answer and wins both: the end screen shows the XP, the win bonus, the streak
import sys, asyncio, sqlite3
from playwright.async_api import async_playwright
base, prefix = sys.argv[1].rstrip('/') + '/', sys.argv[2]

async def account(b, name):
    ctx = await b.new_context(viewport={'width': 1440, 'height': 900})
    pg = await ctx.new_page()
    pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
    pg.on('pageerror', lambda e: print(name, 'pageerror', e))
    await pg.goto(base + 'login', wait_until='networkidle')
    await pg.fill('input[name=username]', name)
    await pg.fill('input[name=password]', 'zz-test-password')
    await pg.click('button[type=submit]')
    await pg.wait_for_load_state('networkidle')
    if 'Invalid' in await pg.content():
        await pg.goto(base + 'register', wait_until='networkidle')
        await pg.fill('input[name=username]', name)
        await pg.fill('input[name=password]', 'zz-test-password')
        await pg.fill('input[name=confirmation]', 'zz-test-password')
        await pg.click('button[type=submit]')
        await pg.wait_for_load_state('networkidle')
    return pg

async def guess(pg, aim):
    box = await pg.locator('#map').bounding_box()
    if aim:
        # the answer, read from the server's own copy of the database
        await pg.evaluate("(a) => { map.invalidateSize(); map.setView([-a[1] + 3, a[0] + 2], 0, {animate: false}); }", answer(pg))
        await pg.wait_for_timeout(200)
    await pg.mouse.click(box['x'] + box['width'] * 0.5, box['y'] + box['height'] * 0.5)
    await pg.wait_for_timeout(300)
    await pg.click('#guess-button')

def answer(pg):
    code = pg.url.split('code=')[1]
    db = sqlite3.connect('file:' + sys.argv[3] + '?mode=ro', uri=True)
    r = db.execute("SELECT locations, round FROM rooms WHERE code = ?", (code,)).fetchone()
    import json
    lid = json.loads(r[0])[r[1] - 1]
    x, z = db.execute("SELECT x_position, z_position FROM locations WHERE location_id = ?", (lid,)).fetchone()
    return [x, z]

async def play(host, other, n):
    await host.wait_for_timeout(2500)
    await host.click('label[for=three]')
    await host.wait_for_timeout(1500)
    await host.click('#start-button')
    await host.wait_for_timeout(4000)
    for r in range(3):
        await guess(other, False)
        await host.wait_for_timeout(800)
        await guess(host, True)
        await host.wait_for_timeout(2500)
        nxt = host.locator('#next-button')
        await nxt.click()
        await host.wait_for_timeout(3500)
    for i, t in enumerate((400, 900, 2600)):
        await host.wait_for_timeout(t)
        await host.screenshot(path='%s-%d-%d.png' % (prefix, n, i), full_page=True)
    await other.screenshot(path='%s-%d-other.png' % (prefix, n), full_page=True)

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        host = await account(b, 'zz_lv1')
        other = await account(b, 'zz_lv2')
        await host.goto(base + 'mode?play=friends', wait_until='networkidle')
        await host.click('form[action="room/create"] button[type=submit]')
        await host.wait_for_load_state('networkidle')
        await other.goto(base + 'room?code=' + host.url.split('code=')[1], wait_until='networkidle')
        await play(host, other, 1)
        await host.click('#again-button')
        await host.wait_for_timeout(4000)
        print('second room', host.url, other.url)
        await play(host, other, 2)
        await b.close()
asyncio.run(main())
