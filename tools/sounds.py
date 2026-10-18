"""Fetch the game's sounds from Minecraft into static/sounds/ (not in git:
they belong to Mojang, so the repository never carries them; each site
fetches its own copy). Run from the repository: python3 tools/sounds.py

Each sound of the site is one or more Minecraft sounds (variants, picked at
random when played), converted to mp3, which every browser can decode.
The names and counts must match SOUNDS in static/js/sound.js."""
import json, os, subprocess, sys, tempfile, urllib.request

SOUNDS = {
    'pin': ['ui/cartography_table/drawmap1', 'ui/cartography_table/drawmap2', 'ui/cartography_table/drawmap3'],
    'guess': ['random/pop'],
    'other': ['random/wood_click'],
    'round': ['item/book/open_flip1', 'item/book/open_flip2', 'item/book/open_flip3'],
    'warn': ['note/bell'],
    'tick': ['note/hat'],
    'perfect': ['random/successful_hit'],
    'hurt': ['damage/hit1', 'damage/hit2', 'damage/hit3'],
    'out': ['random/break'],
    'win': ['ui/toast/challenge_complete'],
    'lose': ['mob/villager/no1', 'mob/villager/no2', 'mob/villager/no3'],
    'join': ['random/door_open'],
    'start': ['block/bell/bell_use01', 'block/bell/bell_use02'],
    'orb': ['random/orb'],
    'level': ['random/levelup'],
    'click': ['random/click'],
    'note': ['note/harp'],
    'good': ['note/pling'],
    'bad': ['note/bass'],
    'bubble': ['ui/hud/hud_bubble'],
    'toast': ['ui/toast/in'],
    'fuse': ['random/fuse'],
    'boom': ['random/explode1', 'random/explode2', 'random/explode3', 'random/explode4'],
    'throw': ['random/bow'],
    'splash': ['random/glass1', 'random/glass2', 'random/glass3'],
    'drink': ['random/drink'],
}

def get(url):
    with urllib.request.urlopen(url, timeout = 30) as r:
        return r.read()

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'sounds')
os.makedirs(out, exist_ok = True)
manifest = json.loads(get('https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'))
version = next(v for v in manifest['versions'] if v['id'] == manifest['latest']['release'])
index = json.loads(get(json.loads(get(version['url']))['assetIndex']['url']))['objects']
for name, sources in SOUNDS.items():
    for n, source in enumerate(sources, 1):
        h = index['minecraft/sounds/' + source + '.ogg']['hash']
        with tempfile.NamedTemporaryFile(suffix = '.ogg') as f:
            f.write(get('https://resources.download.minecraft.net/' + h[:2] + '/' + h))
            f.flush()
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', f.name, '-ac', '1', '-b:a', '96k',
                            os.path.join(out, f'{name}{n}.mp3')], check = True)
    print(name, len(sources), file = sys.stderr)
