# Guesser, the bot of the WynnGuessr Discord server.
#
# Yasuro (2026-10-20): know exactly who is who on Wynncraft, in the fewest
# steps for the player ("le plus simplistique et le plus direct"):
#   - #verify holds one message: Verify gives a one-time link to the site
#     (verify() in app.py), through Log in with Wynncraft and back. The site
#     keeps member <-> Minecraft account (discord_links).
#   - Roles: Verified for whoever verified, a "#1" for whoever leads a
#     leaderboard (both the bot's: given or taken by hand, they go back to
#     how they should be), and the tags, both ways: a tag given on the site
#     gives its role, a role given on Discord gives the tag, and a tag made
#     or deleted on one side is on the other. Tags are the roles between
#     two lines of the server (Yasuro: "entre les lignes c'est tout les
#     roles perso"): staff ranks, Members and the like never reach the site.
#   - Who is it: right-click a member > Apps > Wynncraft account, or /whois.
#
# Its own process (user service wynnguessr-bot), next to the site whose
# database it shares: it imports app.py, so the tables, tags and "#1"s are
# the ones the pages show. Only one may run with the token (two would answer
# every click twice): the beta's until 3.0, then the live site's.

import asyncio
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import quote, urlencode

import discord
from discord import app_commands

import app as A

TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'discord_token')   # not in git
GUILD = discord.Object(id = int(A.DISCORD_GUILD))
TAGS_TOP = 1561308593221795850      # the line above the tags...
TAGS_BOTTOM = 1561308596627570789   # ...and the one below them
MEMBERS = 1561308599274311730       # Verified goes right above this role
RULES = 1561308617401958450         # #verify comes right after this channel
CHANNEL = '✅・verify'
VERIFIED = 'Verified'
# the site's colours (style.css), so a tag looks the same on both
GREEN = 0x88cc42                    # --green, for Verified
TOP = 0xfbe7a6                      # .tag-top, a "#1"
TAG_HEX = {'gold': 0xffd75e, 'red': 0xc4372b, 'orange': 0xf58231, 'green': 0x88cc42,
           'teal': 0x77d1d7, 'purple': 0x8a5cc4, 'stone': 0xc9c5ba}
CARD = 0xa7eb64                     # the bar of the site's link previews (share.html)
RETRY = 600                         # seconds before trying again what Discord refused

log = logging.getLogger('guesser')
WAKE = asyncio.Event()              # something changed: sync soon
WAITING = {}                        # member id: (the click that gave their link, when)
FAILED = {}                         # what Discord refused: when


# ---------- the plan: what to change so that Discord and the site agree ----------
# Pure functions of what each side holds, so they can be tested alone.
#   site: tags {id: {label, color, retired}}, links {member id: {uuid, name, at}},
#         users {uuid: user id}, held {user id: {tag ids}}, tops {user id: [labels]},
#         ids {what: {id, name, color}} (the Discord things the bot looks after:
#         'verified', 'top:<label>', 'tag:<tag id>', 'channel', 'message'),
#         synced {(member id, role id): uuid} (the tags both sides had last time)
#   discord: roles {id: {name, color, position, managed}}, members {id: {role ids}}
# Ids are strings, as Discord's.

def label_of(name):
    # a tag's label from a role's name: a tag holds 20 characters
    return ' '.join(name.split())[:20]

def nearest(color):
    # the site's colour closest to a Discord one (weighted RGB, "redmean")
    if not color:
        return 'stone'
    r, g, b = color >> 16, color >> 8 & 255, color & 255
    def far(hex):
        R, G, B = hex >> 16, hex >> 8 & 255, hex & 255
        m = (r + R) / 2
        return (2 + m / 256) * (r - R) ** 2 + 4 * (g - G) ** 2 + (2 + (255 - m) / 256) * (b - B) ** 2
    return min(TAG_HEX, key = lambda k: far(TAG_HEX[k]))

def between(roles):
    # the roles between the two lines, top first; None when a line is gone
    # (then no role becomes a tag, and no tag gets a role)
    top, bottom = roles.get(str(TAGS_TOP)), roles.get(str(TAGS_BOTTOM))
    if not top or not bottom or bottom['position'] >= top['position']:
        return None
    return [rid for rid, r in sorted(roles.items(), key = lambda x: -x[1]['position'])
            if bottom['position'] < r['position'] < top['position'] and not r['managed'] and re.search(r'\w', r['name'])]

def plan_roles(site, disc, full = True):
    # the roles themselves: made, deleted, renamed; and the tags that go
    # with them. Not full (the beta, see live_site in app.py): Verified only
    roles, ids, tags = disc['roles'], site['ids'], site['tags']
    acts, taken = [], set()
    # Verified and the "#1"s, found again by their name when the database
    # does not know them (the live site's, at 3.0)
    own = {'verified': (VERIFIED, GREEN, 'verified')}
    if full:
        own.update({'top:' + label: (label, TOP, 'top') for label in A.TOP_LABELS})
    for what, (name, color, where) in own.items():
        row = ids.get(what)
        if row and row['id'] in roles:
            taken.add(row['id'])
            continue
        same = next((rid for rid, r in roles.items() if r['name'] == name and rid not in taken and not r['managed']), None)
        if same:
            taken.add(same)
            acts.append(('map', what, same, name, roles[same]['color']))
        else:
            acts.append(('create', what, name, color, where))
    if not full:
        return acts
    for what, row in ids.items():
        if what.startswith('top:') and what not in own:      # a board gone from the site
            acts.append(('delete', what, row['id']) if row['id'] in roles else ('unmap', what))
    # the tags that have a role
    paired = set()
    for what, row in ids.items():
        if not what.startswith('tag:'):
            continue
        tid, rid = int(what[4:]), row['id']
        t, r = tags.get(tid), roles.get(rid)
        if not t:
            acts.append(('unmap', what))
        elif not r:
            # its role was deleted on Discord: put away, as the site does (kept, with who had it)
            paired.add(tid)
            acts.append(('retire', tid, rid) if not t['retired'] else ('unmap', what))
        elif t['retired']:
            taken.add(rid)
            acts.append(('delete', what, rid))               # put away on the site
        else:
            paired.add(tid)
            taken.add(rid)
            if (r['name'], r['color']) != (row['name'], row['color']):
                # renamed or recoloured on Discord
                acts.append(('rename', tid, label_of(r['name']) or t['label'], nearest(r['color']), rid, r['name'], r['color']))
    block = between(roles)
    if block is None:
        return acts
    # roles between the lines with no tag yet: the tag of that name, else a new one
    for rid in block:
        if rid in taken:
            continue
        r = roles[rid]
        label = label_of(r['name'])
        same = next((tid for tid, t in sorted(tags.items()) if tid not in paired and t['label'].lower() == label.lower()), None)
        if same:
            paired.add(same)
            if tags[same]['retired']:
                acts.append(('unretire', same))
            acts.append(('map', 'tag:%d' % same, rid, r['name'], r['color']))
        else:
            acts.append(('make', rid, label, nearest(r['color']), r['name'], r['color']))
        taken.add(rid)
    # tags with no role yet (made on the site): one between the lines
    for tid, t in sorted(tags.items()):
        if not t['retired'] and tid not in paired:
            acts.append(('create', 'tag:%d' % tid, t['label'], TAG_HEX.get(t['color'], 0), 'tag'))
    return acts

def plan_members(site, disc, full = True):
    # who should hold what. The bot's roles follow the site; a tag follows
    # whichever side changed since last time (synced), and when neither
    # knows (a first look, a new link), both sides get it: nothing is lost.
    # Not full (the beta): Verified only, and a "#1" goes from whoever has it
    ids, roles = site['ids'], disc['roles']
    verified = ids.get('verified', {}).get('id')
    tops = {w[4:]: r['id'] for w, r in ids.items() if w.startswith('top:') and r['id'] in roles}
    tagged = {r['id']: int(w[4:]) for w, r in ids.items() if w.startswith('tag:') and r['id'] in roles
              and int(w[4:]) in site['tags'] and not site['tags'][int(w[4:])]['retired'] and full}
    own = set(tops.values()) | ({verified} if verified in roles else set())
    acts, keep = [], set()
    for mid, has in disc['members'].items():
        link = site['links'].get(mid)
        uid = site['users'].get(link['uuid']) if link else None
        want = {verified} if link and verified in roles else set()
        if uid and full:
            want |= {tops[label] for label in site['tops'].get(uid, []) if label in tops}
        for rid in sorted(own):
            why = 'Verified as %s' % link['name'] if rid == verified and link else \
                  'Not verified any more' if rid == verified else '#1 on WynnGuessr' if rid in want else 'Not #1 any more'
            if rid in want and rid not in has:
                acts.append(('add', mid, rid, why, None))
            elif rid in has and rid not in want:
                acts.append(('remove', mid, rid, why, None))
        if not uid:
            continue    # a tag needs both sides: verified, with a WynnGuessr account
        uuid, mine = link['uuid'], site['held'].get(uid, set())
        for rid, tid in sorted(tagged.items()):
            a, b = tid in mine, rid in has
            synced = site['synced'].get((mid, rid)) == uuid
            if a and b:
                keep.add((mid, rid, uuid))
            elif a:
                acts.append(('take', uid, tid, mid, rid, uuid) if synced else ('add', mid, rid, 'Tag given on WynnGuessr', uuid))
            elif b:
                acts.append(('remove', mid, rid, 'Tag taken on WynnGuessr', uuid) if synced else ('give', uid, tid, mid, rid, uuid))
    return acts, keep


# ---------- the site's side (sqlite waits on locks: always in a thread) ----------

def read_site():
    with A.connect() as c:
        site = {
            'tags': {t['id']: dict(t) for t in c.execute("SELECT id, label, color, retired FROM tags")},
            'links': {r['discord_id']: dict(r) for r in c.execute("SELECT * FROM discord_links")},
            'users': {r[0]: r[1] for r in c.execute("SELECT mc_uuid, id FROM users WHERE mc_uuid IS NOT NULL AND COALESCE(guest, 0) = 0")},
            'held': {},
            'ids': {r['what']: dict(r) for r in c.execute("SELECT * FROM discord_ids")},
            'synced': {(r['discord_id'], r['role_id']): r['uuid'] for r in c.execute("SELECT * FROM discord_held")},
            'tops': A.top_tags(c),
        }
        for uid, tid in c.execute("SELECT user_id, tag_id FROM user_tags"):
            site['held'].setdefault(uid, set()).add(tid)
    return site

def noted(c, target, details, who):
    # the staff's log (Moderation > Log), where by 0 reads "Discord"; who did
    # it there, when Discord's own log says
    name, reason = who or (None, '')
    c.execute("INSERT INTO mod_log (at, by, action, target, details, reason) VALUES (?, 0, 'tag', ?, ?, ?)",
              (time.time(), target, details + ' on Discord' + (' (%s)' % name if name else ''), (reason or '')[:200]))

def write_site(writes, held = None):
    # what Discord changed, on the site, in one go
    with A.room_tx() as c:
        for w in writes:
            kind, now = w[0], time.time()
            if kind == 'map':
                c.execute("INSERT OR REPLACE INTO discord_ids (what, id, name, color) VALUES (?, ?, ?, ?)", w[1:5])
            elif kind == 'unmap':
                c.execute("DELETE FROM discord_ids WHERE what = ?", (w[1],))
            elif kind == 'make':
                _, rid, label, color, name, hex, who = w
                tid = c.execute("INSERT INTO tags (label, color, by, at) VALUES (?, ?, 0, ?)", (label, color, now)).lastrowid
                c.execute("INSERT OR REPLACE INTO discord_ids (what, id, name, color) VALUES (?, ?, ?, ?)", ('tag:%d' % tid, rid, name, hex))
                noted(c, None, 'made the tag ' + label, who)
            elif kind == 'retire':
                _, tid, rid, who = w
                c.execute("UPDATE tags SET retired = 1 WHERE id = ?", (tid,))
                c.execute("DELETE FROM discord_ids WHERE what = ?", ('tag:%d' % tid,))
                noted(c, None, 'put away the tag ' + c.execute("SELECT label FROM tags WHERE id = ?", (tid,)).fetchone()[0], who)
            elif kind == 'unretire':
                c.execute("UPDATE tags SET retired = 0 WHERE id = ?", (w[1],))
                noted(c, None, 'put back the tag ' + c.execute("SELECT label FROM tags WHERE id = ?", (w[1],)).fetchone()[0], None)
            elif kind == 'rename':
                _, tid, label, color, rid, name, hex, who = w
                old = c.execute("SELECT label FROM tags WHERE id = ?", (tid,)).fetchone()[0]
                c.execute("UPDATE tags SET label = ?, color = ? WHERE id = ?", (label, color, tid))
                c.execute("UPDATE discord_ids SET name = ?, color = ? WHERE what = ?", (name, hex, 'tag:%d' % tid))
                if label != old:
                    noted(c, None, 'renamed the tag %s to %s' % (old, label), who)
            elif kind in ('give', 'take'):
                _, uid, tid, who = w
                label = c.execute("SELECT label FROM tags WHERE id = ?", (tid,)).fetchone()[0]
                if kind == 'give':
                    c.execute("INSERT OR IGNORE INTO user_tags (user_id, tag_id, by, at) VALUES (?, ?, 0, ?)", (uid, tid, now))
                    noted(c, uid, 'given the tag ' + label, who)
                else:
                    c.execute("DELETE FROM user_tags WHERE user_id = ? AND tag_id = ?", (uid, tid))
                    noted(c, uid, 'lost the tag ' + label, who)
        if held is not None:
            c.execute("DELETE FROM discord_held")
            c.executemany("INSERT INTO discord_held (discord_id, role_id, uuid) VALUES (?, ?, ?)", sorted(held))

def new_code(code, mid, name):
    with A.connect() as c:
        c.execute("DELETE FROM discord_codes WHERE at < ?", (time.time() - 86400,))
        c.execute("INSERT INTO discord_codes (code, discord_id, discord_name, at) VALUES (?, ?, ?, ?)", (code, mid, name, time.time()))

def find(mid = None, name = None):
    # (link, WynnGuessr account or None) of a member, or of a Minecraft name
    with A.connect() as c:
        if mid:
            link = c.execute("SELECT * FROM discord_links WHERE discord_id = ?", (mid,)).fetchone()
        else:
            link = c.execute('''SELECT l.* FROM discord_links l LEFT JOIN users u ON u.mc_uuid = l.uuid AND COALESCE(u.guest, 0) = 0
                WHERE l.name = ? COLLATE NOCASE OR u.mc_name = ? COLLATE NOCASE''', (name, name)).fetchone()
        if not link:
            return None
        user = c.execute("SELECT id, username FROM users WHERE mc_uuid = ? AND COALESCE(guest, 0) = 0", (link['uuid'],)).fetchone()
        return dict(link), dict(user) if user else None

def fresh_name(link):
    # Minecraft names change: Mojang's, else the one Wynncraft gave
    try:
        name = json.loads(A.fetch('https://sessionserver.mojang.com/session/minecraft/profile/' + link['uuid'].replace('-', '')))['name']
    except Exception:
        return link['name']
    if name != link['name']:
        with A.connect() as c:
            c.execute("UPDATE discord_links SET name = ? WHERE uuid = ?", (name, link['uuid']))
    return name

def known(what):
    # the id of one thing the bot looks after (discord_ids), or None
    row = A.connect().execute("SELECT id FROM discord_ids WHERE what = ?", (what,)).fetchone()
    return row and row[0]

def unlink(mid):
    with A.connect() as c:
        c.execute("DELETE FROM discord_links WHERE discord_id = ?", (mid,))

def site_url():
    # the site's address, from its Wynncraft redirect: the session that
    # verify() starts must come back to the same place
    cfg = A.wynn_config()
    return cfg['redirect_uri'].split('/auth/')[0] if cfg else None


# ---------- Discord's side ----------

client = discord.Client(intents = discord.Intents(guilds = True, members = True),
                        allowed_mentions = discord.AllowedMentions.none())
tree = app_commands.CommandTree(client)

def read_discord(guild, roles = None):
    # what Discord holds, from the bot's cache (or roles just asked for)
    return {'roles': {str(r.id): {'name': r.name, 'color': r.color.value, 'position': r.position, 'managed': r.managed}
                      for r in roles or guild.roles if not r.is_default()},
            'members': {str(m.id): {str(r.id) for r in m.roles if not r.is_default()} for m in guild.members if not m.bot}}

def pair(act):
    # (member, role, Minecraft account) of a tag's change; None for the bot's own roles
    if act[0] in ('add', 'remove'):
        return (act[1], act[2], act[4]) if act[4] else None
    return act[3:6]

def due(key):
    # not again what Discord refused a moment ago
    return time.time() - FAILED.get(key, 0) > RETRY

async def who_did(guild, action, target, role = None, added = True):
    # (who, why) of a change made by hand on Discord, as its audit log says
    try:
        async for e in guild.audit_logs(limit = 20, action = action):
            if time.time() - e.created_at.timestamp() > 600:
                break
            if str(getattr(e.target, 'id', '')) != str(target):
                continue
            if role and not any(str(r.id) == str(role) for r in getattr(e.after if added else e.before, 'roles', [])):
                continue
            return (e.user.name, e.reason) if e.user and e.user != client.user else None
    except discord.HTTPException:
        pass
    return None

async def place(guild, role, where):
    # a new role lands at the bottom of the list (position 1, shared): up
    # next to where it goes. Discord gives the position asked, puts the
    # older of two roles on one position first, then numbers them all again
    # (seen 2026-10-20): asking a role's position puts a new one right below it
    anchor = {'verified': MEMBERS, 'top': TAGS_BOTTOM, 'tag': TAGS_TOP}[where]
    at = {r.id: r.position for r in await guild.fetch_roles()}
    if anchor in at:
        await guild.edit_role_positions({role: at[anchor] + (0 if where == 'tag' else 1)}, reason = 'WynnGuessr')

async def apply_roles(guild, acts):
    writes = []
    for act in acts:
        kind = act[0]
        if not due(act[:3]):
            continue
        try:
            if kind == 'create':
                _, what, name, color, where = act
                role = await guild.create_role(name = name, colour = discord.Colour(color), permissions = discord.Permissions.none(),
                                               hoist = False, mentionable = False,
                                               reason = {'verified': 'WynnGuessr: verified players', 'top': 'WynnGuessr: #1 of a leaderboard',
                                                         'tag': 'WynnGuessr: tag made on the site'}[where])
                writes.append(('map', what, str(role.id), role.name, role.color.value))   # made: never twice
                log.info("made the role %s", name)
                try:
                    await place(guild, role, where)
                except discord.HTTPException as e:
                    log.warning("role %s left at the bottom: %s", name, e)
            elif kind == 'delete':
                _, what, rid = act
                role = guild.get_role(int(rid))
                if role:
                    await role.delete(reason = 'WynnGuessr: tag put away on the site')
                writes.append(('unmap', what))
                log.info("deleted the role %s", rid)
            elif kind == 'retire':
                writes.append(act + (await who_did(guild, discord.AuditLogAction.role_delete, act[2]),))
            elif kind == 'make':
                writes.append(act + (await who_did(guild, discord.AuditLogAction.role_create, act[1]),))
            elif kind == 'rename':
                writes.append(act + (await who_did(guild, discord.AuditLogAction.role_update, act[4]),))
            else:
                writes.append(act)
        except discord.HTTPException as e:
            FAILED[act[:3]] = time.time()
            log.warning("%s refused: %s", act[:3], e)
    if writes:
        await asyncio.to_thread(write_site, writes)
        log.info("roles: %s", [w[:3] for w in writes])
    return bool(writes)

async def apply_members(guild, site, acts, keep):
    # held: the tags both sides have once done. A taking that did not happen
    # stays "both had it", so it is tried again rather than undone
    writes, held = [], set(keep)
    for act in acts:
        kind = act[0]
        if not due(act[:4]):
            if kind in ('remove', 'take') and pair(act):
                held.add(pair(act))
            continue
        try:
            if kind in ('add', 'remove'):
                _, mid, rid, why, uuid = act
                member, role = guild.get_member(int(mid)), guild.get_role(int(rid))
                if not member or not role:
                    continue
                if kind == 'add':
                    await member.add_roles(role, reason = why)
                    if uuid:
                        held.add(pair(act))
                else:
                    await member.remove_roles(role, reason = why)
                log.info("%s %s %s (%s)", kind, role.name, member.name, why)
            elif kind == 'give':
                _, uid, tid, mid, rid, uuid = act
                writes.append(('give', uid, tid, await who_did(guild, discord.AuditLogAction.member_role_update, mid, rid)))
                held.add((mid, rid, uuid))
            elif kind == 'take':
                _, uid, tid, mid, rid, uuid = act
                # its role seems taken: asked again before the tag goes
                member = await guild.fetch_member(int(mid))
                if any(str(r.id) == rid for r in member.roles):
                    held.add((mid, rid, uuid))
                    continue
                writes.append(('take', uid, tid, await who_did(guild, discord.AuditLogAction.member_role_update, mid, rid, added = False)))
        except discord.HTTPException as e:
            FAILED[act[:4]] = time.time()
            log.warning("%s refused: %s", act[:4], e)
            if kind in ('remove', 'take') and pair(act):
                held.add(pair(act))
    if writes or held != {(m, r, u) for (m, r), u in site['synced'].items()}:
        await asyncio.to_thread(write_site, writes, held)
    if writes:
        log.info("tags: %s", writes)

LOCK = asyncio.Lock()

async def sync():
    async with LOCK:
        guild = client.get_guild(GUILD.id)
        if not guild or guild.unavailable or not guild.chunked:
            return
        site, full = await asyncio.to_thread(read_site), A.live_site()
        if plan_roles(site, read_discord(guild), full):
            # something to change: planned again on the roles as Discord has
            # them now (a role just made may not be in the cache yet, and
            # would be made twice)
            if await apply_roles(guild, plan_roles(site, read_discord(guild, await guild.fetch_roles()), full)):
                site = await asyncio.to_thread(read_site)
        acts, keep = plan_members(site, read_discord(guild), full)
        await apply_members(guild, site, acts, keep)
        await tell_waiting(site)


# ---------- what members see ----------

def card(text, link = None, title = None):
    e = discord.Embed(color = CARD, description = text, title = title)
    if link and site_url():
        e.set_thumbnail(url = site_url() + '/avatar?' + urlencode({'uuid': link['uuid']}))
    return e

def door_card(verified, full = True):
    e = card("Show everyone here which Wynncraft player you are, in two clicks:\n\n"
             "**1.** Press **Verify**\n"
             "**2.** Log in on wynncraft.com and press **Authorize**\n\n"
             "You get %s%s." % ('<@&%s>' % verified if verified else '**Verified**',
                                ', and your WynnGuessr tags come along (like a **#1** on a leaderboard)' if full else ''),
             title = 'Verify your Minecraft account')
    e.set_footer(text = 'We only see your Minecraft name. Never your password or email.')
    return e

def guide(verified, support):
    # every step from nothing (Yasuro: "un tutoriel super facile à
    # comprendre"), with wynncraft.com's own words, as its code had them
    # on 2026-10-20: SIGN IN, CONTINUE, VERIFY, REGISTER, then LINK
    def step(title, text, color):
        return discord.Embed(title = title, description = text, color = color)
    return [step('1. Make a Wynncraft account',
                 "Already have one? Go to **2**.\n\n"
                 "**1.** Open [wynncraft.com/account/login](https://wynncraft.com/account/login)\n"
                 "**2.** Type your email and press **SIGN IN**\n"
                 "**3.** Press **CONTINUE**\n"
                 "**4.** Wynncraft emails you a code: type it and press **VERIFY**\n"
                 "**5.** Pick a password and press **REGISTER**", TAG_HEX['gold']),
            step('2. Add your Minecraft account',
                 "**1.** On your computer, open Minecraft (Java Edition) and join `play.wynncraft.com`\n"
                 "**2.** On wynncraft.com, press **Link your Minecraft account**\n"
                 "*Closed it? Open your [dashboard](https://wynncraft.com/account/dashboard) and press* **ADD MINECRAFT ACCOUNT**\n"
                 "**3.** Type your Minecraft name and press **LINK**\n"
                 "**4.** A code shows up in your Minecraft chat: type it on wynncraft.com and press **LINK**\n"
                 "*No code? Type `/link` in Minecraft*", TAG_HEX['teal']),
            step('3. Verify here',
                 "**1.** Press **Verify**, then **Verify with Wynncraft**\n"
                 "**2.** Log in if asked, then press **Authorize**\n"
                 "**3.** Done! You get %s" % ('<@&%s>' % verified if verified else '**Verified**')
                 + ("\n\nStuck? Ask in %s" % support if support else ''), TAG_HEX['green'])]

def questions(full = True):
    site = site_url() or A.LIVE
    return card("**No wynncraft.com account?**\n"
                "Press **Don't know how?**: every step, from zero.\n\n"
                "**More than one Minecraft account?**\n"
                "We take your main one. You can pick it on wynncraft.com.\n\n"
                "**New Minecraft name?**\n"
                "Nothing to do: we know your account, not just its name.\n\n"
                "**Wrong account?**\n"
                "Press **Verify**, then **Use another account**.\n\n"
                "**Who can see it?**\n"
                "Everyone here: right-click someone, then **Apps › Wynncraft account**. Or type `/whois`.\n\n"
                + ("**Tags missing?**\n"
                   "Log in on [%s](%s) with Wynncraft, with the same Minecraft account.\n\n" % (site.split('//')[1], site) if full else '') +
                "**Want to stop?**\n"
                "Press **Verify**, then **Unlink**.", title = 'Questions')

class Door(discord.ui.View):
    # the buttons under the message in #verify; they answer after a restart too
    def __init__(self):
        super().__init__(timeout = None)

    @discord.ui.button(label = 'Verify', style = discord.ButtonStyle.success, custom_id = 'wg:verify')
    async def verify(self, interaction, button):
        await interaction.response.defer(ephemeral = True, thinking = True)
        found = await asyncio.to_thread(find, str(interaction.user.id))
        if found:
            name = await asyncio.to_thread(fresh_name, found[0])
            await interaction.edit_original_response(embed = card("You're verified as **%s**." % discord.utils.escape_markdown(name), found[0]),
                                                     view = Account())
        else:
            await give_link(interaction)

    @discord.ui.button(label = "Don't know how?", style = discord.ButtonStyle.secondary, custom_id = 'wg:guide')
    async def steps(self, interaction, button):
        verified = await asyncio.to_thread(known, 'verified')
        support = discord.utils.find(lambda c: 'support' in c.name, interaction.guild.text_channels) if interaction.guild else None
        await interaction.response.send_message(embeds = guide(verified, support and support.mention), ephemeral = True)

    @discord.ui.button(label = 'Questions', style = discord.ButtonStyle.secondary, custom_id = 'wg:help')
    async def help(self, interaction, button):
        await interaction.response.send_message(embed = questions(A.live_site()), ephemeral = True)

class Account(discord.ui.View):
    # under "You're verified as ...", seen by that member only
    def __init__(self):
        super().__init__(timeout = None)

    @discord.ui.button(label = 'Use another account', style = discord.ButtonStyle.secondary, custom_id = 'wg:again')
    async def again(self, interaction, button):
        await interaction.response.defer()
        await give_link(interaction)

    @discord.ui.button(label = 'Unlink', style = discord.ButtonStyle.danger, custom_id = 'wg:unlink')
    async def unlink(self, interaction, button):
        await interaction.response.defer()
        await asyncio.to_thread(unlink, str(interaction.user.id))
        WAKE.set()
        await interaction.edit_original_response(embed = card("Unlinked. Press **Verify** whenever you want to come back."), view = None)

async def give_link(interaction):
    # a one-time link to the site, for this member only; once they are back,
    # this same message says so (tell_waiting)
    site = site_url()
    if not site:
        await interaction.edit_original_response(embed = card("Verifying opens soon."), view = None)
        return
    code = secrets.token_urlsafe(18)
    await asyncio.to_thread(new_code, code, str(interaction.user.id), interaction.user.display_name)
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label = 'Verify with Wynncraft', url = site + '/verify?code=' + code))
    e = card("**Your link is ready**\nLog in on wynncraft.com, then press **Authorize**.")
    e.set_footer(text = 'Only for you · works for %d minutes' % (A.VERIFY_LIFE // 60))
    await interaction.edit_original_response(embed = e, view = view)
    WAITING[str(interaction.user.id)] = (interaction, time.time())

async def tell_waiting(site):
    for mid, (interaction, since) in list(WAITING.items()):
        link = site['links'].get(mid)
        if time.time() - since > 14 * 60:          # Discord lets a click's answer change for 15 minutes
            WAITING.pop(mid)
        elif link and link['at'] >= since:
            WAITING.pop(mid)
            try:
                await interaction.edit_original_response(embed = card("✅ You're verified as **%s**." % discord.utils.escape_markdown(link['name']), link),
                                                         view = None)
            except discord.HTTPException:
                pass

async def door(guild):
    # #verify and its one message: made once, kept up to date after
    ids = (await asyncio.to_thread(read_site))['ids']
    channel = guild.get_channel(int(ids['channel']['id'])) if 'channel' in ids else None
    channel = channel or discord.utils.get(guild.text_channels, name = CHANNEL)
    if channel is None:
        rules = guild.get_channel(RULES)
        category = rules.category if rules else None
        channel = await guild.create_text_channel(CHANNEL, category = category, overwrites = category.overwrites if category else {},
                                                  reason = 'WynnGuessr: verifying')
        if rules:
            await channel.move(after = rules)
    message = None
    if ids.get('channel', {}).get('id') == str(channel.id) and 'message' in ids:
        try:
            message = await channel.fetch_message(int(ids['message']['id']))
        except discord.NotFound:
            pass
    if message is None:
        # its message from before, when the database does not know it (the live site's, at 3.0)
        async for m in channel.history(limit = 30):
            if m.author == client.user and m.components:
                message = m
                break
    e = door_card(ids.get('verified', {}).get('id'), A.live_site())
    if message:
        await message.edit(embed = e, view = Door())
    else:
        message = await channel.send(embed = e, view = Door())
    await asyncio.to_thread(write_site, [('map', 'channel', str(channel.id), channel.name, None),
                                         ('map', 'message', str(message.id), None, None)])

async def whois_answer(interaction, member = None, name = None):
    await interaction.response.defer(ephemeral = True, thinking = True)
    if not member and not name:
        await interaction.edit_original_response(embed = card("Pick a member, or type a Minecraft name."))
        return
    found = await asyncio.to_thread(find, str(member.id) if member else None, name and name.strip())
    who = member or (found and interaction.guild.get_member(int(found[0]['discord_id'])))
    if not found or not who:
        await interaction.edit_original_response(embed = card(
            "%s hasn't verified yet." % member.mention if member else "Nobody here verified **%s**." % discord.utils.escape_markdown(name)))
        return
    link, user = found
    mc = await asyncio.to_thread(fresh_name, link)
    site = site_url() or 'https://wynndle.com'
    text = '%s · verified <t:%d:D>' % (who.mention, link['at'])
    if user:
        text += '\nWynnGuessr: [%s](%s/player?id=%d)' % (discord.utils.escape_markdown(user['username']), site, user['id'])
    e = card(text, link, mc)
    e.url = 'https://wynncraft.com/stats/player/' + quote(mc)
    await interaction.edit_original_response(embed = e)

@tree.context_menu(name = 'Wynncraft account', guild = GUILD)
async def account_menu(interaction: discord.Interaction, member: discord.Member):
    await whois_answer(interaction, member)

@tree.command(name = 'whois', description = "Someone's Wynncraft account", guild = GUILD)
@app_commands.describe(member = 'Someone on this server', minecraft = 'Or a Minecraft name')
async def whois(interaction: discord.Interaction, member: discord.Member = None, minecraft: str = None):
    await whois_answer(interaction, member, minecraft)


# ---------- running ----------

@client.event
async def on_member_update(before, after):
    if before.roles != after.roles:
        WAKE.set()

@client.event
async def on_member_join(member):
    WAKE.set()

@client.event
async def on_guild_role_create(role):
    WAKE.set()

@client.event
async def on_guild_role_delete(role):
    WAKE.set()

@client.event
async def on_guild_role_update(before, after):
    WAKE.set()

async def watch():
    # the site wrote something (a tag given, a link made...): sync soon.
    # data_version moves whenever another connection writes
    con = sqlite3.connect('database.db')
    last = None
    while True:
        try:
            now = con.execute('PRAGMA data_version').fetchone()[0]
            if now != last:
                last = now
                WAKE.set()
        except sqlite3.Error:
            pass
        await asyncio.sleep(2)

async def syncing():
    # one sync at a time, when something changed, else every TOPS_EVERY (a "#1" moves on its own)
    await client.wait_until_ready()
    door_done = False
    while not client.is_closed():
        try:
            await asyncio.wait_for(WAKE.wait(), timeout = A.TOPS_EVERY)
        except asyncio.TimeoutError:
            pass
        WAKE.clear()
        try:
            await sync()
            if not door_done and client.get_guild(GUILD.id):
                await door(client.get_guild(GUILD.id))
                door_done = True
        except Exception:
            log.exception("sync")
            await asyncio.sleep(30)
        await asyncio.sleep(1)

async def setup():
    client.add_view(Door())
    client.add_view(Account())
    await tree.sync(guild = GUILD)
    asyncio.create_task(watch())
    asyncio.create_task(syncing())

client.setup_hook = setup

if __name__ == '__main__':
    with open(TOKEN_FILE) as f:
        token = f.read().strip()
    client.run(token, log_level = logging.INFO, root_logger = True)
