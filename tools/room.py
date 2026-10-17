# usage: room.py <base_url> <prefix> <mode> [width] [height]
# two zz_ guests play a 3-round room: lobby, guess, reveal, results (host's screen)
import sys, asyncio
from playwright.async_api import async_playwright
base, prefix, mode = sys.argv[1].rstrip('/') + '/', sys.argv[2], sys.argv[3]
w = int(sys.argv[4]) if len(sys.argv) > 4 else 1440
h = int(sys.argv[5]) if len(sys.argv) > 5 else 900

async def guest(b, name, w, h):
    ctx = await b.new_context(viewport={'width': w, 'height': h})
    pg = await ctx.new_page()
    pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
    pg.on('pageerror', lambda e: print(name, 'pageerror', e))
    await pg.goto(base + 'guest?next=mode%3Fplay%3Dfriends', wait_until='networkidle')
    await pg.fill('input[name=username]', name)
    await pg.click('button[type=submit]')
    await pg.wait_for_load_state('networkidle')
    return pg

async def guess(pg, fx, fy):
    box = await pg.locator('#map').bounding_box()
    if box is None:
        await pg.screenshot(path=prefix + '-debug.png')
        print('no map on', pg.url, await pg.evaluate("document.body.className + ' | ' + [...document.querySelectorAll('section')].map(s => s.id + ':' + !s.hidden).join(' ')"))
    await pg.mouse.click(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
    await pg.wait_for_timeout(300)
    await pg.click('#guess-button')

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--use-gl=swiftshader', '--enable-webgl', '--ignore-gpu-blocklist'])
        host = await guest(b, 'zz_host', w, h)
        await host.click('label[for=new-' + mode + ']')
        await host.click('form[action="room/create"] button[type=submit]')
        await host.wait_for_load_state('networkidle')
        code = host.url.split('code=')[1]
        print('room', code)
        other = await guest(b, 'zz_friend', 1280, 800)
        await other.goto(base + 'room?code=' + code, wait_until='networkidle')
        await host.wait_for_timeout(2500)
        if mode == 'classic':
            await host.click('label[for=three]')
            await host.wait_for_timeout(1500)
        await host.screenshot(path=prefix + '-lobby.png', full_page=True)
        await host.click('#start-button')
        await host.wait_for_timeout(4500)
        await host.screenshot(path=prefix + '-guess.png')
        for r in range(1, 26):
            if await other.locator('#results').is_visible() or await host.locator('#results').is_visible():
                break
            await guess(other, 0.40, 0.45)
            await host.wait_for_timeout(1200)
            if r == 1:
                await host.screenshot(path=prefix + '-guess-other.png')
            await guess(host, 0.55, 0.55)
            await host.wait_for_timeout(2500)
            if r in (1, 2):
                await host.screenshot(path=prefix + '-reveal%d.png' % r)
            if await host.locator('#results').is_visible():
                break
            nxt = host.locator('#next-button')
            if await nxt.is_visible() and await nxt.is_enabled():
                if 'Results' in (await nxt.inner_text()):
                    await nxt.click()
                    await host.wait_for_timeout(2500)
                    break
                await nxt.click()
            await host.wait_for_timeout(3500)
        await host.wait_for_timeout(1500)
        await host.screenshot(path=prefix + '-results.png', full_page=True)
        await other.screenshot(path=prefix + '-results-other.png', full_page=True)
        await b.close()
asyncio.run(main())
