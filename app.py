from flask import Flask, render_template, url_for, request, redirect, session, send_from_directory, send_file, jsonify
import os
import re
import sqlite3
import json
import math
import secrets
import subprocess
import shutil
import zipfile
import io
import time
import base64
import hashlib
import fcntl
from datetime import date
import urllib.request
from urllib.parse import quote, urlencode
from flask_bcrypt import Bcrypt
from config import Config

app = Flask(__name__)
bcrypt = Bcrypt(app)
app.config.from_object(Config)
# other sites share this domain behind Tailscale Funnel
app.config['SESSION_COOKIE_NAME'] = 'wynnguessr_session'
# never sent with another site's forms (nobody can act for a player from
# elsewhere), and only over https
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True
# nothing bigger comes in (the mod's captures are ~13 MB)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024

# only these locations are played; 'new' ones wait for the review
PLAYABLE = "('old', 'kept')"

def connect():
    # one connection per request: a single shared one is not safe across threads
    c = sqlite3.connect('database.db', timeout=10)
    c.row_factory = sqlite3.Row
    return c

# The site runs several processes (gunicorn -w): each one runs the
# migrations below as it starts. One at a time, or two could add the same
# column and one would fail to start (the lock is let go at the end of this
# file). The database in WAL mode: reading no longer holds up a writer.
STARTING = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.starting.lock'), 'w')
fcntl.flock(STARTING, fcntl.LOCK_EX)
with connect() as c:
    c.execute("PRAGMA journal_mode=WAL")

@app.context_processor
def assets():
    # Cloudflare tells browsers to keep static files 4 hours without asking
    # again: a changed file needs a new address to be seen at once
    def asset(path):
        try:
            return 'static/' + path + '?v=' + str(int(os.path.getmtime(os.path.join(app.static_folder, path))))
        except OSError:
            return 'static/' + path
    return {'asset': asset}

@app.after_request
def only_one_site_in_search(response):
    # beta.wynndle.com and the old ts.net address are the same site: kept out
    # of search engines, so Google only lists wynndle.com
    if request.host != 'wynndle.com':
        response.headers['X-Robots-Tag'] = 'noindex'
    return response

@app.after_request
def kept_long(response):
    # a file whose address changes with it (asset(): ?v=, the map's tiles in
    # a folder named after the map, Mojang's sounds that never change) is
    # kept a year, by the browser and by Cloudflare, without asking again:
    # before, Cloudflare checked them every 4 hours and the 8.7 MB map came
    # back from here
    if request.endpoint == 'static' and response.status_code == 200 and (
            'v' in request.args or request.path.startswith(('/static/map-2026/', '/static/sounds/'))):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

@app.after_request
def no_tricks(response):
    # no page of this site inside another site's frame (fake buttons over
    # real ones), and a file is only ever read as the type it is served as
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # nor carry a <base>, run a plugin, or send its forms anywhere else; and
    # always https (the browser remembers it a year). The scripts themselves
    # are left free: the pages have inline ones, and the CDNs they come from
    # host any npm package, so a list would stop nothing
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'self'; object-src 'none'; form-action 'self'"
    response.headers['Strict-Transport-Security'] = 'max-age=31536000'
    return response

def next_page():
    # where to go after logging in: only a page of this site, e.g. "room?code=ABC234"
    page = request.args.get('next', '')
    return page if re.fullmatch(r'[a-z]+(\?(code|play|join)=[A-Za-z0-9_-]+)?', page) else './'

# The solo Classic game is played on the server (section "Solo" below): the
# browser never had to know where the locations are. The old routes that
# gave it every location with its coordinates (api/locations) and took its
# score as it said (api/score) are gone.

def save_solo(c, uid, g):
    c.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
              (uid, g['score'], date.today(), g['nolook'], g['provinces'], g['rounds'], g['time'], g['mode']))

def adopt(c, uid):
    # on logging in or making an account, what was just played becomes the
    # account's: the solo game waiting in the session, and the rooms played as
    # a guest (a finished classic one then lands on the leaderboard)
    game = session.pop('pending', None)
    if game:
        save_solo(c, uid, game)
    gid = session.get('solo')
    if gid:
        c.execute("UPDATE solo_games SET user_id = ? WHERE id = ? AND user_id IS NULL AND phase != 'over'", (uid, gid))
    rid = session.get('survival')
    if rid and c.execute("UPDATE survival_runs SET user_id = ? WHERE id = ? AND user_id IS NULL", (uid, rid)).rowcount:
        survival_record(c, c.execute("SELECT * FROM survival_runs WHERE id = ?", (rid,)).fetchone())
    old = session.get('user_id')
    if session.get('loggedin') or not old or old == uid:
        return
    if not c.execute("SELECT COALESCE(guest, 0) FROM users WHERE id = ?", (old,)).fetchone()[0]:
        return
    for p in c.execute("""SELECT * FROM room_players WHERE user_id = ?
            AND code NOT IN (SELECT code FROM room_players WHERE user_id = ?)""", (old, uid)).fetchall():
        for table in ('room_players', 'room_guesses', 'room_chat', 'room_milk'):
            c.execute(f"UPDATE {table} SET user_id = ? WHERE code = ? AND user_id = ?", (uid, p['code'], old))
        for column in ('buyer', 'target'):
            c.execute(f"UPDATE room_shop SET {column} = ? WHERE code = ? AND {column} = ?", (uid, p['code'], old))
        c.execute("UPDATE rooms SET host_id = ? WHERE code = ? AND host_id = ?", (uid, p['code'], old))
        r = find_room(c, p['code'])
        done = c.execute("SELECT COUNT(*) FROM room_guesses WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()[0]
        if r['state'] == 'finished' and r['mode'] == 'classic' and (p['live'] or done == r['rounds']):
            record(c, r, uid)
        elif r['state'] == 'finished' and r['mode'] == 'survival':
            survival_room_record(c, r, uid)

def board(c, form, user_id = None):
    # the games played with exactly the settings of the filters, best first
    # Survival: one board per difficulty, the most locations survived, then the most points
    mode = 'survival' if form.get('mode') == 'survival' else 'classic'
    query = '''SELECT u.id, u.username AS name, u.mc_name AS mc, u.avatar, u.mc_uuid, s.score, s.points, s.time, s.date
        FROM scores s JOIN users u ON u.id = s.user_id WHERE COALESCE(s.mode, 'classic') = ?'''
    params = [mode]
    if mode == 'classic':
        # the whole map only: choosing provinces is for custom games
        query += " AND s.provinces = ? AND s.nolook = ? AND s.rounds = ?"
        params += [str(PROVINCES), form.get('nolook', 'No'), form.get('rounds', '')]
        order = " ORDER BY s.score DESC, s.time ASC"
    else:
        query += " AND s.difficulty = ? AND COALESCE(s.milk, 0) = ?"
        params += [form.get('difficulty', 'normal'), int(form.get('milk') == '1')]
        order = " ORDER BY s.score DESC, s.points DESC, s.time ASC"
    if user_id:
        query += " AND s.user_id = ?"
        params.append(user_id)
    return [dict(row) for row in c.execute(query + order, params)]

def ladder(c, mode):
    # levels: the most XP first; wins (players who won at least once): the most
    # wins with friends first, then the longest streak, then the fewest games for them
    rows = []
    for u in c.execute("SELECT id, username, mc_name, avatar, mc_uuid FROM users WHERE COALESCE(guest, 0) = 0").fetchall():
        p = progress(c, u['id'])
        if p['xp'] if mode == 'levels' else p['wins']:
            rows.append({'id': u['id'], 'name': u['username'], 'mc': u['mc_name'], 'avatar': u['avatar'], 'mc_uuid': u['mc_uuid'],
                         **{k: p[k] for k in ('xp', 'level', 'games', 'played', 'wins', 'best', 'streak')}})
    if mode == 'levels':
        return sorted(rows, key = lambda r: -r['xp'])
    return sorted(rows, key = lambda r: (-r['wins'], -r['best'], r['played']))

BOARD_PAGE = 50   # rows of a leaderboard sent at once

@app.route("/api/updaterank", methods=['POST'])
def update_rank():
    # each player's best game, or the levels, or the wins with friends
    with connect() as c:
        if request.form.get('mode') in ('levels', 'wins'):
            rows = ladder(c, request.form['mode'])
        else:
            rows, seen = [], set()
            for row in board(c, request.form):
                if row['id'] not in seen:
                    seen.add(row['id'])
                    rows.append(row)
            # every leaderboard shows the players' levels and current win streaks
            known = {r['id']: r for r in ladder(c, 'levels')}
            for row in rows:
                row['level'] = known.get(row['id'], {}).get('level', 1)
                row['streak'] = known.get(row['id'], {}).get('streak', 0)
        # 50 at a time ("Show more"), and the player's own place on the whole board
        start = max(0, request.form.get('start', 0, type = int))
        uid = session.get('user_id')
        mine = next(({**row, 'rank': i + 1} for i, row in enumerate(rows) if row['id'] == uid), None)
        total, rows = len(rows), rows[start:start + BOARD_PAGE]
        tags = tag_of(c, [r['id'] for r in rows] + ([mine['id']] if mine else []))
        for row in rows + ([mine] if mine else []):
            row['tag'] = tags.get(row['id'])
        # each player's picture; a Minecraft head is drawn sharp
        for row in rows + ([mine] if mine else []):
            row['pic'], row['head'] = avatar_url(row), not row.get('avatar')
            row.pop('avatar', None)
            row.pop('mc_uuid', None)
    return jsonify({"rows": rows, "start": start, "total": total, "me": uid, "mine": mine,
                    "ranked": bool(session.get('loggedin'))})

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/mode")
def play():
    # the Multiplayer card says how many are in the worlds right now
    online = 0
    if not request.args.get('play'):
        with connect() as c:
            online = sum(w['waiting'] + w['playing'] for w in world_counts(c).values())
    return render_template('mode.html', online = online)

@app.route("/leaderboard")
def leaderboard():
    return render_template('leaderboard.html')

DISCORD = 'https://discord.gg/fMqQ2p5mZr'
# the site's version, in the footer: one more at each push to the live site
# (2.0 the new look, 2.1 Survival remade, 2.2 Survival with friends; CLAUDE.md)
VERSION = '2.3'

@app.context_processor
def site_version():
    return {'version': VERSION}

# Who comes, for the About page: a random id kept in the session (no
# account needed) and when it was last seen, written once a minute at most.
# Robots that say so are not counted. Counting started on 2026-10-18.
SEEN_EVERY = 60          # seconds between two writes for the same visitor
ONLINE = 300             # seen this recently: online now
ROBOTS = re.compile(r'bot|crawl|spider|preview|curl|python|wget|http', re.I)

with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS visitors (vid TEXT PRIMARY KEY, first REAL, last REAL)")

@app.before_request
def count_visitor():
    now = time.time()
    if (request.endpoint in ('static', 'play_tile', 'survival_tile', 'avatar') or now - session.get('seen', 0) < SEEN_EVERY
            or ROBOTS.search(request.headers.get('User-Agent', ''))):
        return
    session['vid'] = session.get('vid') or secrets.token_hex(8)
    session['seen'] = now
    with connect() as c:
        c.execute("INSERT INTO visitors (vid, first, last) VALUES (?, ?, ?) ON CONFLICT(vid) DO UPDATE SET last = excluded.last",
                  (session['vid'], now, now))

# the Discord server's members, from its public invite: asked every 10 minutes at most
DISCORD_COUNTS = {'at': 0, 'members': None, 'online': None}

def discord_counts():
    if time.time() - DISCORD_COUNTS['at'] > 600:
        DISCORD_COUNTS['at'] = time.time()
        try:
            req = urllib.request.Request('https://discord.com/api/v10/invites/' + DISCORD.rsplit('/', 1)[1] + '?with_counts=true',
                                         headers = {'User-Agent': 'WynnGuessr (wynndle.com)'})
            with urllib.request.urlopen(req, timeout = 3) as r:
                d = json.loads(r.read())
            DISCORD_COUNTS.update(members = d.get('approximate_member_count'), online = d.get('approximate_presence_count'))
        except Exception:
            pass   # the page goes without them
    return DISCORD_COUNTS

# the visitors as Cloudflare counts them (each one once, since the site went
# behind it), read with a token that may only read wynndle.com's analytics
# (file cloudflare_token next to this one, not in git); else our own count
CLOUDFLARE_TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloudflare_token')
CLOUDFLARE_ZONE = '6123d2ca7e48c20b76cb0da69584f9a5'   # wynndle.com
LAUNCH = '2026-10-15'      # its first day behind Cloudflare
VISITS = {'at': 0, 'count': None}

def cloudflare_visitors():
    if time.time() - VISITS['at'] > 600:
        VISITS['at'] = time.time()
        try:
            with open(CLOUDFLARE_TOKEN_FILE) as f:
                token = f.read().strip()
            query = ('{viewer{zones(filter:{zoneTag:"%s"}){httpRequests1dGroups(limit:1, filter:{date_geq:"%s"}){uniq{uniques}}}}}'
                     % (CLOUDFLARE_ZONE, LAUNCH))
            req = urllib.request.Request('https://api.cloudflare.com/client/v4/graphql', data = json.dumps({'query': query}).encode(),
                                         headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout = 5) as r:
                VISITS['count'] = json.loads(r.read())['data']['viewer']['zones'][0]['httpRequests1dGroups'][0]['uniq']['uniques']
        except Exception:
            pass   # no token, Cloudflare silent: our own count instead
    return VISITS['count']

@app.route("/about")
def about():
    now = time.time()
    with connect() as c:
        one = lambda q, *a: c.execute(q, a).fetchone()[0]
        stats = {
            'online': one("SELECT COUNT(*) FROM visitors WHERE last > ?", now - ONLINE),
            'visitors': cloudflare_visitors() or one("SELECT COUNT(*) FROM visitors"),
            'accounts': one("SELECT COUNT(*) FROM users WHERE COALESCE(guest, 0) = 0"),
            # rooms played to the end, Classic games alone, Survival runs
            'games': one("SELECT COUNT(*) FROM rooms WHERE state = 'finished'")
                     + one("SELECT COUNT(*) FROM scores WHERE room IS NULL AND COALESCE(mode, 'classic') = 'classic'")
                     + one("SELECT COUNT(*) FROM survival_runs WHERE round > 0 AND COALESCE(test, 0) = 0"),
            'guesses': one("SELECT COUNT(*) FROM room_guesses") + one("SELECT COUNT(*) FROM survival_guesses")
                       + one("SELECT COUNT(*) FROM solo_guesses"),
            'locations': one(f"SELECT COUNT(*) FROM locations WHERE review IN {PLAYABLE}"),
        }
    return render_template('about.html', discord = DISCORD, stats = stats, server = discord_counts())

@app.route("/game", methods=['POST', 'GET'])
def game():
    # the mode page sends its settings in the address, so "Play Again" is a plain reload
    form = request.values
    if form.get('mode') == 'survival':
        # Survival has its own page (and no settings but the difficulty)
        return redirect('survival?' + urlencode({'difficulty': form.get('difficulty', 'normal'), 'milk': int(form.get('milk') == 'on')}))
    if 'rounds' in form:
        if form.get('mode') in ('duel', 'royale'):
            return render_template('apology.html', message = "This mode is played with friends: create a room")
        mode = 'survival' if form.get('mode') == 'survival' else 'classic'
        # always the whole map: choosing provinces is for custom games
        provinces = PROVINCES
        #if time limit is not selected, set time limit to -1
        if form.get('time-limit-checkbox') == None:
            time_limit = -1
        #if time limit is selected, check if time limit is a number and greater than 0
        elif form.get('time-limit-checkbox') == 'on':
            #if time limit is not entered, return apology
            if form.get('time-limit') == "":
                return render_template('apology.html', message = "Please enter a time limit")
            #if time limit is not a number, return apology
            if form.get('time-limit').isnumeric() == False:
                return render_template('apology.html', message = "Time limit must be a number")
            #if time limit is less than 1, return apology
            if int(form.get('time-limit')) < 0:
                return render_template('apology.html', message = "Time limit cannot be less than 0 seconds")
            if int(form.get('time-limit')) > 1800:
                return render_template('apology.html', message = "Time limit cannot be greater than 30 minutes")
            time_limit = int(form.get('time-limit'))
        #if look is not selected, set look to False
        look = form.get('look') == 'on'
        rounds = form.get('rounds')

        return render_template('game.html', provinces = provinces, time_limit = time_limit, look = look, rounds = rounds, mode = mode)
    return render_template('game.html', provinces = "['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse', 'fruma']", time_limit = -1, look = False, rounds = 5, mode = 'classic')

# ---------- Accounts ----------

TRIES = 10       # wrong passwords (or recovery codes) for one account from one place...
WINDOW = 900     # ...in this many seconds, then it has to wait

# the recent failures, in the database: the site runs several processes,
# which must all see them (in memory, each had its own count)
with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS fails (place TEXT, name TEXT, at REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS fails_name ON fails (name, at)")

def place():
    # behind Cloudflare or Funnel every request comes from 127.0.0.1: the
    # real address is the last one in X-Forwarded-For, which both write after
    # whatever the player sent. Not CF-Connecting-IP: through Funnel (the old
    # address) a player could write that one himself, and so get around the
    # limits and the bans
    return request.headers.get('X-Forwarded-For', '').split(',')[-1].strip() or request.headers.get('CF-Connecting-IP') or request.remote_addr

# what one address may make in WINDOW: no flood of guests, accounts, rooms, pictures
ACTIONS = {'guest': 10, 'account': 5, 'room': 20, 'picture': 10, 'contact': 6}

with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS actions (place TEXT, what TEXT, at REAL)")
    c.execute("CREATE INDEX IF NOT EXISTS actions_place ON actions (place, what, at)")

def too_often(what):
    # (not for this machine itself: tests and tools; through Cloudflare or
    # Funnel a request always has its player's address)
    if place() in ('127.0.0.1', '::1'):
        return False
    since = time.time() - WINDOW
    with connect() as c:
        c.execute("DELETE FROM actions WHERE at < ?", (since,))
        return c.execute("SELECT COUNT(*) FROM actions WHERE place = ? AND what = ? AND at > ?", (place(), what, since)).fetchone()[0] >= ACTIONS[what]

def done(c, what):
    # counted once made, so a name already taken costs nothing (on the
    # request's own connection: a second one would wait for its transaction)
    c.execute("INSERT INTO actions (place, what, at) VALUES (?, ?, ?)", (place(), what, time.time()))

def too_many(name):
    # also a cap per account whatever the place, a little higher
    since, name = time.time() - WINDOW, name.lower()
    with connect() as c:
        c.execute("DELETE FROM fails WHERE at < ?", (since,))
        here = c.execute("SELECT COUNT(*) FROM fails WHERE name = ? AND place = ? AND at > ?", (name, place(), since)).fetchone()[0]
        anywhere = c.execute("SELECT COUNT(*) FROM fails WHERE name = ? AND at > ?", (name, since)).fetchone()[0]
    return here >= TRIES or anywhere >= 3 * TRIES

def failed(name):
    with connect() as c:
        c.execute("INSERT INTO fails (place, name, at) VALUES (?, ?, ?)", (place(), name.lower(), time.time()))

def stamp(hashed):
    # a trace of the password in the session: when it changes, every other
    # browser logged in with the old one is logged out
    return hashlib.sha256((hashed or '').encode()).hexdigest()[:16]

@app.before_request
def still_logged_in():
    # (not for the pictures: 95 % of the requests, and none needs it)
    # a banned player, guest or not, is logged out of every browser, and
    # their next page tells them why, once (a page: not a script's call, nor
    # a picture, which would use the message up unseen)
    if request.endpoint in ('static', 'play_tile', 'survival_tile'):
        return
    if session.get('user_id'):
        with connect() as c:
            me = c.execute("SELECT password, COALESCE(guest, 0) AS guest, banned_until FROM users WHERE id = ?", (session['user_id'],)).fetchone()
            note = me and (me['banned_until'] or 0) > time.time() and ban_note(c, session['user_id'])
        if note:
            session.clear()
            session['banned'] = note
        elif session.get('loggedin') and not (me and not me['guest'] and session.setdefault('stamp', stamp(me[0])) == stamp(me[0])):
            session.clear()
    if session.get('banned') and request.method == 'GET' and a_page():
        return render_template('apology.html', message = session.pop('banned'), appeal = True), 403

def a_page():
    # a page the player opens, not a script's call nor a picture. Browsers say
    # so (Sec-Fetch-Dest); else the Accept header (its "best" will not do:
    # Chromium's signed-exchange type would rank above text/html)
    dest = request.headers.get('Sec-Fetch-Dest')
    return dest == 'document' if dest else request.accept_mimetypes.best_match(['application/json', 'image/webp', 'text/html']) == 'text/html'

def log_in(c, uid, wynn = False):
    # a banned player stays out: what to tell them comes back instead
    note = ban_note(c, uid)
    if note:
        return note
    seen(c, uid)
    adopt(c, uid)
    session.permanent = True
    session['guest'] = False
    session['loggedin'] = True
    session['user_id'] = uid
    # Wynncraft vouched for this login: a new password needs no old one
    # (that is how a linked account gets back in)
    session['wynn'] = wynn
    session['stamp'] = stamp(c.execute("SELECT password FROM users WHERE id = ?", (uid,)).fetchone()[0])

def clean_name(name):
    return ' '.join(name.split())

def name_problem(c, name, uid = None):
    # the name everyone sees: one per player, whatever the case, and never
    # the Minecraft name Wynncraft proved for someone else
    if not 1 <= len(name) <= 20 or not name.isprintable():
        return "Pick a name of 1 to 20 characters"
    if name_rule(name):
        return name_rule(name)
    if c.execute("""SELECT 1 FROM users WHERE id IS NOT ? AND ((username = ? COLLATE NOCASE AND COALESCE(guest, 0) = 0)
            OR mc_name = ? COLLATE NOCASE)""", (uid, name, name)).fetchone():
        return "This name is taken"

def password_problem(password, confirmation):
    if not 8 <= len(password) <= 64:
        return "Pick a password of 8 to 64 characters"
    if password != confirmation:
        return "Passwords do not match"

def hashed(password):
    return bcrypt.generate_password_hash(password).decode('utf-8')

def plain_code(code):
    # "abcd efgh-ijkl" and "ABCD-EFGH-IJKL" are the same code
    return re.sub(r'[^A-Z0-9]', '', code.upper())

@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.method == 'POST':#user login request
        username = request.form['username']
        password = request.form['password']

        if username == "" or password == "":
            return render_template('apology.html', message = "Please fill in all fields")
        if too_many(username):
            return render_template('apology.html', message = "Too many tries: wait a few minutes")
        with connect() as c:
            user = c.execute("SELECT * FROM users WHERE username = ? AND COALESCE(guest, 0) = 0", (username,)).fetchone()
            if user and user[2] and bcrypt.check_password_hash(user[2], password):
                note = log_in(c, user[0])
                return render_template('apology.html', message = note, appeal = True) if note else redirect(next_page())
        failed(username)
        return render_template('apology.html', message = "Invalid username or password")
    else:
        return render_template('login.html')

@app.route("/register", methods=['POST', 'GET'])
def register():
    if request.method == 'POST':
        username = clean_name(request.form['username'])
        password = request.form['password']
        confirmation = request.form['confirmation']
        with connect() as c:
            problem = (place_note(c) or (too_often('account') and "Too many new accounts from here: wait a few minutes")
                       or name_problem(c, username) or password_problem(password, confirmation))
            if problem:
                return render_template('apology.html', message = problem)
            uid = c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed(password))).lastrowid
            done(c, 'account')
            log_in(c, uid)
            return redirect(next_page())
    else:
        return render_template('register.html')

@app.route("/recover", methods=['POST', 'GET'])
def recover():
    # a forgotten password: the recovery code made on the account page sets a
    # new one, once (a Wynncraft account just logs in with Wynncraft)
    if request.method == 'GET':
        return render_template('recover.html')
    username = request.form.get('username', '')
    if too_many(username):
        return render_template('apology.html', message = "Too many tries: wait a few minutes")
    problem = password_problem(request.form.get('password', ''), request.form.get('confirmation', ''))
    if problem:
        return render_template('apology.html', message = problem)
    with connect() as c:
        user = c.execute("SELECT id, recovery FROM users WHERE username = ? AND COALESCE(guest, 0) = 0", (username,)).fetchone()
        if user and user['recovery'] and bcrypt.check_password_hash(user['recovery'], plain_code(request.form.get('code', ''))):
            c.execute("UPDATE users SET password = ?, recovery = NULL WHERE id = ?", (hashed(request.form['password']), user['id']))
            note = log_in(c, user['id'])
            return render_template('apology.html', message = note, appeal = True) if note else redirect('account?saved=recovered')
    failed(username)
    return render_template('apology.html', message = "Wrong username or recovery code")

@app.route("/logout")
def logout():
    session.clear()
    return redirect('./')

def room_card(page):
    # the card under a shared room link (Discord, WhatsApp...): who waits in
    # it, or how far the game is. Their robots are not logged in: they land
    # here, on the way to the room. A snapshot: Discord keeps it as it was
    m = re.fullmatch(r'room\?code=([A-Za-z0-9]+)', page)
    if not m:
        return None
    with connect() as c:
        r = find_room(c, m.group(1))
        if not r:
            return None
        here = c.execute("SELECT COUNT(*) FROM room_players WHERE code = ? AND last_seen > ?", (r['code'], time.time() - AWAY)).fetchone()[0]
        host = c.execute("SELECT username FROM users WHERE id = ?", (r['host_id'],)).fetchone()
    mode = {'classic': 'Classic', 'duel': 'Duel', 'survival': 'Survival', 'royale': 'Battle Royale'}[r['mode']]
    if r['mode'] == 'survival':
        mode += ' (' + r['difficulty'].capitalize() + (', milk' if r['milk'] else '') + ')'
    players = '%d %s' % (here, 'player' if here == 1 else 'players')
    if r['state'] == 'waiting':
        text = (host[0] + ' is waiting' if here <= 1 and host else players + ' waiting') + ' in the lobby. Hop on!'
    elif r['state'] == 'playing':
        text = 'Game on: round %d, %s.' % (r['round'], players)
    else:
        text = 'This game is over.'
    return {'title': 'Room ' + r['code'] + ' · ' + mode, 'text': text}

@app.route("/guest", methods=['POST', 'GET'])
def guest():
    # multiplayer without an account: just a nickname. A guest is a user row
    # marked guest: no password, and never on the leaderboard
    if request.method == 'GET':
        return render_template('guest.html', card = room_card(next_page()))
    name = ' '.join(request.form.get('username', '').split())
    if not name or len(name) > 20:
        return render_template('apology.html', message = "Pick a nickname of 1 to 20 characters")
    if name_rule(name):
        return render_template('apology.html', message = name_rule(name))
    if too_often('guest'):
        return render_template('apology.html', message = "Too many new nicknames from here: wait a few minutes")
    with connect() as c:
        if place_note(c):
            return render_template('apology.html', message = place_note(c))
        if c.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE AND COALESCE(guest, 0) = 0", (name,)).fetchone():
            return render_template('apology.html', message = "This name belongs to a registered player: pick another one, or log in")
        uid = c.execute("INSERT INTO users (username, password, guest, seen_from) VALUES (?, '', 1, ?)", (name, place())).lastrowid
        done(c, 'guest')
    session.permanent = True
    session['loggedin'] = False
    session['guest'] = True
    session['user_id'] = uid
    return redirect(next_page())

AVATAR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'avatars')   # not in git
PICTURE_MAX = 8 * 1024 * 1024
STEVE = 'https://textures.minecraft.net/texture/31f477eb1a7beee631c2ca64d06f8f68fa93a3386d04452ab27f43acdf1b60cb'

def avatar_url(user):
    # the version changes with the picture, so a browser never shows an old one
    return 'avatar?' + urlencode({'id': user['id'], 'v': user['avatar'] or (user['mc_uuid'] or 'steve')[:8]})

def show_profile(uid):
    with connect() as c:
        user = c.execute("SELECT id, username, mc_name, mc_uuid, avatar FROM users WHERE id = ? AND COALESCE(guest, 0) = 0", (uid,)).fetchone()
        if not user:
            return render_template('apology.html', message = "This player does not exist"), 404
        p = progress(c, uid)
        tags = tags_of(c, [uid])[uid]
        return render_template('profile.html', user = user, username = user['username'], mc_name = user['mc_name'], tags = tags,
                           avatar = avatar_url(user), own = uid == session.get('user_id') and session.get('loggedin'),
                           admin = may(c, 'pictures', uid), moderate = uid != session.get('user_id') and may(c, 'players'),
                           games = p['history'][:30], p = p)

@app.route("/profile")
def profile():
    if not session.get('loggedin'):
        return redirect('login?next=profile')
    return show_profile(session['user_id'])

@app.route("/player", methods=['GET', 'POST'])
def player():
    # anyone's profile, opened from the leaderboard
    uid = request.args.get('id', type = int)
    if request.method == 'POST':
        # the staff takes down a picture that should not be there
        with connect() as c:
            if not may(c, 'pictures', uid):
                return render_template('apology.html', message = "Not allowed"), 403
            drop_picture(c, uid)
            logged(c, 'picture', uid, 'picture taken down')
        return redirect('player?id=' + str(uid))
    return show_profile(uid)

def fetch(url):
    # Mojang's servers: a small answer, quickly, or nothing
    req = urllib.request.Request(url, headers = {'User-Agent': 'WynnGuessr (+https://wynndle.com)'})
    with urllib.request.urlopen(req, timeout = 5) as r:
        return r.read(1_000_000)

def head(uuid):
    # the face of a Minecraft skin, its hat layer on top, fetched from Mojang
    # at most once a day; Steve's without a linked account
    from PIL import Image
    name = re.sub(r'[^0-9a-f]', '', (uuid or '').lower()) or 'steve'
    path = os.path.join(AVATAR_DIR, 'heads', name + '.png')
    try:
        if time.time() - os.path.getmtime(path) < 86400:
            return path
    except OSError:
        pass
    try:
        url = STEVE
        if name != 'steve':
            profile = json.loads(fetch('https://sessionserver.mojang.com/session/minecraft/profile/' + name))
            skin = json.loads(base64.b64decode(profile['properties'][0]['value']))['textures'].get('SKIN')
            url = skin['url'] if skin else STEVE
        if not re.fullmatch(r'https?://textures\.minecraft\.net/texture/[0-9a-f]+', url):
            raise ValueError(url)
        skin = Image.open(io.BytesIO(fetch(url.replace('http://', 'https://', 1)))).convert('RGBA')
        if skin.width != 64 or skin.height not in (32, 64):
            raise ValueError(skin.size)
        face = skin.crop((8, 8, 16, 16))
        face.alpha_composite(skin.crop((40, 8, 48, 16)))
        os.makedirs(os.path.dirname(path), exist_ok = True)
        face.resize((128, 128), Image.Resampling.NEAREST).save(path + '.part', 'PNG')
        os.replace(path + '.part', path)
    except Exception as e:
        # Mojang down: yesterday's head, or Steve's
        app.logger.warning("Minecraft head %s: %r", name, e)
        if not os.path.exists(path):
            return head(None) if name != 'steve' else None
    return path

@app.route("/avatar")
def avatar():
    # a player's picture: the one they sent, else their Minecraft head
    uid = request.args.get('id', type = int)
    with connect() as c:
        user = c.execute("SELECT avatar, avatar_pending, mc_uuid FROM users WHERE id = ?", (uid,)).fetchone()
        if request.args.get('pending') and user and user['avatar_pending'] and (
                uid == session.get('user_id') and session.get('loggedin') or may(c, 'pictures')):
            response = send_from_directory(AVATAR_DIR, user['avatar_pending'] + '.webp', max_age = 600)
            response.cache_control.public, response.cache_control.private = False, True
            return response
    if user and user['avatar']:
        return send_from_directory(AVATAR_DIR, user['avatar'] + '.webp', max_age = 86400)
    path = head(user['mc_uuid'] if user else None)
    return send_file(path, max_age = 3600) if path else ('', 404)

def save_picture(c, uid, upload):
    # any picture becomes a 256 px square webp made here: the file sent is
    # never served itself
    from PIL import Image, ImageOps
    try:
        img = Image.open(upload.stream)
        if img.format not in ('PNG', 'JPEG', 'WEBP', 'GIF') or img.width * img.height > 40_000_000:
            raise ValueError(img.format)
        img = ImageOps.exif_transpose(img).convert('RGBA')
    except Exception:
        return "This file is not a picture"
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    # pixel art stays sharp
    img = img.crop((left, top, left + side, top + side)).resize(
        (256, 256), Image.Resampling.NEAREST if side < 128 else Image.Resampling.LANCZOS)
    name = secrets.token_hex(10)
    os.makedirs(AVATAR_DIR, exist_ok = True)
    img.save(os.path.join(AVATAR_DIR, name + '.webp'), 'WEBP', quality = 85)
    # it waits for the staff before anyone sees it (Yasuro), except the
    # owner's: nobody is above to look at it
    drop_picture(c, uid, 'avatar_pending')
    c.execute("UPDATE users SET avatar_pending = ?, pending_at = ?, avatar_note = NULL WHERE id = ?", (name, time.time(), uid))
    if rank_of(c, uid) == 4:
        approve_picture(c, uid)

def approve_picture(c, uid):
    drop_picture(c, uid)
    c.execute("UPDATE users SET avatar = avatar_pending, avatar_pending = NULL, pending_at = NULL WHERE id = ?", (uid,))

def drop_picture(c, uid, which = 'avatar'):
    # the shown picture (back to the Minecraft head), or the one waiting
    old = c.execute(f"SELECT {which} FROM users WHERE id = ?", (uid,)).fetchone()
    if old and old[0]:
        c.execute(f"UPDATE users SET {which} = NULL WHERE id = ?", (uid,))
        try:
            os.remove(os.path.join(AVATAR_DIR, old[0] + '.webp'))
        except OSError:
            pass

@app.route("/account", methods=['GET', 'POST'])
def account():
    # one's own picture, name, tag, password and recovery code
    if not session.get('loggedin'):
        return redirect('login?next=account')
    uid = session['user_id']
    what = request.args.get('do', '')
    if what == 'picture' and (request.content_length or PICTURE_MAX + 1) > PICTURE_MAX:
        return account_page(what, "Pick a picture under 8 MB")
    if request.method == 'GET':
        return account_page()
    form = request.form
    with connect() as c:
        me = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if what == 'picture':
            problem = ("Too many pictures: wait a few minutes" if too_often('picture') else
                       save_picture(c, uid, request.files['picture']) if 'picture' in request.files else "Pick a picture")
            if not problem:
                done(c, 'picture')
        elif what == 'head':
            problem = drop_picture(c, uid) or drop_picture(c, uid, 'avatar_pending')
        elif what in ('name', 'mc-name'):
            name = me['mc_name'] if what == 'mc-name' else clean_name(form.get('username', ''))
            problem = name_problem(c, name or '', uid)
            if not problem:
                c.execute("UPDATE users SET username = ? WHERE id = ?", (name, uid))
            what = 'name'
        elif what == 'tag':
            label = form.get('tag', '')
            problem = None if label in [t['label'] for t in tags_of(c, [uid])[uid]] else "No such tag"
            if not problem:
                c.execute("UPDATE users SET shown_tag = ? WHERE id = ?", (label, uid))
        elif what == 'password':
            # the old password, unless there is none or Wynncraft vouched for this login
            if me['password'] and not session.get('wynn'):
                if too_many(me['username']):
                    return account_page(what, "Too many tries: wait a few minutes")
                if not bcrypt.check_password_hash(me['password'], form.get('current', '')):
                    failed(me['username'])
                    return account_page(what, "Wrong current password")
            problem = password_problem(form.get('password', ''), form.get('confirmation', ''))
            if not problem:
                new = hashed(form['password'])
                c.execute("UPDATE users SET password = ? WHERE id = ?", (new, uid))
                session['stamp'] = stamp(new)   # this browser stays logged in, the others are out
        elif what == 'code' and me['password']:
            # shown once; only its hash is kept, and a new one replaces the old
            raw = ''.join(secrets.choice(CODE_CHARS) for _ in range(12))
            c.execute("UPDATE users SET recovery = ? WHERE id = ?", (hashed(raw), uid))
            return account_page('code', code = '-'.join((raw[:4], raw[4:8], raw[8:])))
        else:
            return redirect('account')
    if problem:
        return account_page(what, problem)
    return redirect('account?saved=' + what)

def account_page(section = None, error = None, code = None):
    with connect() as c:
        me = c.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        if me['avatar_note'] and request.method == 'GET':
            c.execute("UPDATE users SET avatar_note = NULL WHERE id = ?", (me['id'],))   # said once
        tags = tags_of(c, [me['id']])[me['id']]
    return render_template('account.html', me = me, avatar = avatar_url(me), tags = tags, section = section, error = error,
                           code = code, saved = request.args.get('saved'), need_current = bool(me['password']) and not session.get('wynn'))

def history(c, uid):
    # the player's games, newest first: finished rooms with at least two
    # players (with their place), and solo games (room games also sit in
    # scores, marked with their room: they are not counted twice)
    games = []
    for r in c.execute('''SELECT r.* FROM rooms r JOIN room_players p ON p.code = r.code
            WHERE p.user_id = ? AND r.state = 'finished' ''', (uid,)).fetchall():
        # only who played it live: a finished classic room can be replayed
        # alone later, and that score once moved the win to someone else after
        # the fact (Yasuro: "we all seem to lose our streak randomly")
        live = """SELECT g.user_id, SUM(g.score), MAX(g.at) FROM room_guesses g JOIN room_players p ON p.code = g.code AND p.user_id = g.user_id
            WHERE g.code = ? AND p.live = 1 GROUP BY g.user_id"""
        rows = c.execute(live, (r['code'],)).fetchall()
        totals = {u: t for u, t, _ in rows}
        when = max((at for _, _, at in rows if at), default = None)   # (the oldest guesses have no time)
        if r['mode'] == 'classic':
            st = {}
            players = list(totals)
            key = lambda u: totals[u]
        else:
            st = standings(c, r, r['round'])
            players = list(st)
            key = lambda u: (st[u]['out'] is None, st[u]['left'], st[u]['out'] or 0, totals.get(u, 0))
        if uid not in players or len(players) < 2:
            continue
        rank = 1 + sum(key(u) > key(uid) for u in players)
        games.append({'multi': True, 'code': r['code'], 'mode': r['mode'], 'rank': rank, 'of': len(players), 'win': rank == 1,
                      'score': totals.get(uid, 0), 'rounds': r['round'], 'when': when or 0,
                      'left': st.get(uid, {}).get('left'), 'out': st.get(uid, {}).get('out'),
                      'survived': st.get(uid, {}).get('survived'), 'milk': r['mode'] == 'survival' and r['milk']})
    for g in c.execute('''SELECT score, rounds, time, date, COALESCE(mode, 'classic') AS mode, difficulty, COALESCE(milk, 0) AS milk
            FROM scores WHERE user_id = ? AND room IS NULL''', (uid,)).fetchall():
        try:
            when = time.mktime(time.strptime(g['date'], '%Y-%m-%d'))
        except (TypeError, ValueError):
            when = 0
        games.append({'multi': False, 'mode': g['mode'], 'score': g['score'], 'rounds': g['rounds'],
                      'difficulty': g['difficulty'], 'milk': g['milk'], 'time': g['time'], 'when': when})
    for g in games:
        g['day'] = time.strftime('%b %d, %Y', time.localtime(g['when'])) if g['when'] else ''
    return sorted(games, key = lambda g: g['when'], reverse = True)

# ---------- Levels ----------
# Accounts earn XP by playing (guests do not): 1 XP for every 100 points
# scored, in a room or alone; in survival, which only keeps the streak, 45 XP
# for each spot found (one within 500 blocks is worth about 4,500 points); and
# 50 more for winning a game with friends. Like health and lives, XP is never
# stored: it is worked out again from the games, so the games played before
# levels existed count too. Level L takes 50·L·(L−1) XP in all: each level asks
# 100 XP more than the one before (xp.js has the same formula).

WIN_XP = 50
SPOT_XP = 45

def level_of(xp):
    return (5 + math.isqrt(25 + 2 * xp)) // 10

def level_xp(level):
    # XP needed to reach a level
    return 50 * level * (level - 1)

def solo_xp(score, mode):
    return score * SPOT_XP if mode == 'survival' else score // 100

def room_xp(points, win):
    return points // 100 + (WIN_XP if win else 0)

def progress(c, uid):
    # an account's XP and level, its games, and its wins with friends in a row
    games = history(c, uid)
    best = run = wins = 0
    for g in sorted((g for g in games if g['multi']), key = lambda g: g['when']):
        run = run + 1 if g['win'] else 0
        best = max(best, run)
        wins += g['win']
    # every round played in a room counts, even in a game left unfinished
    xp = (sum(p // 100 for (p,) in c.execute("SELECT SUM(score) FROM room_guesses WHERE user_id = ? GROUP BY code", (uid,)))
          + sum(solo_xp(g['score'], g['mode']) for g in games if not g['multi'])
          + WIN_XP * wins)
    level = level_of(xp)
    return {'xp': xp, 'level': level, 'into': xp - level_xp(level), 'need': level_xp(level + 1) - level_xp(level),
            'games': len(games), 'played': sum(g['multi'] for g in games), 'wins': wins,
            'best': best, 'streak': run, 'history': games}

@app.context_processor
def menu_level():
    # the level shown in the menu, worked out only by the pages that show it
    def mine():
        with connect() as c:
            return progress(c, session['user_id'])
    return {'my_progress': mine}

# ---------- Wynncraft account ----------
# "Log in with Wynncraft" (OAuth2): Wynncraft vouches for the Minecraft
# account, so a linked name on the leaderboard is really that player. The
# application's id and secret live in wynncraft_oauth.json (not in git);
# without that file the button is simply not shown.

WYNN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wynncraft_oauth.json')

def wynn_config():
    try:
        with open(WYNN_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

@app.context_processor
def wynn_button():
    return {'wynn_login': wynn_config() is not None}

def wynn_api(url, data = None, token = None):
    # Cloudflare in front of the API refuses Python's default User-Agent (error 1010)
    headers = {'User-Agent': 'WynnGuessr (+https://wynndle.com)'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data = urlencode(data).encode() if data else None, headers = headers)
    with urllib.request.urlopen(req, timeout = 10) as r:
        return json.load(r)

def wynn_fail(message, appeal = False):
    # these routes sit two folders deep: show the error on the normal page
    return redirect('../../apology?' + urlencode(dict({'message': message}, **({'appeal': 1} if appeal else {}))))

@app.route("/auth/wynncraft")
def wynn_start():
    cfg = wynn_config()
    if not cfg:
        return wynn_fail("Wynncraft login is not set up yet")
    session['wynn_state'] = secrets.token_urlsafe(16)
    session['wynn_next'] = next_page()
    url = cfg['authorize_url']
    return redirect(url + ('&' if '?' in url else '?') + urlencode({'state': session['wynn_state']}))

@app.route("/auth/wynncraft/callback")
def wynn_back():
    cfg = wynn_config()
    state = session.pop('wynn_state', None)
    if not cfg or not state or request.args.get('state') != state:
        return wynn_fail("Wynncraft login failed, please try again")
    if not request.args.get('code'):
        return wynn_fail("Wynncraft login was cancelled")
    try:
        token = wynn_api('https://api.wynncraft.com/v3/oauth/token', {
            'grant_type': 'authorization_code', 'code': request.args['code'], 'redirect_uri': cfg['redirect_uri'],
            'client_id': cfg['client_id'], 'client_secret': cfg['client_secret']})['access_token']
        profiles = wynn_api('https://api.wynncraft.com/v3/oauth/me', token = token)['profiles']
        uuid, profile = sorted(profiles.items(), key = lambda p: not p[1].get('primary'))[0]
        name = profile['username']
    except Exception as e:
        detail = e.read()[:300] if hasattr(e, 'read') else ''
        app.logger.error("Wynncraft login: %r %s", e, detail)
        return wynn_fail("Wynncraft did not answer, please try again")
    with connect() as c:
        owner = c.execute("SELECT id FROM users WHERE mc_uuid = ?", (uuid,)).fetchone()
        if session.get('loggedin'):
            # linking an existing account, from the profile page
            if owner and owner[0] != session['user_id']:
                return wynn_fail("This Minecraft account is already linked to another account")
            c.execute("UPDATE users SET mc_uuid = ?, mc_name = ? WHERE id = ?", (uuid, name, session['user_id']))
            return redirect('../../profile')
        if owner:
            c.execute("UPDATE users SET mc_name = ? WHERE id = ?", (name, owner[0]))  # Minecraft names can change
            uid = owner[0]
        elif c.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE AND COALESCE(guest, 0) = 0", (name,)).fetchone():
            return wynn_fail("An account named " + name + " already exists: log in with its password, then link Wynncraft from your profile")
        elif place_note(c) or too_often('account'):
            # a new account, as on the register page: never from a banned
            # address (another Minecraft account would get round the ban),
            # nor one more than an address may make
            return wynn_fail(place_note(c) or "Too many new accounts from here: wait a few minutes")
        else:
            uid = c.execute("INSERT INTO users (username, password, mc_uuid, mc_name) VALUES (?, '', ?, ?)", (name, uuid, name)).lastrowid
            done(c, 'account')
        note = log_in(c, uid, wynn = True)
    if note:
        return wynn_fail(note, appeal = True)
    return redirect('../../' + session.pop('wynn_next', './'))

@app.route("/apology")
def apology():
    message = request.args.get('message', 'Something went wrong')
    return render_template('apology.html', message = message, appeal = bool(request.args.get('appeal')))

# ---------- Multiplayer rooms ----------
# A room is a fixed list of locations, played live by everyone who joins before
# the end: same round at the same time, the round closes once all have guessed
# (or the clock runs out) and the next one starts by itself after the reveal.
# Modes: classic (most points after N rounds), duel (health points, the
# gap to the round's best guess hurts, more and more each round), survival
# (the solo rules together, plus a shop: see "Survival with friends") and,
# replaced by survival but still replayed for the games played with it,
# royale (lives: the worst guess of a round loses one, a bullseye wins one back).
# Anyone opening a finished classic room plays the same locations alone and
# lands in the same ranking. Rooms only move forward when someone asks: every
# room request first runs tick().

PROVINCES = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse', 'fruma']
ROUNDS = ['3', '5', '10', '25']
MODES = ['classic', 'duel', 'survival']   # royale: no new games
LAST_CALL = 15   # once someone guessed, the others have this long
REVEAL = 10      # the answer stays on screen this long before the next round
AWAY = 10        # a page that stopped polling this long is shown away
GONE = 60        # ...and this long, no round waits for it any more. A tab in the
                 # background can stay silent most of a minute (browsers put its
                 # timers to sleep): with 10 s a player reading Discord lost the
                 # round as soon as someone else guessed (2026-10-18)
HOST_AWAY = 30   # a host gone this long hands the room over (else nobody could start)
GRACE = 1        # guesses still accepted this long after the deadline (network lag)
CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O or 1/I/L to mistype
DUEL_HP = 6000   # duel: everyone's health at the start
LIVES = 3        # royale: everyone's lives at the start
BULLSEYE = 4950  # royale: a guess this good never loses a life, and wins one back
LAST_ROUND = 25  # duel and royale go on until one player is left, this long at most

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY, host_id INTEGER, provinces TEXT, rounds INTEGER,
            time_limit INTEGER, look INTEGER, locations TEXT, state TEXT,
            round INTEGER, round_start REAL, round_end REAL, next_code TEXT,
            mode TEXT DEFAULT 'classic');
        CREATE TABLE IF NOT EXISTS room_players (
            code TEXT, user_id INTEGER, live INTEGER, last_seen REAL,
            recorded INTEGER DEFAULT 0, seat INTEGER DEFAULT 0, PRIMARY KEY (code, user_id));
        CREATE TABLE IF NOT EXISTS room_guesses (
            code TEXT, user_id INTEGER, round INTEGER, x REAL, z REAL, score INTEGER,
            at REAL, time REAL, PRIMARY KEY (code, user_id, round));
        CREATE TABLE IF NOT EXISTS room_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, user_id INTEGER, at REAL, text TEXT);
        CREATE TABLE IF NOT EXISTS room_bans (
            code TEXT, user_id INTEGER, PRIMARY KEY (code, user_id));
    ''')
    # the scores table comes with the original game, which had no modes
    if 'mode' not in [col[1] for col in c.execute("PRAGMA table_info(scores)")]:
        c.execute("ALTER TABLE scores ADD COLUMN mode TEXT DEFAULT 'classic'")
    # a game played in a room keeps its room code, so the profile does not list it twice
    if 'room' not in [col[1] for col in c.execute("PRAGMA table_info(scores)")]:
        c.execute("ALTER TABLE scores ADD COLUMN room TEXT")
    # guests: players with a nickname and no account
    if 'guest' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN guest INTEGER DEFAULT 0")
    # Wynncraft account linked to this one (see /auth/wynncraft)
    if 'mc_uuid' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN mc_uuid TEXT")
        c.execute("ALTER TABLE users ADD COLUMN mc_name TEXT")
    # the picture sent (a file in avatars/; none = the Minecraft head) and the
    # hash of the recovery code (see /account)
    if 'avatar' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN avatar TEXT")
        c.execute("ALTER TABLE users ADD COLUMN recovery TEXT")
    # review of the locations (see /review): 'old' = from the original game,
    # 'new' = a fresh capture not checked yet, 'kept', 'deleted'
    if 'review' not in [col[1] for col in c.execute("PRAGMA table_info(locations)")]:
        c.execute("ALTER TABLE locations ADD COLUMN review TEXT DEFAULT 'old'")
        c.execute("ALTER TABLE locations ADD COLUMN difficulty TEXT")

def room_tx():
    # room requests read then write: taking the write lock first means two
    # requests can never both move the same room forward
    c = connect()
    c.execute('BEGIN IMMEDIATE')
    return c

def find_room(c, code):
    return c.execute("SELECT * FROM rooms WHERE code = ? COLLATE NOCASE", (code.strip(),)).fetchone()

def room_settings(form):
    # the same choices as the mode page; returns (settings, error)
    mode = form.get('mode', 'classic')
    if mode not in MODES:
        return None, "Unknown game mode"
    if mode == 'survival':
        # as alone: every province, the view free, the clock of the difficulty
        if form.get('difficulty') not in DIFFICULTIES:
            return None, "Unknown difficulty"
        return {'mode': mode, 'provinces': PROVINCES, 'rounds': SURVIVAL_ROUNDS, 'time_limit': -1, 'look': 0,
                'difficulty': form['difficulty'], 'milk': int(form.get('milk') == 'on')}, None
    provinces = [p for p in PROVINCES if p in form.getlist('province')]
    if not provinces:
        return None, "Please select at least one province"
    if mode == 'classic' and form.get('rounds') not in ROUNDS:
        return None, "Invalid number of rounds"
    time_limit = -1
    if form.get('time-limit-checkbox') == 'on':
        t = form.get('time-limit', '')
        if not t.isnumeric() or not 0 < int(t) <= 1800:
            return None, "Time limit must be between 1 and 1800 seconds"
        time_limit = int(t)
    return {'mode': mode, 'provinces': provinces, 'rounds': int(form['rounds']) if mode == 'classic' else LAST_ROUND,
            'time_limit': time_limit, 'look': int(form.get('look') == 'on'), 'difficulty': None, 'milk': 0}, None

def pick_locations(c, s):
    # survival: only places with their fog photo, when there are enough, so
    # that Blindness can always be thrown
    fog = ''
    if s['mode'] == 'survival' and c.execute(f"SELECT COUNT(*) FROM locations WHERE review IN {PLAYABLE} AND fog_url IS NOT NULL"
                                             ).fetchone()[0] >= s['rounds']:
        fog = ' AND fog_url IS NOT NULL'
    ids = [r[0] for r in c.execute(
        f"SELECT location_id FROM locations WHERE province IN ({', '.join('?' * len(s['provinces']))}) AND review IN {PLAYABLE}{fog} ORDER BY RANDOM() LIMIT ?",
        (*s['provinces'], s['rounds']))]
    return json.dumps(ids) if len(ids) == s['rounds'] else None

def new_room(c, host, s, world = None):
    # a world (see "Multiplayer: worlds") has no host, and nobody in it yet
    locations = pick_locations(c, s)
    if not locations:
        return None
    code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    while find_room(c, code):
        code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    c.execute('''INSERT INTO rooms (code, host_id, mode, provinces, rounds, time_limit, look, locations, state, round, round_start, difficulty, milk, world)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 0, 0, ?, ?, ?)''',
        (code, host, s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations, s['difficulty'], s['milk'], world))
    if host:
        c.execute("INSERT INTO room_players (code, user_id, live, last_seen, joined) VALUES (?, ?, 1, ?, ?)", (code, host, time.time(), time.time()))
    return code

PERFECT = 2      # a guess this close (in blocks) is a perfect 5,000; game.js has the same

def guess_score(x, z, loc):
    # same formula as game.js
    d = ((loc['x_position'] - x) ** 2 + (loc['z_position'] - z) ** 2) ** .5
    return 5000 if d <= PERFECT else max(0, round(5200 / (1 + .002 * math.e ** (.0042 * d + 3)) + .822))

def round_deadline(c, r):
    # the time limit, cut short LAST_CALL seconds after the first guess;
    # returns (deadline or None, name of the first player who guessed or None)
    first = c.execute('''SELECT u.username, g.at FROM room_guesses g JOIN users u ON u.id = g.user_id
        WHERE g.code = ? AND g.round = ? AND g.x IS NOT NULL ORDER BY g.at LIMIT 1''', (r['code'], r['round'])).fetchone()
    ends = [r['round_start'] + r['time_limit']] if r['time_limit'] > 0 else []
    if first:
        ends.append(first['at'] + LAST_CALL)
    return min(ends, default=None), first and first['username']

def multiplier(n):
    # duel: damage grows from the third round on, so that nobody is ever safe
    return 1 if n <= 2 else 1 + (n - 2) / 2

def standings(c, r, upto):
    # duel and royale: replay the rounds up to `upto` for each contestant's
    # health or lives: {user_id: {'left', 'out', 'delta'}}, where out is the
    # round they were knocked out in and delta their change in round `upto`
    # (survival: hearts, and much more, see survivors())
    if r['mode'] == 'survival':
        return survivors(c, r, upto)
    seats = [p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND seat = 1 ORDER BY rowid", (r['code'],))]
    scores = {(g[0], g[1]): g[2] for g in c.execute("SELECT user_id, round, score FROM room_guesses WHERE code = ? AND round <= ?",
                                                     (r['code'], upto))}
    st = {u: {'left': DUEL_HP if r['mode'] == 'duel' else LIVES, 'out': None, 'delta': 0} for u in seats}
    for n in range(1, upto + 1):
        alive = [u for u in seats if st[u]['out'] is None]
        if len(alive) <= 1:
            break
        s = {u: scores.get((u, n), 0) for u in alive}
        best, worst = max(s.values()), min(s.values())
        for u in alive:
            if r['mode'] == 'duel':
                d = -min(st[u]['left'], round((best - s[u]) * multiplier(n)))
            elif s[u] >= BULLSEYE:
                d = int(st[u]['left'] < LIVES)  # a bullseye is always safe, and heals
            else:
                d = -int(s[u] == worst < best)
            st[u]['left'] += d
            if n == upto:
                st[u]['delta'] = d
            if st[u]['left'] <= 0:
                st[u]['out'] = n
    return st

def guessers(c, r):
    # who plays the current round: every live player in classic, the
    # contestants still standing in duel and royale
    if r['mode'] == 'classic':
        return {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND live = 1", (r['code'],))}
    return {u for u, p in standings(c, r, r['round'] - 1).items() if p['out'] is None}

def record(c, r, uid):
    # a finished classic room game also counts for the leaderboard and the profile (not for guests)
    if c.execute("SELECT recorded FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()[0]:
        return
    if c.execute("SELECT COALESCE(guest, 0) FROM users WHERE id = ?", (uid,)).fetchone()[0]:
        return
    c.execute("UPDATE room_players SET recorded = 1 WHERE code = ? AND user_id = ?", (r['code'], uid))
    total, spent, guessed = c.execute('''SELECT COALESCE(SUM(score), 0), COALESCE(SUM(time), 0), COUNT(x)
        FROM room_guesses WHERE code = ? AND user_id = ?''', (r['code'], uid)).fetchone()
    if guessed:
        c.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, room) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (uid, total, date.today(), 'Yes' if r['look'] else 'No', str(json.loads(r['provinces'])),
                   r['rounds'], round(spent, 2), r['code']))

def next_round(c, r):
    over = r['round'] >= r['rounds']
    if r['mode'] != 'classic':
        over = over or sum(p['out'] is None for p in standings(c, r, r['round']).values()) <= 1
    if not over:
        c.execute("UPDATE rooms SET round = round + 1, round_start = ?, round_end = NULL WHERE code = ?",
                  (time.time(), r['code']))
    else:
        c.execute("UPDATE rooms SET state = 'finished' WHERE code = ?", (r['code'],))
        if r['mode'] == 'classic':
            for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND live = 1", (r['code'],)).fetchall():
                record(c, r, p['user_id'])

def tick(c, r):
    # close the round once nobody is left to wait for, then move on after the reveal
    now = time.time()
    if r['world'] and r['state'] != 'playing':
        return world_tick(c, r)
    if r['state'] != 'playing':
        host = c.execute("SELECT last_seen FROM room_players WHERE code = ? AND user_id = ?", (r['code'], r['host_id'])).fetchone()
        if host and host[0] > now - HOST_AWAY:
            return r
        heir = c.execute("SELECT user_id FROM room_players WHERE code = ? AND live = 1 AND last_seen > ? ORDER BY rowid LIMIT 1",
                         (r['code'], now - AWAY)).fetchone()
        if heir:
            c.execute("UPDATE rooms SET host_id = ? WHERE code = ?", (heir[0], r['code']))
        return find_room(c, r['code'])
    if r['mode'] == 'survival':
        return survival_room_tick(c, r)
    if r['round_end'] is None:
        deadline, _ = round_deadline(c, r)
        here = {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND last_seen > ?", (r['code'], now - GONE))}
        done = {g[0] for g in c.execute("SELECT user_id FROM room_guesses WHERE code = ? AND round = ?", (r['code'], r['round']))}
        if (guessers(c, r) & here) - done and (deadline is None or now < deadline + GRACE):
            return r
        c.execute("UPDATE rooms SET round_end = ? WHERE code = ?", (now, r['code']))
    elif now >= r['round_end'] + REVEAL:
        next_round(c, r)
    return find_room(c, r['code'])

def member(c, code):
    # (room, player row) for the logged-in player, or (None, None)
    r = find_room(c, code)
    uid = session.get('user_id')
    me = r and uid and c.execute("SELECT * FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()
    return (r, me) if me else (None, None)

def name_clash(c, code, uids):
    # names tell players apart on screen: is someone else in this room named
    # like one of these players?
    marks = ','.join('?' * len(uids))
    return bool(c.execute(f'''SELECT 1 FROM room_players p JOIN users u ON u.id = p.user_id
        WHERE p.code = ? AND p.user_id NOT IN ({marks})
        AND u.username COLLATE NOCASE IN (SELECT username FROM users WHERE id IN ({marks}))''', [code] + uids + uids).fetchone())

@app.route("/room/create", methods=['POST'])
def room_create():
    if not session.get('user_id'):
        return redirect('../guest?next=' + quote('mode?play=friends'))
    s, error = room_settings(request.form)
    if error or too_often('room'):
        return render_template('apology.html', message = error or "Too many new rooms: wait a few minutes")
    with room_tx() as c:
        code = new_room(c, session['user_id'], s)
        if code:
            done(c, 'room')
    if not code:
        return render_template('apology.html', message = "Not enough locations in these provinces")
    return redirect('../room?code=' + code)

@app.route("/room")
def room():
    code = request.args.get('code', '').strip()
    if not session.get('user_id'):
        return redirect('guest?next=' + quote('room?code=' + code))
    with room_tx() as c:
        r = find_room(c, code)
        if not r:
            return render_template('apology.html', message = "No room with the code " + code)
        ban = c.execute("SELECT why FROM room_bans WHERE code = ? AND user_id = ?", (r['code'], session['user_id'])).fetchone()
        if ban:
            # not ready when a world's game started: back to the worlds, with a word why
            if ban['why'] == 'away':
                return redirect('multiplayer?missed=1')
            return render_template('apology.html', message = "The host removed you from this room")
        clash = name_clash(c, r['code'], [session['user_id']])
        if r['world'] and not c.execute("SELECT 1 FROM room_players WHERE code = ? AND user_id = ?", (r['code'], session['user_id'])).fetchone() \
                and (r['state'] != 'waiting' or world_here(c, r['code']) >= WORLD_MAX or clash):
            # started, full, or someone there has this name: another lobby of the same world
            return redirect('multiplayer?join=' + r['world'])
        if clash:
            return render_template('apology.html', message = "Someone in this room already has your name: pick another nickname")
        # joining before the end means playing live, even mid-game; a finished
        # classic room can still be played alone, the other modes only looked at
        c.execute("INSERT OR IGNORE INTO room_players (code, user_id, live, last_seen, joined) VALUES (?, ?, ?, ?, ?)",
                  (r['code'], session['user_id'], int(r['state'] != 'finished' or r['mode'] != 'classic'), time.time(), time.time()))
        # (here at once: a reload comes after the page it replaces said it was gone)
        c.execute("UPDATE room_players SET last_seen = ? WHERE code = ? AND user_id = ?", (time.time(), r['code'], session['user_id']))
        seen(c, session['user_id'])
    return render_template('room.html', code = r['code'], world = r['world'] and world_info(r['world']),
                           guest = not session.get('loggedin'))

@app.route("/api/room/<code>")
def room_state(code):
    # the "#1" tags, when due, before the room's write lock: never while holding it
    if time.time() - TOPS['at'] > TOPS_EVERY:
        top_tags(connect())
    with room_tx() as c:
        r, me = member(c, code)
        if not r:
            return jsonify({"success": False})
        now = time.time()
        c.execute("UPDATE room_players SET last_seen = ? WHERE code = ? AND user_id = ? AND last_seen < ?",
                  (now, r['code'], me['user_id'], now - 2))
        r = tick(c, r)
        live = bool(me['live'])
        # live players follow the room's round, the others pick any round they reached
        if live:
            n = r['round']
        else:
            done = c.execute("SELECT COUNT(*) FROM room_guesses WHERE code = ? AND user_id = ?",
                             (r['code'], me['user_id'])).fetchone()[0]
            n = min(done + 1, r['rounds'])
            if request.args.get('round', '').isnumeric():
                n = max(1, min(n, int(request.args['round'])))
        players = c.execute('''SELECT p.user_id AS uid, u.username AS name, p.user_id = ? AS you, p.user_id = ? AS host,
                p.seat, p.last_seen > ? AS here, p.lobby_ready, COALESCE(SUM(g.score), 0) AS total, COUNT(g.round) AS played,
                COALESCE(MAX(g.round = ?), 0) AS guessed
            FROM room_players p JOIN users u ON u.id = p.user_id
            LEFT JOIN room_guesses g ON g.code = p.code AND g.user_id = p.user_id
            WHERE p.code = ? GROUP BY p.user_id ORDER BY p.rowid''',
            (me['user_id'], r['host_id'], now - AWAY, n, r['code'])).fetchall()
        # duel and royale: health or lives after the last finished round
        st = {}
        if r['mode'] in ('duel', 'royale') and r['state'] != 'waiting':
            st = standings(c, r, r['round'] if r['state'] == 'finished' or r['round_end'] is not None else r['round'] - 1)
        out = {"success": True, "code": r['code'], "mode": r['mode'], "state": r['state'],
               "host": r['host_id'] == me['user_id'], "live": live, "round": n, "rounds": r['rounds'],
               "next": r['next_code'],
               "settings": {"mode": r['mode'], "provinces": json.loads(r['provinces']), "rounds": r['rounds'],
                            "time_limit": r['time_limit'], "look": bool(r['look'])},
               # the colour of a player is their place in the join order
               "players": [dict(p, color = i, **st.get(p['uid'], {})) for i, p in enumerate(players)]}
        if r['world']:
            out['world'] = world_info(r['world'])
            out['ready'] = bool(me['lobby_ready'])
            if r['state'] == 'waiting' and r['starts_at']:
                out['starts_in'] = max(0, r['starts_at'] - now)
            if r['state'] == 'finished' and not r['next_code']:
                out['next_in'] = max(0, (r['round_end'] or now) + REVEAL + WORLD_RESULTS - now)
        # the tag next to each name (Moderation: staff rank, a tag, a "#1")
        tags = tag_of(c, [p['uid'] for p in players])
        for p in out['players']:
            p['tag'] = tags.get(p['uid'])
        # chat: the messages the page has not seen yet (it says which was its last),
        # but none the staff hid, and none of the players this one ignores
        colors = {p['uid']: p['color'] for p in out['players']}
        since = request.args.get('chat', '')
        ignored = {i[0] for i in c.execute("SELECT target FROM ignores WHERE user_id = ?", (me['user_id'],))}
        out['chat'] = [dict(m, color = colors.get(m['uid'], 0)) for m in reversed(c.execute(
            '''SELECT m.id, m.user_id AS uid, u.username AS name, m.text FROM room_chat m JOIN users u ON u.id = m.user_id
            WHERE m.code = ? AND m.id > ? AND m.hidden_by IS NULL ORDER BY m.id DESC LIMIT 50''',
            (r['code'], int(since) if since.isnumeric() else 0)).fetchall()) if m['uid'] not in ignored]
        # players keep their id: the host's tools (make host, kick) name them by it;
        # a message does not, but the staff learns which ones it may hide.
        # (Who wrote and has left the room: looked up all at once, not message by message)
        rank, writers = my_rank(c), {p['uid'] for p in out['chat']}
        tags.update(tag_of(c, writers - set(tags)))
        ranks = ranks_of(c, writers) if rank >= MAY['hide'] else {}
        for p in out['chat']:
            p['tag'] = tags.get(p['uid'])
            if rank >= MAY['hide'] and ranks[p['uid']] < rank:
                p['hide'] = True
            del p['uid']
        # hidden after the page showed them: it takes them away
        out['hidden'] = [m[0] for m in c.execute("SELECT id FROM room_chat WHERE code = ? AND hidden_by IS NOT NULL", (r['code'],))]
        for p in out['players']:
            if p['uid'] in ignored:
                p['ignored'] = True
        muted = (c.execute("SELECT muted_until FROM users WHERE id = ?", (me['user_id'],)).fetchone()[0] or 0) - now
        if muted > 0:
            out['muted'] = how_long(muted)
        if r['mode'] == 'duel':
            out['multiplier'] = multiplier(max(n, 1))
        if r['mode'] == 'survival':
            out['settings'].update({"difficulty": r['difficulty'], "milk": bool(r['milk'])})
            return jsonify(survival_view(c, r, me, out, now))
        if n == 0 or (live and r['state'] == 'waiting'):
            return jsonify(out)
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (json.loads(r['locations'])[n - 1],)).fetchone()
        out['url'] = tile_url(c, loc['location_id'], 'room:%s:%d' % (r['code'], n))
        out['answered'] = bool(c.execute("SELECT 1 FROM room_guesses WHERE code = ? AND user_id = ? AND round = ?",
                                         (r['code'], me['user_id'], n)).fetchone())
        # false for whoever only watches: knocked out, or arrived after the start of a duel or royale
        out['playing'] = not live or (r['state'] == 'playing' and me['user_id'] in guessers(c, r))
        if live and r['state'] == 'playing' and r['round_end'] is None:
            deadline, first = round_deadline(c, r)
            if deadline:
                out['time_left'] = max(0, deadline - now)
            out['first'] = first
        elif live or out['answered']:
            # the round is over for this player: everyone's guesses can be shown;
            # upto: total up to this round, so that a late player compares like with like
            out['reveal'] = {"X": loc['x_position'], "Z": loc['z_position'], "guesses": [dict(g) for g in c.execute(
                '''SELECT u.username AS name, g.x, g.z, g.score, (SELECT SUM(h.score) FROM room_guesses h
                    WHERE h.code = g.code AND h.user_id = g.user_id AND h.round <= g.round) AS upto
                FROM room_guesses g JOIN users u ON u.id = g.user_id WHERE g.code = ? AND g.round = ?''', (r['code'], n))]}
            if live and r['state'] == 'playing':
                out['next_in'] = max(0, r['round_end'] + REVEAL - now)
                # load the next picture during the reveal: everyone has it when the round starts
                ids = json.loads(r['locations'])
                if n < len(ids):
                    out['next_url'] = tile_url(c, ids[n], 'room:%s:%d' % (r['code'], n + 1))
        return jsonify(out)

@app.route("/api/room/<code>/chat", methods=['POST'])
def room_chat(code):
    text = ' '.join(request.form.get('text', '').split())[:200]
    shown = filtered(text)   # before the room's write lock, which every room waits for
    with room_tx() as c:
        r, me = member(c, code)
        if not r or not text:
            return jsonify({"success": False})
        muted = (c.execute("SELECT muted_until FROM users WHERE id = ?", (me['user_id'],)).fetchone()[0] or 0) - time.time()
        if muted > 0:
            return jsonify({"success": False, "error": "You are muted for " + how_long(muted)})
        last = c.execute("SELECT MAX(at) FROM room_chat WHERE code = ? AND user_id = ?", (r['code'], me['user_id'])).fetchone()[0]
        if last and time.time() - last < 0.7:
            return jsonify({"success": False, "error": "Slow down a little"})
        c.execute("INSERT INTO room_chat (code, user_id, at, text, raw) VALUES (?, ?, ?, ?, ?)",
                  (r['code'], me['user_id'], time.time(), shown, text if shown != text else None))
    return jsonify({"success": True})

@app.route("/api/room/<code>/report", methods=['POST'])
def room_report(code):
    # a player reports a message of someone else: it waits in Moderation
    mid = request.form.get('id', type = int)
    with room_tx() as c:
        r, me = member(c, code)
        m = r and c.execute("SELECT user_id FROM room_chat WHERE id = ? AND code = ? AND hidden_by IS NULL", (mid, r['code'])).fetchone()
        if not m or m['user_id'] == me['user_id']:
            return jsonify({"success": False})
        if c.execute("SELECT COUNT(*) FROM chat_reports WHERE by = ? AND at > ?", (me['user_id'], time.time() - 600)).fetchone()[0] >= REPORTS_MAX:
            return jsonify({"success": False, "error": "That's a lot of reports! The staff is on it"})
        c.execute("INSERT OR IGNORE INTO chat_reports (message, by, at) VALUES (?, ?, ?)", (mid, me['user_id'], time.time()))
    return jsonify({"success": True})

@app.route("/api/room/<code>/ignore", methods=['POST'])
def room_ignore(code):
    # stop seeing someone's messages, in every room (undo: see them again)
    with room_tx() as c:
        r, me = member(c, code)
        if not r:
            return jsonify({"success": False})
        if request.form.get('undo'):
            c.execute("DELETE FROM ignores WHERE user_id = ? AND target = ?", (me['user_id'], request.form.get('uid', type = int)))
            return jsonify({"success": True})
        m = c.execute("SELECT m.user_id, u.username FROM room_chat m JOIN users u ON u.id = m.user_id WHERE m.id = ? AND m.code = ?",
                      (request.form.get('id', type = int), r['code'])).fetchone()
        if not m or m['user_id'] == me['user_id']:
            return jsonify({"success": False})
        c.execute("INSERT OR IGNORE INTO ignores (user_id, target, at) VALUES (?, ?, ?)", (me['user_id'], m['user_id'], time.time()))
    return jsonify({"success": True, "uid": m['user_id'], "name": m['username']})

@app.route("/api/room/<code>/settings", methods=['POST'])
def room_set(code):
    # host only, before the start: new settings mean new locations
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['host_id'] != me['user_id'] or r['state'] != 'waiting':
            return jsonify({"success": False, "error": "Only the host can change the settings before the start"})
        s, error = room_settings(request.form)
        locations = s and pick_locations(c, s)
        if not locations:
            return jsonify({"success": False, "error": error or "Not enough locations in these provinces"})
        c.execute("""UPDATE rooms SET mode = ?, provinces = ?, rounds = ?, time_limit = ?, look = ?, locations = ?, difficulty = ?, milk = ?
                WHERE code = ?""", (s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations,
                s['difficulty'], s['milk'], r['code']))
    return jsonify({"success": True})

@app.route("/api/room/<code>/host", methods=['POST'])
def room_host(code):
    # host only: hands the room over to another player who is here
    with room_tx() as c:
        r, me = member(c, code)
        uid = request.form.get('uid', type = int)
        if not r or r['host_id'] != me['user_id'] or not c.execute(
                "SELECT 1 FROM room_players WHERE code = ? AND user_id = ? AND live = 1 AND last_seen > ?",
                (r['code'], uid, time.time() - AWAY)).fetchone():
            return jsonify({"success": False})
        c.execute("UPDATE rooms SET host_id = ? WHERE code = ?", (uid, r['code']))
    return jsonify({"success": True})

@app.route("/api/room/<code>/kick", methods=['POST'])
def room_kick(code):
    # host only, before the start: the player leaves and cannot come back
    # (their page reloads on the room, which says so)
    with room_tx() as c:
        r, me = member(c, code)
        uid = request.form.get('uid', type = int)
        if not r or r['host_id'] != me['user_id'] or r['state'] != 'waiting' or uid == me['user_id']:
            return jsonify({"success": False})
        c.execute("DELETE FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid))
        c.execute("INSERT OR IGNORE INTO room_bans (code, user_id) VALUES (?, ?)", (r['code'], uid))
    return jsonify({"success": True})

@app.route("/api/room/<code>/start", methods=['POST'])
def room_start(code):
    # host only: starts the game, or cuts a reveal short
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['host_id'] != me['user_id']:
            return jsonify({"success": False})
        r = tick(c, r)
        now = time.time()
        if r['state'] == 'waiting':
            if r['mode'] != 'classic':
                # the players here now are the contestants; whoever comes later watches
                here = c.execute("SELECT COUNT(*) FROM room_players WHERE code = ? AND live = 1 AND last_seen > ?",
                                 (r['code'], now - AWAY)).fetchone()[0]
                if here < 2:
                    return jsonify({"success": False, "error": "This mode needs at least 2 players"})
                c.execute("UPDATE room_players SET seat = (last_seen > ?) WHERE code = ? AND live = 1", (now - AWAY, r['code']))
            # survival: the first picture loads unseen for PREP seconds, like all the others
            c.execute("UPDATE rooms SET state = 'playing', round = 1, round_start = ?, round_end = NULL WHERE code = ?",
                      (now + (PREP if r['mode'] == 'survival' else 0), r['code']))
        elif r['state'] == 'playing' and r['round_end'] is not None and r['mode'] == 'survival':
            # survival: the reveal only, straight to the shop (the shop waits for everyone)
            if now >= r['round_end'] + REVEAL:
                return jsonify({"success": False})
            c.execute("UPDATE rooms SET round_end = ? WHERE code = ?", (now - REVEAL, r['code']))
        elif r['state'] == 'playing' and r['round_end'] is not None:
            next_round(c, r)
        else:
            return jsonify({"success": False})
    return jsonify({"success": True})

@app.route("/api/room/<code>/guess", methods=['POST'])
def room_guess(code):
    with room_tx() as c:
        r, me = member(c, code)
        if not r:
            return jsonify({"success": False})
        r = tick(c, r)
        now = time.time()
        n = request.form.get('round', '')
        n = int(n) if n.isnumeric() else 0
        if r['mode'] == 'survival':
            return jsonify({"success": survival_room_guess(c, r, me, n)})
        if me['live']:
            if (r['state'] != 'playing' or n != r['round'] or r['round_end'] is not None
                    or me['user_id'] not in guessers(c, r)):
                return jsonify({"success": False})
            spent = now - r['round_start']
        else:
            done = c.execute("SELECT COUNT(*) FROM room_guesses WHERE code = ? AND user_id = ?",
                             (r['code'], me['user_id'])).fetchone()[0]
            if n != done + 1 or n > r['rounds']:
                return jsonify({"success": False})
            try:
                spent = min(max(float(request.form.get('time', 0)), 0), 3600)
            except ValueError:
                spent = 0
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (json.loads(r['locations'])[n - 1],)).fetchone()
        x = z = None
        score = 0  # the clock ran out with no marker on the map
        if request.form.get('x'):
            try:
                x, z = float(request.form['x']), float(request.form['z'])
            except (KeyError, ValueError):
                return jsonify({"success": False})
            if not (math.isfinite(x) and math.isfinite(z)):
                return jsonify({"success": False})
            score = guess_score(x, z, loc)
        c.execute("INSERT OR IGNORE INTO room_guesses (code, user_id, round, x, z, score, at, time) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (r['code'], me['user_id'], n, x, z, score, now, spent))
        if not me['live'] and n == r['rounds']:
            record(c, r, me['user_id'])
    return jsonify({"success": True})

@app.route("/api/room/<code>/again", methods=['POST'])
def room_again(code):
    # host only, once finished: same settings, new locations, everyone follows
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['host_id'] != me['user_id'] or r['state'] != 'finished':
            return jsonify({"success": False})
        nxt = r['next_code']
        if not nxt:
            # a battle royale goes on as survival, which replaced it
            mode = 'survival' if r['mode'] == 'royale' else r['mode']
            nxt = new_room(c, me['user_id'], {'mode': mode, 'provinces': PROVINCES if mode == 'survival' else json.loads(r['provinces']),
                                              'rounds': SURVIVAL_ROUNDS if mode == 'survival' else r['rounds'],
                                              'time_limit': r['time_limit'], 'look': r['look'],
                                              'difficulty': r['difficulty'] or ('normal' if mode == 'survival' else None),
                                              'milk': r['milk'] or 0})
            c.execute("UPDATE rooms SET next_code = ? WHERE code = ?", (nxt, r['code']))
    return jsonify({"success": bool(nxt), "code": nxt})

@app.route("/api/room/<code>/xp")
def room_level(code):
    # for the end screen: the XP this game brought, the total it reaches, and
    # the wins in a row if it was one (guests earn none)
    with connect() as c:
        r, me = member(c, code)
        if not r or r['state'] != 'finished':
            return jsonify({"success": False})
        if not session.get('loggedin'):
            return jsonify({"success": False, "guest": True})
        p = progress(c, me['user_id'])
        win = any(g['win'] for g in p['history'] if g.get('code') == r['code'])
        points = c.execute("SELECT COALESCE(SUM(score), 0) FROM room_guesses WHERE code = ? AND user_id = ?",
                           (r['code'], me['user_id'])).fetchone()[0]
    return jsonify({"success": True, "xp": p['xp'], "gained": room_xp(points, win), "bonus": WIN_XP if win else 0,
                    "streak": p['streak'] if win else 0})

# ---------- Captures and review ----------
# The Wynndle Panorama mod (mod/) sends each panorama here as it is taken; it
# shows up as a 'new' location, not played until Yasuro reviews it on /review:
# keep or delete. A click on the review map plans a spot
# ('planned'): in a downloaded copy of the world, the mod flies to each one,
# takes it and sends it back as 'new'. The mod also sends which chunks the
# copy holds, shown as a grey veil over the rest. Only works where a
# capture_key file exists (the beta).
CAPTURE_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'capture_key')
CAPTURE_DIR = os.path.join(app.static_folder, 'captures')
TILES_DIR = os.path.join(app.static_folder, 'tiles')   # a link to /data: big
CUBE, TILE = 4096, 512   # multires: same numbers in panoramaConfig() (game, room, review)
COVERAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'coverage.json')
REVIEWERS = (1, 3)   # user ids (names can be changed): Yasuro, kemmi
PUBLISHER = (1,)     # the only one who may push to the live site: Yasuro
# the live site's database, next to this checkout: ~/Wynnguessr beside ~/Wynnguessr-beta
LIVE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'Wynnguessr', 'database.db')
REVIEW_PROVINCES = PROVINCES

def capture_key():
    try:
        with open(CAPTURE_KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def key_ok():
    key = capture_key()
    return bool(key) and secrets.compare_digest(request.headers.get('X-Wynndle-Key', ''), key)

def is_reviewer(only=REVIEWERS):
    return bool(session.get('loggedin') and capture_key()) and session.get('user_id') in only

def guess_province(c, x, z):
    # Fruma has no location yet to learn from; elsewhere, the nearest one
    # decides (deleted ones too: their province is still right)
    if x < -1000 and z > -2000:
        return 'fruma'
    near = c.execute("""SELECT province FROM locations WHERE review IN ('old', 'kept', 'deleted')
        ORDER BY (x_position - ?) * (x_position - ?) + (z_position - ?) * (z_position - ?) LIMIT 1""",
        (x, x, z, z)).fetchone()
    return near['province'] if near else 'wynn'

@app.route("/api/capture", methods=['POST'])
def capture():
    if not key_ok():
        return jsonify({"success": False}), 403
    try:
        x, z = float(request.args['x']), float(request.args['z'])
    except (KeyError, ValueError):
        return jsonify({"success": False}), 400
    data = request.get_data()
    if len(data) > 100_000_000:
        return jsonify({"success": False}), 400
    # a random name: the address of a picture must not give away where it is
    name = secrets.token_hex(10)
    if request.args.get('fog'):
        # the fog tour (mod 1.8+): the same place seen with a render distance
        # of 6 and no Distant Horizons, for Blindness; it joins the location
        # already kept, no review
        with connect() as c:
            loc = c.execute("SELECT location_id FROM locations WHERE location_id = ? AND review = 'kept'",
                            (request.args['fog'],)).fetchone()
        if not loc or not data.startswith(b'PK'):
            return jsonify({"success": False}), 400
        try:
            url = make_tiles(data, name)
        except Exception:
            return jsonify({"success": False}), 400
        with connect() as c:
            c.execute("UPDATE locations SET fog_url = ? WHERE location_id = ?", (url, loc[0]))
        return jsonify({"success": True, "id": loc[0]})
    if data.startswith(b'PK'):
        # mod 1.6+: the six cube faces in a zip, cut into tiles
        try:
            url = make_tiles(data, name)
        except Exception:
            return jsonify({"success": False}), 400
    elif data.startswith(b'\xff\xd8'):
        # one equirectangular JPEG (older mod)
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        jpg, webp = os.path.join(CAPTURE_DIR, name + '.jpg'), os.path.join(CAPTURE_DIR, name + '.webp')
        with open(jpg, 'wb') as f:
            f.write(data)
        try:
            # same quality as the original images: about 1.4 MB for 8192x4096
            subprocess.run(['cwebp', '-quiet', '-q', '85', jpg, '-o', webp], check=True, timeout=120)
        except (subprocess.SubprocessError, OSError):
            return jsonify({"success": False}), 500
        finally:
            os.remove(jpg)
        url = 'static/captures/' + name + '.webp'
    else:
        return jsonify({"success": False}), 400
    with connect() as c:
        planned = c.execute("SELECT location_id FROM locations WHERE location_id = ? AND review = 'planned'",
                            (request.args.get('planned', ''),)).fetchone()
        if planned:
            # a spot planned on the map, now taken: it keeps its place and province
            lid = planned[0]
            c.execute("UPDATE locations SET image_url = ?, review = 'new' WHERE location_id = ?", (url, lid))
        else:
            lid = c.execute("INSERT INTO locations (x_position, z_position, image_url, province, review) VALUES (?, ?, ?, ?, 'new')",
                            (x, z, url, guess_province(c, x, z))).lastrowid
    return jsonify({"success": True, "id": lid})

def make_tiles(data, name):
    # Pannellum "multires": each face cut in 512 px tiles at 4096, 2048, 1024
    # and 512 (levels 4 to 1), like Street View; the browser only loads what
    # it shows. The URL of such a location ends with "/".
    from PIL import Image
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        faces = {l: Image.open(io.BytesIO(z.read(l + '.jpg'))).convert('RGB') for l in 'fbudlr'}
    if any(f.size != (CUBE, CUBE) for f in faces.values()):
        raise ValueError('faces must be %d px' % CUBE)
    levels = int(math.log2(CUBE // TILE)) + 1
    tmp = os.path.join(TILES_DIR, '.' + name)
    for letter, face in faces.items():
        for level in range(levels, 0, -1):
            size = CUBE >> (levels - level)
            img = face if size == CUBE else face.resize((size, size), Image.Resampling.LANCZOS)
            os.makedirs(os.path.join(tmp, str(level)), exist_ok=True)
            for i in range(size // TILE):
                for j in range(size // TILE):
                    # each tile twice: WebP 90, what the pages load (a third
                    # lighter, Yasuro's choice), and JPEG, until no page asks
                    # for it (tools/webp_tiles.py did the older locations)
                    tile = img.crop((j * TILE, i * TILE, (j + 1) * TILE, (i + 1) * TILE))
                    tile.save(os.path.join(tmp, str(level), f'{letter}{i}_{j}.jpg'), quality=90)
                    tile.save(os.path.join(tmp, str(level), f'{letter}{i}_{j}.webp'), quality=90)
        os.makedirs(os.path.join(tmp, 'fallback'), exist_ok=True)
        small = face.resize((1024, 1024), Image.Resampling.LANCZOS)
        small.save(os.path.join(tmp, 'fallback', letter + '.jpg'), quality=90)
        small.save(os.path.join(tmp, 'fallback', letter + '.webp'), quality=90)
    os.rename(tmp, os.path.join(TILES_DIR, name))
    return 'static/tiles/' + name + '/'

@app.route("/api/capture/fog")
def capture_fog():
    # for the mod's fog tour: the kept locations still without their fog photo
    if not key_ok():
        return jsonify({"success": False}), 403
    with connect() as c:
        rows = c.execute("SELECT location_id, x_position, z_position FROM locations WHERE review = 'kept' AND fog_url IS NULL").fetchall()
    return jsonify([{"id": r[0], "x": int(math.floor(r[1])), "z": int(math.floor(r[2]))} for r in rows])

@app.route("/api/capture/planned")
def capture_planned():
    if not key_ok():
        return jsonify({"success": False}), 403
    with connect() as c:
        rows = c.execute("SELECT location_id, x_position, z_position FROM locations WHERE review = 'planned'").fetchall()
    return jsonify([{"id": r[0], "x": int(r[1]), "z": int(r[2])} for r in rows])

@app.route("/api/coverage", methods=['POST'])
def coverage_upload():
    # {"x,z": base64 of the region's 1024 bits, one per chunk} from the mod
    if not key_ok():
        return jsonify({"success": False}), 403
    regions = request.get_json(silent=True)
    if not isinstance(regions, dict) or len(request.get_data()) > 5_000_000:
        return jsonify({"success": False}), 400
    with open(COVERAGE_FILE, 'w') as f:
        json.dump(regions, f)
    return jsonify({"success": True})

@app.route("/api/review/coverage")
def coverage():
    if not is_reviewer():
        return jsonify({"success": False}), 403
    try:
        with open(COVERAGE_FILE) as f:
            return jsonify(json.load(f))
    except FileNotFoundError:
        return jsonify(None)

@app.route("/api/review/plan", methods=['POST'])
def review_plan():
    if not is_reviewer():
        return jsonify({"success": False}), 403
    form = request.get_json(silent=True) or {}
    try:
        x, z = int(form['x']), int(form['z'])
    except (KeyError, ValueError, TypeError):
        return jsonify({"success": False})
    with connect() as c:
        lid = c.execute("INSERT INTO locations (x_position, z_position, image_url, province, review) VALUES (?, ?, '', ?, 'planned')",
                        (x, z, guess_province(c, x, z))).lastrowid
    return jsonify({"success": True, "id": lid})

@app.route("/review")
def review():
    if not is_reviewer():
        return redirect('login?next=review') if not session.get('loggedin') else redirect('./')
    return render_template('review.html', provinces = REVIEW_PROVINCES, can_push = is_reviewer(PUBLISHER))

# The green dots become the live site's locations, and nothing else: the
# rest is hidden there, never erased (finished rooms replay their own). Ids
# are the same on both sides, the beta started as a copy of the live database
# and the live site never makes locations. The photos are shared: both sites'
# static/tiles lead to the same folder on /data.
@app.route("/api/review/push", methods=['POST'])
def review_push():
    if not is_reviewer(PUBLISHER):
        return jsonify({"success": False}), 403
    if os.path.samefile(LIVE_DB, 'database.db'):
        return jsonify({"success": False, "error": "this is the live site"})
    with connect() as c:
        kept = c.execute("""SELECT location_id, x_position, z_position, image_url, province, fog_url
                            FROM locations WHERE review = 'kept'""").fetchall()
    live = sqlite3.connect(LIVE_DB, timeout=10)
    try:
        if 'review' not in [r[1] for r in live.execute("PRAGMA table_info(locations)")]:
            return jsonify({"success": False, "error": "the live site is not up to date yet"})
        # the fog photos too, once the live site has their column (its app.py
        # adds it on start); their tiles are shared through /data, like the others
        fog = 'fog_url' in [r[1] for r in live.execute("PRAGMA table_info(locations)")]
        with live:
            live.execute("UPDATE locations SET review = 'deleted'")
            live.executemany("""INSERT INTO locations (location_id, x_position, z_position, image_url, province, review)
                                VALUES (?, ?, ?, ?, ?, 'kept')
                                ON CONFLICT(location_id) DO UPDATE SET x_position = excluded.x_position,
                                    z_position = excluded.z_position, image_url = excluded.image_url,
                                    province = excluded.province, review = 'kept'""", [tuple(r)[:5] for r in kept])
            if fog:
                live.executemany("UPDATE locations SET fog_url = ? WHERE location_id = ?",
                                 [(r['fog_url'], r['location_id']) for r in kept])
    finally:
        live.close()
    return jsonify({"success": True, "count": len(kept)})

@app.route("/api/review")
def review_list():
    if not is_reviewer():
        return jsonify({"success": False}), 403
    with connect() as c:
        rows = c.execute("""SELECT location_id, x_position, z_position, image_url, province, review
            FROM locations WHERE review != 'deleted'""").fetchall()
    return jsonify([{"id": r[0], "X": r[1], "Z": r[2], "url": r[3], "province": r[4], "review": r[5]} for r in rows])

@app.route("/api/review/<int:lid>", methods=['POST'])
def review_one(lid):
    if not is_reviewer():
        return jsonify({"success": False}), 403
    form = request.get_json(silent=True) or {}
    with connect() as c:
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (lid,)).fetchone()
        if not loc:
            return jsonify({"success": False})
        if form.get('action') == 'keep':
            if form.get('province') not in REVIEW_PROVINCES or loc['review'] == 'planned':
                return jsonify({"success": False})
            c.execute("UPDATE locations SET review = 'kept', province = ? WHERE location_id = ?", (form['province'], lid))
        elif form.get('action') == 'delete':
            if loc['review'] in ('new', 'planned'):
                # never played anywhere: nothing refers to it, it can go for good
                c.execute("DELETE FROM locations WHERE location_id = ?", (lid,))
                if loc['image_url']:
                    path = os.path.join(app.static_folder, loc['image_url'][len('static/'):])
                    try:
                        shutil.rmtree(path) if path.endswith('/') else os.remove(path)
                    except OSError:
                        pass
            else:
                # a finished room may still replay it: hidden, not erased
                c.execute("UPDATE locations SET review = 'deleted' WHERE location_id = ?", (lid,))
        else:
            return jsonify({"success": False})
    return jsonify({"success": True})

# ---------- Pictures behind tokens ----------
# The real address of a location's tiles (its folder) never reaches a page:
# what played it would otherwise learn, over its games, which folder is
# where. A page gets play/tile/<token>/, a random token for one use: a
# round of a room (kept: a finished room can be replayed, and its token
# leads nowhere else) or of a solo game (dropped once guessed).
# Survival has its own (survival/tile/), tied to its runs.

with connect() as c:
    c.execute("CREATE TABLE IF NOT EXISTS tiles (token TEXT PRIMARY KEY, location_id INTEGER, scope TEXT UNIQUE)")
    # Blindness in a survival room: the same place in the fog
    if 'fog' not in [col[1] for col in c.execute("PRAGMA table_info(tiles)")]:
        c.execute("ALTER TABLE tiles ADD COLUMN fog INTEGER DEFAULT 0")

def tile_url(c, lid, scope, fog = False):
    # the address of a location's pictures for one use: scope names it
    # ('room:ABC234:3', 'solo:12:2'), the same scope gets the same token;
    # fog: its fog photo instead (a scope of its own)
    if fog:
        scope += ':fog'
    row = c.execute("SELECT token FROM tiles WHERE scope = ?", (scope,)).fetchone()
    token = row[0] if row else secrets.token_hex(16)
    if not row:
        c.execute("INSERT INTO tiles (token, location_id, scope, fog) VALUES (?, ?, ?, ?)", (token, lid, scope, int(fog)))
    return 'play/tile/' + token + '/'

@app.route("/play/tile/<token>/<path:name>")
def play_tile(token, name):
    with connect() as c:
        row = c.execute("""SELECT CASE WHEN t.fog = 1 AND l.fog_url IS NOT NULL THEN l.fog_url ELSE l.image_url END, t.scope
                FROM tiles t JOIN locations l ON l.location_id = t.location_id WHERE t.token = ?""", (token,)).fetchone()
    if not row or not row[0].startswith('static/tiles/'):
        return '', 404
    if row[1].startswith('room:'):
        # a room's token never dies and everyone in the room has it: Cloudflare
        # keeps the tiles, and sends them to the others without asking here
        return send_from_directory(os.path.join(TILES_DIR, row[0][len('static/tiles/'):].strip('/')), name, max_age = 86400)
    response = send_from_directory(os.path.join(TILES_DIR, row[0][len('static/tiles/'):].strip('/')), name, max_age = 3600)
    response.cache_control.public, response.cache_control.private = False, True   # alone: the browser keeps it, Cloudflare does not (see Survival)
    return response

# ---------- Solo ----------
# The Classic game alone, played on the server like Survival (same reasons,
# see its header): the page gets a picture and a clock, sends a guess, and is
# told the answer and the points. The rules are those of the original game:
# N rounds, points by distance (guess_score), an optional time limit; a
# finished game goes to the leaderboard of its settings. A reload brings back
# the same round; Play Again starts another game.

SOLO_ROUNDS = (3, 5, 10, 25)

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS solo_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, provinces TEXT, rounds INTEGER,
            time_limit INTEGER, look INTEGER, round INTEGER DEFAULT 0, phase TEXT, location_id INTEGER,
            round_start REAL, deadline REAL, used TEXT DEFAULT '[]', score INTEGER DEFAULT 0,
            time REAL DEFAULT 0, started REAL, ended REAL);
        CREATE TABLE IF NOT EXISTS solo_guesses (
            game_id INTEGER, round INTEGER, location_id INTEGER, x REAL, z REAL, distance REAL,
            score INTEGER, time REAL, at REAL, PRIMARY KEY (game_id, round));
    ''')

def my_solo(c):
    # the game this page plays: the session's, unless it is another account's
    gid = session.get('solo')
    game = gid and c.execute("SELECT * FROM solo_games WHERE id = ?", (gid,)).fetchone()
    me = session.get('user_id') if session.get('loggedin') else None
    if not game or (game['user_id'] is not None and game['user_id'] != me):
        return None
    return game

def solo_settings(form):
    # the settings of the mode page, checked: rounds, time, view. Always the
    # whole map: choosing provinces is for custom games (Yasuro, 2026-10-18)
    try:
        rounds, limit = int(form.get('rounds', '')), int(form.get('time_limit', -1))
    except ValueError:
        return None
    if rounds not in SOLO_ROUNDS or not (limit == -1 or 1 <= limit <= 1800):
        return None
    return {'provinces': PROVINCES, 'rounds': rounds, 'time_limit': limit, 'look': form.get('look') == 'true'}

def solo_next(c, game):
    provinces = json.loads(game['provinces'])
    used = json.loads(game['used'])
    marks = ', '.join('?' for _ in provinces)
    left = [l[0] for l in c.execute(f"SELECT location_id FROM locations WHERE review IN {PLAYABLE} AND province IN ({marks})",
                                    provinces) if l[0] not in used]
    lid = secrets.choice(left)
    now = time.time()
    c.execute("""UPDATE solo_games SET round = round + 1, phase = 'guess', location_id = ?, round_start = ?, deadline = ?,
            used = ? WHERE id = ?""", (lid, now, now + game['time_limit'] if game['time_limit'] > 0 else None,
            json.dumps(used + [lid]), game['id']))

def solo_settle(c, game, x = None, z = None):
    # the round's guess (x and z, or None: no pin when the time ran out)
    now = time.time()
    loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (game['location_id'],)).fetchone()
    spent = max(0, min(now, game['deadline'] or now) - game['round_start'])
    d = None if x is None else math.hypot(loc['x_position'] - x, loc['z_position'] - z)
    points = 0 if x is None else guess_score(x, z, loc)
    over = game['round'] >= game['rounds']
    c.execute("""INSERT INTO solo_guesses (game_id, round, location_id, x, z, distance, score, time, at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (game['id'], game['round'], loc['location_id'], x, z, d, points, spent, now))
    c.execute("UPDATE solo_games SET score = score + ?, time = time + ?, phase = ?, ended = ? WHERE id = ?",
              (points, spent, 'over' if over else 'result', now if over else None, game['id']))
    c.execute("DELETE FROM tiles WHERE scope = ?", ('solo:%d:%d' % (game['id'], game['round']),))
    game = c.execute("SELECT * FROM solo_games WHERE id = ?", (game['id'],)).fetchone()
    if over:
        # the finished game, on the leaderboard of its settings; without an
        # account, kept in the session for the one the player logs in to (adopt)
        g = {'score': game['score'], 'nolook': 'Yes' if game['look'] else 'No', 'provinces': str(json.loads(game['provinces'])),
             'rounds': game['rounds'], 'time': round(game['time'], 2), 'mode': 'classic'}
        if game['user_id']:
            save_solo(c, game['user_id'], g)
        else:
            session['pending'] = g
    return game

def solo_tick(c, game):
    if game['phase'] == 'guess' and game['deadline'] and time.time() > game['deadline'] + LATE:
        game = solo_settle(c, game)
    return game

def solo_state(c, game):
    out = {"success": True, "round": game['round'], "rounds": game['rounds'], "score": game['score'], "phase": game['phase'],
           "time_limit": game['time_limit'], "look": bool(game['look']), "provinces": json.loads(game['provinces'])}
    if game['phase'] == 'guess':
        out['url'] = tile_url(c, game['location_id'], 'solo:%d:%d' % (game['id'], game['round']))
        if game['deadline']:
            out['time_left'] = max(0, game['deadline'] - time.time())
        return out
    guesses = [dict(g) for g in c.execute("""SELECT g.round, g.x, g.z, g.distance, g.score, l.x_position AS X, l.z_position AS Z
            FROM solo_guesses g JOIN locations l ON l.location_id = g.location_id WHERE g.game_id = ? ORDER BY g.round""", (game['id'],))]
    out['result'] = guesses[-1] if guesses else None
    if game['phase'] == 'over':
        out['history'] = guesses
        out['time'] = game['time']
        if game['user_id']:
            out.update({"xp": progress(c, game['user_id'])['xp'], "gained": solo_xp(game['score'], 'classic')})
        else:
            out['pending'] = True
    return out

@app.route("/api/solo/start", methods=['POST'])
def solo_start():
    settings = solo_settings(request.form)
    if not settings:
        return jsonify({"success": False})
    uid = session.get('user_id') if session.get('loggedin') else None
    c = run_tx()
    try:
        marks = ', '.join('?' for _ in settings['provinces'])
        pool = c.execute(f"SELECT COUNT(*) FROM locations WHERE review IN {PLAYABLE} AND province IN ({marks})",
                         settings['provinces']).fetchone()[0]
        if pool < settings['rounds']:
            c.execute("ROLLBACK")
            return jsonify({"success": False, "error": "Not enough locations in these provinces"})
        gid = c.execute("""INSERT INTO solo_games (user_id, provinces, rounds, time_limit, look, phase, started)
                VALUES (?, ?, ?, ?, ?, 'new', ?)""", (uid, json.dumps(settings['provinces']), settings['rounds'],
                settings['time_limit'], int(settings['look']), time.time())).lastrowid
        solo_next(c, c.execute("SELECT * FROM solo_games WHERE id = ?", (gid,)).fetchone())
        session['solo'] = gid
        out = solo_state(c, c.execute("SELECT * FROM solo_games WHERE id = ?", (gid,)).fetchone())
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/solo")
def solo_get():
    c = run_tx()
    try:
        game = my_solo(c)
        out = solo_state(c, solo_tick(c, game)) if game else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/solo/guess", methods=['POST'])
def solo_guess():
    c = run_tx()
    try:
        game = my_solo(c)
        ok = game and game['phase'] == 'guess' and request.form.get('round') == str(game['round'])
        if ok:
            x = z = None
            late = game['deadline'] and time.time() > game['deadline'] + LATE
            if not late and request.form.get('x'):
                try:
                    x, z = float(request.form['x']), float(request.form['z'])
                except ValueError:
                    x = z = None
                if x is not None and not (math.isfinite(x) and math.isfinite(z)):
                    x = z = None
            game = solo_settle(c, game, x, z)
        out = solo_state(c, game) if ok else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/solo/next", methods=['POST'])
def solo_go():
    c = run_tx()
    try:
        game = my_solo(c)
        ok = game and game['phase'] == 'result' and request.form.get('round') == str(game['round'])
        if ok:
            solo_next(c, game)
            game = c.execute("SELECT * FROM solo_games WHERE id = ?", (game['id'],)).fetchone()
        out = solo_state(c, game) if ok else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

# ---------- Survival ----------
# Solo only. Hearts as in Minecraft (counted in half-hearts), a zone that
# shrinks every round, the potions, and two milk buckets to cancel them. The whole run lives here, never in
# the browser: the page gets a picture, sends a guess and is told what it
# cost. Against cheating:
# - no answer leaves the server before its guess, and no picture's real
#   address: tiles go through survival/tile/<token>/, a new random token for
#   every round (old addresses, learnt from the reveals of earlier games,
#   lead nowhere);
# - the clock is the server's: a guess later than the deadline (plus a
#   little lag) counts as no guess, and a round left open is settled as
#   such at the next request;
# - one run at a time per player (session and account): starting another
#   ends it, as it stands; a reload brings back the same round, with the
#   time already spent;
# - each guess names its round: a second one, or one from an old tab, is
#   refused;
# - every guess is kept (survival_guesses), time included, for checking.
# Known limits: what only the page draws (Darkness, Nausea, Mining Fatigue)
# can be undone by someone who edits the page; a script that recognises
# the pictures themselves cannot be stopped from here.

DIFFICULTIES = {'normal': 20, 'hard': 10, 'hardcore': 2}   # half-hearts
ROUND_TIME = {'normal': 60, 'hard': 40, 'hardcore': 30}    # seconds
SWIFT_TIME = 20
SWIFT_ZONE = 1.5           # Swiftness: a zone this much wider
NEAR = 10                  # blocks: a near-perfect guess; two in a row give back half a heart
LATE = 2                   # seconds a guess may come after the deadline (network lag)
FIRST_POTION = 4           # no potion before this round
POTION_RATE = {'normal': 1 / 5, 'hard': 1 / 4, 'hardcore': 1 / 3}
# name: weight (Regeneration, the only good one, comes half as often).
# Blindness waits for the fog pictures (CLAUDE.md, "Survival")
POTIONS = {'swiftness': 2, 'mining_fatigue': 2, 'wither': 2, 'nausea': 2, 'darkness': 2, 'regeneration': 1, 'blindness': 2}
SHAKE = (20, 60)           # Nausea: the pin lands this many blocks off, in any direction
WITHER_EVERY = 5           # Wither: half a heart every this many seconds until the guess
REGEN = 4                  # Regeneration: half-hearts given back for a guess inside the zone
MILK = 2                   # milk buckets a run with milk starts with (an option, off by default): each cancels a potion

def zone(n, effect = None):
    # round n: no damage within `safe` blocks, the most a guess can cost from
    # `far` on, and that most (`cap`, in half-hearts). Calibrated on the real
    # guesses of the rooms (CLAUDE.md, "Survival")
    # 2026-10-18, "a tad bit harder" (players: "if you know the spot you get
    # within 5 blocks easily"): 110 -> 35 at round 20, floor 15 (was 150 ->
    # 50, floor 25); the far end 1700 -> 650, floor 400 (was 2000 -> 800, 500)
    safe = max(15, 110 * (35 / 110) ** ((n - 1) / 19))
    far = max(400, 1700 * (650 / 1700) ** ((n - 1) / 19))
    cap = min(20, 10 + round(10 * (n - 1) / 19))
    if effect == 'swiftness':
        safe, far = safe * SWIFT_ZONE, far * SWIFT_ZONE
    return safe, far, cap

def hurt(d, n, effect = None):
    # half-hearts a guess d blocks away costs in round n
    safe, far, cap = zone(n, effect)
    if d <= safe:
        return 0
    if d >= far:
        return cap
    return min(cap, 1 + math.floor(19 * ((d - safe) / (far - safe)) ** 1.5))

def kill_radius(n, effect, hp):
    # from how far a guess would have killed (the red circle), or None if
    # nothing could; the damage only grows with the distance
    safe, far, cap = zone(n, effect)
    if cap < hp:
        return None
    low, high = safe, far
    for _ in range(40):
        mid = (low + high) / 2
        if hurt(mid, n, effect) >= hp:
            high = mid
        else:
            low = mid
    return high

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS survival_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, difficulty TEXT, hp INTEGER,
            round INTEGER DEFAULT 0, phase TEXT, location_id INTEGER, token TEXT, effect TEXT,
            round_start REAL, deadline REAL, close INTEGER DEFAULT 0, survived INTEGER DEFAULT 0,
            points INTEGER DEFAULT 0, time REAL DEFAULT 0, used TEXT DEFAULT '[]', score_id INTEGER,
            started REAL, ended REAL);
        CREATE TABLE IF NOT EXISTS survival_guesses (
            run_id INTEGER, round INTEGER, location_id INTEGER, x REAL, z REAL, distance REAL,
            hp INTEGER, damage INTEGER, wither INTEGER, heal INTEGER, points INTEGER, effect TEXT,
            time REAL, at REAL, PRIMARY KEY (run_id, round));
    ''')
    # the new Survival has a leaderboard per difficulty, broken ties on points;
    # the old one's scores (other rules) go, once
    # the potion thrown at the player with a result, for the round after it
    if 'next_effect' not in [col[1] for col in c.execute("PRAGMA table_info(survival_runs)")]:
        c.execute("ALTER TABLE survival_runs ADD COLUMN next_effect TEXT")
    # Blindness: the same place in the fog (the mod's fog tour), when it was taken
    if 'fog_url' not in [col[1] for col in c.execute("PRAGMA table_info(locations)")]:
        c.execute("ALTER TABLE locations ADD COLUMN fog_url TEXT")
    # test runs (the beta's test panel), never on the leaderboard; where a
    # guess under Nausea was aimed before it landed off
    if 'test' not in [col[1] for col in c.execute("PRAGMA table_info(survival_runs)")]:
        c.execute("ALTER TABLE survival_runs ADD COLUMN test INTEGER DEFAULT 0")
    if 'aim_x' not in [col[1] for col in c.execute("PRAGMA table_info(survival_guesses)")]:
        c.execute("ALTER TABLE survival_guesses ADD COLUMN aim_x REAL")
        c.execute("ALTER TABLE survival_guesses ADD COLUMN aim_z REAL")
    # the milk buckets left, and the potion a bucket cancelled (with the result it was thrown at).
    # No bucket for the runs already there: on the live site none ever had milk
    # (a default of MILK gave every run in progress two buckets, and their scores to the milk board)
    if 'milk' not in [col[1] for col in c.execute("PRAGMA table_info(survival_runs)")]:
        c.execute("ALTER TABLE survival_runs ADD COLUMN milk INTEGER DEFAULT 0")
        c.execute("ALTER TABLE survival_guesses ADD COLUMN milked TEXT")
    # milk became an option (Yasuro: the runs with milk apart from the others,
    # on the leaderboard too): the run's choice, and the score's. Before, every
    # run had its buckets: those that drank one count as runs with milk
    if 'milk_on' not in [col[1] for col in c.execute("PRAGMA table_info(survival_runs)")]:
        c.execute("ALTER TABLE survival_runs ADD COLUMN milk_on INTEGER DEFAULT 0")
        c.execute("ALTER TABLE scores ADD COLUMN milk INTEGER DEFAULT 0")
        c.execute("""UPDATE survival_runs SET milk_on = 1 WHERE id IN (SELECT run_id FROM survival_guesses WHERE milked IS NOT NULL)
                OR (phase != 'over' AND milk > 0)""")
        c.execute("""UPDATE scores SET milk = 1 WHERE id IN (SELECT score_id FROM survival_runs WHERE milk_on = 1 AND score_id IS NOT NULL)""")
    if 'difficulty' not in [col[1] for col in c.execute("PRAGMA table_info(scores)")]:
        c.execute("ALTER TABLE scores ADD COLUMN difficulty TEXT")
        c.execute("ALTER TABLE scores ADD COLUMN points INTEGER")
        c.execute("DELETE FROM scores WHERE mode = 'survival'")

def my_run(c):
    # the run this page plays: the session's, as long as it is not someone
    # else's account (a run played without one belongs to its session)
    rid = session.get('survival')
    run = rid and c.execute("SELECT * FROM survival_runs WHERE id = ?", (rid,)).fetchone()
    me = session.get('user_id') if session.get('loggedin') else None
    if not run or (run['user_id'] is not None and run['user_id'] != me):
        return None
    return run

def run_tx():
    # like rooms: one request at a time moves a run forward
    c = connect()
    c.isolation_level = None
    c.execute("BEGIN IMMEDIATE")
    return c

def survival_record(c, run):
    # the run on the leaderboard as it stands, from the first location found
    # on (updated each round: a run left half-way keeps its score)
    if not run['user_id'] or not run['survived'] or run['test']:
        return
    if run['score_id']:
        c.execute("UPDATE scores SET score = ?, points = ?, time = ?, milk = ? WHERE id = ?",
                  (run['survived'], run['points'], round(run['time'], 2), run['milk_on'], run['score_id']))
    else:
        sid = c.execute("""INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode, difficulty, points, milk)
                VALUES (?, ?, ?, 'No', '', NULL, ?, 'survival', ?, ?, ?)""",
                (run['user_id'], run['survived'], date.today(), round(run['time'], 2), run['difficulty'], run['points'],
                 run['milk_on'])).lastrowid
        c.execute("UPDATE survival_runs SET score_id = ? WHERE id = ?", (sid, run['id']))

def survival_end(c, run):
    c.execute("UPDATE survival_runs SET phase = 'over', ended = ? WHERE id = ?", (time.time(), run['id']))

def survival_next(c, run):
    # a new round: a location not seen in this run, maybe a potion, the clock starts
    used = json.loads(run['used'])
    left = [l[0] for l in c.execute(f"SELECT location_id FROM locations WHERE review IN {PLAYABLE}")
            if l[0] not in used]
    if not left:
        return survival_end(c, run)   # every location found: nothing left to play
    n = run['round'] + 1
    effect = run['next_effect']   # thrown at the player with the last result
    if effect == 'blindness':
        # played on a place that has its fog photo
        foggy = fog_left(c, run)
        left, effect = (foggy, effect) if foggy else (left, None)
    lid = secrets.choice(left)
    now = time.time()
    seconds = SWIFT_TIME if effect == 'swiftness' else ROUND_TIME[run['difficulty']]
    c.execute("""UPDATE survival_runs SET round = ?, phase = 'guess', location_id = ?, token = ?, effect = ?,
            next_effect = NULL, round_start = ?, deadline = ?, used = ? WHERE id = ?""",
            (n, lid, secrets.token_hex(16), effect, now, now + seconds, json.dumps(used + [lid]), run['id']))

def potion(difficulty, n, effect, fog = True):
    # the potion for round n, or None: never before FIRST_POTION, never two in
    # a row (so drawn more often after a round without one, for potions to
    # really come once every 5, 4 or 3 rounds: r / (1 - r)); Blindness only
    # when a location with its fog photo is left (fog), never imitated
    rate = POTION_RATE[difficulty]
    if not POTIONS or n < FIRST_POTION or effect or secrets.randbelow(10 ** 6) >= rate / (1 - rate) * 10 ** 6:
        return None
    pool = {k: w for k, w in POTIONS.items() if fog or k != 'blindness'}
    pick = secrets.randbelow(sum(pool.values()) * 100) / 100
    for name, weight in pool.items():
        pick -= weight
        if pick < 0:
            return name

def fog_left(c, run):
    # a location with its fog photo, not seen yet in this run
    used = json.loads(run['used'])
    return [l[0] for l in c.execute(f"SELECT location_id FROM locations WHERE review IN {PLAYABLE} AND fog_url IS NOT NULL")
            if l[0] not in used]

def survival_settle(c, run, x = None, z = None):
    # the round's guess (x and z, or None: no pin when the clock ran out, the creeper)
    now = time.time()
    n, effect, hp = run['round'], run['effect'], run['hp']
    loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (run['location_id'],)).fetchone()
    spent = max(0, min(now, run['deadline']) - run['round_start'])
    wither = int(spent // WITHER_EVERY) if effect == 'wither' else 0
    aim_x, aim_z = x, z
    if effect == 'nausea' and x is not None:
        # Nausea, the hand shakes: the pin lands somewhere around where it was aimed
        angle = secrets.randbelow(360000) / 1000 * math.pi / 180
        off = SHAKE[0] + secrets.randbelow((SHAKE[1] - SHAKE[0]) * 1000) / 1000
        x, z = round(x + off * math.cos(angle)), round(z + off * math.sin(angle))
    if x is None:
        d, damage, points = None, zone(n, effect)[2], 0
    else:
        d = math.hypot(loc['x_position'] - x, loc['z_position'] - z)
        damage, points = hurt(d, n, effect), guess_score(x, z, loc)
    hp_after = hp - damage - wither
    heal, close = 0, run['close']
    if hp_after > 0 and d is not None:
        if effect == 'regeneration' and d <= zone(n, effect)[0]:
            heal += REGEN
        close = close + 1 if d <= NEAR else 0
        if close == 2:
            heal, close = heal + 1, 0
    else:
        close = 0
    hp_after = min(DIFFICULTIES[run['difficulty']], hp_after + heal) if hp_after > 0 else 0
    survived = run['survived'] + (1 if hp_after > 0 else 0)
    c.execute("""INSERT INTO survival_guesses (run_id, round, location_id, x, z, distance, hp, damage, wither, heal, points, effect,
            time, at, aim_x, aim_z) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run['id'], n, loc['location_id'], x, z, d, hp, damage, wither, heal if hp_after > 0 else 0, points, effect, spent, now,
             aim_x if effect == 'nausea' else None, aim_z if effect == 'nausea' else None))
    c.execute("""UPDATE survival_runs SET hp = ?, close = ?, survived = ?, points = points + ?, time = time + ?,
            phase = ?, next_effect = ? WHERE id = ?""", (hp_after, close, survived, points, spent, 'result' if hp_after > 0 else 'over',
            potion(run['difficulty'], n + 1, effect, bool(fog_left(c, run))) if hp_after > 0 else None, run['id']))
    run = c.execute("SELECT * FROM survival_runs WHERE id = ?", (run['id'],)).fetchone()
    if hp_after <= 0:
        c.execute("UPDATE survival_runs SET ended = ? WHERE id = ?", (now, run['id']))
    survival_record(c, run)
    return run

def survival_tick(c, run):
    # a round whose time is up and which nobody answered: the creeper
    if run['phase'] == 'guess' and time.time() > run['deadline'] + LATE:
        run = survival_settle(c, run)
    return run

def survival_state(c, run):
    # what the page may know: never the answer of a round still open
    out = {"success": True, "difficulty": run['difficulty'], "max": DIFFICULTIES[run['difficulty']],
           "hp": run['hp'], "round": run['round'], "survived": run['survived'], "points": run['points'],
           "phase": run['phase'], "test": bool(run['test']), "milk_on": bool(run['milk_on'])}
    if run['phase'] == 'over':
        # the end screen: the XP the run brought, or a word to log in and keep it
        if run['user_id']:
            out.update({"xp": progress(c, run['user_id'])['xp'], "gained": run['survived'] * SPOT_XP})
        else:
            out['pending'] = run['survived'] > 0
    if run['phase'] == 'guess':
        out.update({"url": 'survival/tile/' + run['token'] + '/', "effect": run['effect'],
                    "time": run['deadline'] - run['round_start'], "time_left": max(0, run['deadline'] - time.time())})
        return out
    g = c.execute("SELECT * FROM survival_guesses WHERE run_id = ? AND round = ?", (run['id'], run['round'])).fetchone()
    if g:
        loc = c.execute("SELECT x_position, z_position FROM locations WHERE location_id = ?", (g['location_id'],)).fetchone()
        safe, far, cap = zone(g['round'], g['effect'])
        # the circles of the reveal: green, no damage; yellow, damage; red,
        # death with the hearts that were left (Wither's share already taken)
        out['result'] = {"X": loc[0], "Z": loc[1], "x": g['x'], "z": g['z'], "distance": g['distance'],
                         "damage": g['damage'], "wither": g['wither'], "heal": g['heal'], "points": g['points'],
                         "effect": g['effect'], "creeper": g['x'] is None, "safe": safe, "far": far,
                         "kill": kill_radius(g['round'], g['effect'], g['hp'] - g['wither']),
                         "aim_x": g['aim_x'], "aim_z": g['aim_z']}
        if run['phase'] == 'result':
            out.update({"potion": run['next_effect'],   # thrown now, for the next round
                        "milk": run['milk'], "milked": g['milked']})
    return out

def survival_tester():
    # the test panel: on the beta only (where capture_key exists), for the
    # reviewers; its runs never reach the leaderboard
    return is_reviewer()

@app.route("/survival")
def survival_page():
    difficulty = request.args.get('difficulty')
    return render_template('survival.html', difficulty = difficulty if difficulty in DIFFICULTIES else 'normal',
                           milk = request.args.get('milk') == '1', test = request.args.get('test') == '1' and survival_tester())

@app.route("/api/survival/test", methods=['POST'])
def survival_test():
    # the test panel's buttons, on a test run only
    c = run_tx()
    try:
        run = my_run(c)
        if not run or not run['test'] or not survival_tester() or run['phase'] == 'over':
            c.execute("ROLLBACK")
            return jsonify({"success": False})
        form, now = request.form, time.time()
        what = form.get('do')
        if what == 'potion' and form.get('potion', '') in [''] + list(POTIONS):
            name = form['potion'] or None
            if run['phase'] == 'guess':
                # drunk now: the round starts again under it (same place, its
                # clock; Blindness needs a place with its fog photo)
                seconds = SWIFT_TIME if name == 'swiftness' else ROUND_TIME[run['difficulty']]
                lid = run['location_id']
                if name == 'blindness' and not c.execute("SELECT fog_url FROM locations WHERE location_id = ?", (lid,)).fetchone()[0]:
                    foggy = fog_left(c, run)
                    if not foggy:
                        c.execute("ROLLBACK")
                        return jsonify({"success": False, "error": "no fog photo yet"})
                    lid = secrets.choice(foggy)
                c.execute("UPDATE survival_runs SET effect = ?, round_start = ?, deadline = ?, location_id = ?, token = ? WHERE id = ?",
                          (name, now, now + seconds, lid, secrets.token_hex(16), run['id']))
            else:
                c.execute("UPDATE survival_runs SET next_effect = ? WHERE id = ?", (name, run['id']))
        elif what == 'hearts' and form.get('hp', '').isdigit():
            c.execute("UPDATE survival_runs SET hp = ? WHERE id = ?",
                      (max(1, min(DIFFICULTIES[run['difficulty']], int(form['hp']))), run['id']))
        elif what == 'round' and form.get('round', '').isdigit():
            c.execute("UPDATE survival_runs SET round = ? WHERE id = ?", (max(1, min(200, int(form['round']))), run['id']))
        elif what == 'milk':
            c.execute("UPDATE survival_runs SET milk = ? WHERE id = ?", (MILK, run['id']))
        elif what == 'creeper' and run['phase'] == 'guess':
            c.execute("UPDATE survival_runs SET deadline = ? WHERE id = ?", (now + 4, run['id']))
        out = survival_state(c, c.execute("SELECT * FROM survival_runs WHERE id = ?", (run['id'],)).fetchone())
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/survival/start", methods=['POST'])
def survival_start():
    difficulty = request.form.get('difficulty')
    if difficulty not in DIFFICULTIES:
        return jsonify({"success": False})
    uid = session.get('user_id') if session.get('loggedin') else None
    c = run_tx()
    try:
        # one run at a time: the one this session played, and any other of this account
        old = my_run(c)
        if old and old['phase'] != 'over':
            survival_end(c, old)
        if uid:
            for r in c.execute("SELECT * FROM survival_runs WHERE user_id = ? AND phase != 'over'", (uid,)).fetchall():
                survival_end(c, r)
        test = request.form.get('test') == '1' and survival_tester()
        milk = request.form.get('milk') == '1'
        rid = c.execute("""INSERT INTO survival_runs (user_id, difficulty, hp, phase, started, test, milk, milk_on)
                VALUES (?, ?, ?, 'new', ?, ?, ?, ?)""",
                (uid, difficulty, DIFFICULTIES[difficulty], time.time(), int(test), MILK if milk else 0, int(milk))).lastrowid
        run = c.execute("SELECT * FROM survival_runs WHERE id = ?", (rid,)).fetchone()
        survival_next(c, run)
        session['survival'] = rid
        out = survival_state(c, c.execute("SELECT * FROM survival_runs WHERE id = ?", (rid,)).fetchone())
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/survival")
def survival_get():
    c = run_tx()
    try:
        run = my_run(c)
        out = survival_state(c, survival_tick(c, run)) if run else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/survival/guess", methods=['POST'])
def survival_guess():
    c = run_tx()
    try:
        run = my_run(c)
        ok = run and run['phase'] == 'guess' and request.form.get('round') == str(run['round'])
        if ok:
            x = z = None
            if time.time() <= run['deadline'] + LATE and request.form.get('x'):
                try:
                    x, z = float(request.form['x']), float(request.form['z'])
                except ValueError:
                    x = z = None
                if x is not None and not (math.isfinite(x) and math.isfinite(z)):
                    x = z = None
            run = survival_settle(c, run, x, z)
        out = survival_state(c, run) if ok else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/survival/next", methods=['POST'])
def survival_go():
    c = run_tx()
    try:
        run = my_run(c)
        ok = run and run['phase'] == 'result' and request.form.get('round') == str(run['round'])
        if ok:
            survival_next(c, run)
            run = c.execute("SELECT * FROM survival_runs WHERE id = ?", (run['id'],)).fetchone()
        out = survival_state(c, run) if ok else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/api/survival/milk", methods=['POST'])
def survival_milk():
    # a bucket of milk: the potion thrown with this result never happens
    c = run_tx()
    try:
        run = my_run(c)
        ok = (run and run['phase'] == 'result' and request.form.get('round') == str(run['round'])
              and run['next_effect'] and run['milk'] > 0)
        if ok:
            c.execute("UPDATE survival_guesses SET milked = ? WHERE run_id = ? AND round = ?", (run['next_effect'], run['id'], run['round']))
            c.execute("UPDATE survival_runs SET next_effect = NULL, milk = milk - 1 WHERE id = ?", (run['id'],))
            run = c.execute("SELECT * FROM survival_runs WHERE id = ?", (run['id'],)).fetchone()
        out = survival_state(c, run) if ok else {"success": False}
        c.execute("COMMIT")
    finally:
        c.close()
    return jsonify(out)

@app.route("/survival/tile/<token>/<path:name>")
def survival_tile(token, name):
    # the pictures of the round being played, under an address that only means
    # something during that round
    with connect() as c:
        # under Blindness, the fog photo of the same place
        run = c.execute("""SELECT CASE WHEN r.effect = 'blindness' AND l.fog_url IS NOT NULL THEN l.fog_url ELSE l.image_url END
                FROM survival_runs r JOIN locations l ON l.location_id = r.location_id
                WHERE r.token = ? AND r.phase = 'guess'""", (token,)).fetchone()
    if not run or not run[0].startswith('static/tiles/'):
        return '', 404
    response = send_from_directory(os.path.join(TILES_DIR, run[0][len('static/tiles/'):].strip('/')), name, max_age = 600)
    # kept by the browser, never by Cloudflare: the address must die with the round
    response.cache_control.public, response.cache_control.private = False, True
    return response


# ---------- Survival with friends ----------
# Survival in a room (it replaced Battle Royale): everyone plays the same
# location at the same time under the solo rules (the hearts of the
# difficulty, the shrinking zone, the clock, the creeper, two near-perfect
# guesses in a row, the random potions), and the game stops as soon as one
# player is left: the winner (several dying in the same round: the most
# points). Each guess earns emeralds by its distance (Wynncraft's money;
# points are all close to 5,000 and would tell nobody apart), spent between
# rounds on potions thrown at the others, or on Regeneration and milk for
# oneself; the dead watch, and may spend what they have left.
# Between two rounds, in this order (Yasuro's):
# 1. the reveal (REVEAL seconds), where the random potions are thrown;
# 2. the shop, until everyone is ready or SHOP seconds;
# 3. the potions bought are thrown (THROW seconds, only if there are any);
# 4. PREP seconds: the picture loads unseen, everyone sees what hit them
#    and may drink milk (it cancels everything, for that round);
# 5. the round.
# Everything stacks: the same potion twice is level II (Wither II, Darkness
# II...), and so on. Like duel, nothing is stored but what the players did
# (guesses, purchases and random potions in room_shop, milk drunk in
# room_milk): hearts and emeralds are replayed each time (survivors()).
# Unlike the other rooms, no last call once someone guessed: everyone has
# their whole clock, as alone (Yasuro, after trying one). Against cheating,
# as alone: the server's clock, a purchase checked against the emeralds left
# and the shop's hours, a guess only in its round. Known limits: the picture
# loads PREP seconds early (classic rooms load it during the reveal), and
# what only the page draws (Darkness, Nausea's spin, Mining Fatigue).

SURVIVAL_ROUNDS = 100   # the room's locations: the game ends long before
SHOP = 20               # seconds the shop stays open, less once everyone is ready
THROW = 4               # the potions bought fly (Yasuro's animation lasts 3.07 s)
PREP = 5                # the picture loads unseen; effects; milk
# emeralds for a guess within NEAR blocks, inside the safe zone, short of
# its far end (nothing beyond). Calibrated on 4,611 real guesses of 94
# players: about 9 a round for the strongest tenth, 5.5 for the median, 4
# for the weakest quarter, much the same from round 1 to 20 (CLAUDE.md)
EMERALDS = (10, 6, 2)
# the median player buys two potions a round, the strongest three (Yasuro:
# one a round, as at first with 5, 10, 15, was boring)
PRICES = {'mining_fatigue': 2, 'swiftness': 2, 'wither': 3, 'nausea': 3, 'blindness': 3, 'milk': 4,
          'darkness': 5, 'regeneration': 6}
SHOP_MAX = 3            # purchases a player may make in one shop (Yasuro: nobody buys every potion for one player)
SELF = ('regeneration', 'milk')   # bought for oneself; every other potion is thrown at someone else
MILK_BUYS = 2           # buckets a player may buy in a game (then: out of stock)
SWIFT_STEP = 5          # Swiftness II gives 5 seconds less than I, III 10 less...
SWIFT_MIN = 10          # ...never under this

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS room_shop (
            code TEXT, round INTEGER, buyer INTEGER, target INTEGER, item TEXT, at REAL);
        CREATE TABLE IF NOT EXISTS room_milk (
            code TEXT, round INTEGER, user_id INTEGER, at REAL, PRIMARY KEY (code, round, user_id));
        CREATE INDEX IF NOT EXISTS room_shop_code ON room_shop (code);
    ''')
    # a room's difficulty (survival); the shop a player is done with; where a
    # guess under Nausea was aimed before it landed off
    if 'difficulty' not in [col[1] for col in c.execute("PRAGMA table_info(rooms)")]:
        c.execute("ALTER TABLE rooms ADD COLUMN difficulty TEXT")
    # milk in the shop: an option of the room (off by default), with a leaderboard of its own
    if 'milk' not in [col[1] for col in c.execute("PRAGMA table_info(rooms)")]:
        c.execute("ALTER TABLE rooms ADD COLUMN milk INTEGER DEFAULT 0")
    # a Battle Royale room never started becomes a classic one: the mode is
    # gone from the settings (its page would find no mode to show)
    c.execute("UPDATE rooms SET mode = 'classic' WHERE mode = 'royale' AND state = 'waiting'")
    if 'ready' not in [col[1] for col in c.execute("PRAGMA table_info(room_players)")]:
        c.execute("ALTER TABLE room_players ADD COLUMN ready INTEGER DEFAULT 0")
    if 'aim_x' not in [col[1] for col in c.execute("PRAGMA table_info(room_guesses)")]:
        c.execute("ALTER TABLE room_guesses ADD COLUMN aim_x REAL")
        c.execute("ALTER TABLE room_guesses ADD COLUMN aim_z REAL")

def room_effects(shop, milked, uid, n):
    # what hits a player in round n, {potion: level}: random, thrown or drunk;
    # nothing at all once they drank milk
    if (uid, n) in milked:
        return {}
    fx = {}
    for row in shop:
        if row['round'] == n and row['target'] == uid and row['item'] in POTIONS:
            fx[row['item']] = fx.get(row['item'], 0) + 1
    return fx

def room_time(difficulty, fx):
    # the seconds a player has: the difficulty's, or Swiftness's (20, 15, 10)
    k = fx.get('swiftness', 0)
    return max(SWIFT_MIN, SWIFT_TIME - SWIFT_STEP * (k - 1)) if k else ROUND_TIME[difficulty]

def survival_deadline(r, fx):
    # a player's end of the round: their own clock
    return r['round_start'] + room_time(r['difficulty'], fx)

def room_shop_rows(c, code):
    return (c.execute("SELECT * FROM room_shop WHERE code = ?", (code,)).fetchall(),
            {(m[0], m[1]) for m in c.execute("SELECT user_id, round FROM room_milk WHERE code = ?", (code,))})

def survivors(c, r, upto):
    # replays the rounds up to `upto`: for each contestant, the hearts left
    # ('left', in half-hearts), the round they died in ('out'), the change in
    # round `upto` ('delta'), the emeralds left (every purchase so far
    # counted), the milk in hand, the locations survived, and what round
    # `upto` did to them ('result')
    code, full = r['code'], DIFFICULTIES[r['difficulty']]
    seats = [p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND seat = 1 ORDER BY rowid", (code,))]
    guesses = {(g['user_id'], g['round']): g for g in c.execute("SELECT * FROM room_guesses WHERE code = ? AND round <= ?", (code, upto))}
    shop, milked = room_shop_rows(c, code)
    ids = json.loads(r['locations'])[:upto]
    where = {l[0]: (l[1], l[2]) for l in c.execute(
        f"SELECT location_id, x_position, z_position FROM locations WHERE location_id IN ({', '.join('?' * len(ids))})", ids)} if ids else {}
    st = {u: {'left': full, 'out': None, 'delta': 0, 'emeralds': 0, 'milk': 0, 'milk_bought': 0, 'survived': 0, 'close': 0}
          for u in seats}
    for row in shop:
        if row['buyer'] in st:
            st[row['buyer']]['emeralds'] -= PRICES[row['item']]
            if row['item'] == 'milk':
                st[row['buyer']]['milk'] += 1
                st[row['buyer']]['milk_bought'] += 1
    for u, n in milked:
        if u in st:
            st[u]['milk'] -= 1
    for n in range(1, upto + 1):
        alive = [u for u in seats if st[u]['out'] is None]
        if len(alive) <= 1:
            break
        loc = where[ids[n - 1]]
        for u in alive:
            s, fx, g = st[u], room_effects(shop, milked, u, n), guesses.get((u, n))
            swift = 'swiftness' if 'swiftness' in fx else None
            safe, far, cap = zone(n, swift)
            hp = s['left']
            spent = g['time'] if g else room_time(r['difficulty'], fx)
            # Wither: half a heart every WITHER_EVERY seconds, k times as often at level k
            wither = int(spent * fx.get('wither', 0) // WITHER_EVERY)
            if g and g['x'] is not None:
                d = math.hypot(loc[0] - g['x'], loc[1] - g['z'])
                damage, points = hurt(d, n, swift), g['score']
                earned = EMERALDS[0] if d <= NEAR else EMERALDS[1] if d <= safe else EMERALDS[2] if d < far else 0
            else:
                d, damage, points, earned = None, cap, 0, 0   # no pin when the clock ran out: the creeper
            after, heal = hp - damage - wither, 0
            if after > 0 and d is not None:
                if d <= safe:
                    heal += REGEN * fx.get('regeneration', 0)
                s['close'] = s['close'] + 1 if d <= NEAR else 0
                if s['close'] == 2:
                    heal, s['close'] = heal + 1, 0
            else:
                s['close'] = 0
            after = min(full, after + heal) if after > 0 else 0
            s['left'] = after
            s['emeralds'] += earned
            if after > 0:
                s['survived'] += 1
            else:
                s['out'] = n
            if n == upto:
                s['delta'] = after - hp
                s['result'] = {"x": g and g['x'], "z": g and g['z'], "aim_x": g and g['aim_x'], "aim_z": g and g['aim_z'],
                               "distance": d, "damage": damage, "wither": wither, "heal": heal if after > 0 else 0,
                               "points": points, "earned": earned, "effects": fx, "creeper": d is None,
                               "safe": safe, "far": far, "kill": kill_radius(n, swift, hp - wither)}
    return st

def next_fog(c, r):
    # does the next round's location have its fog photo (Blindness possible)?
    ids = json.loads(r['locations'])
    return r['round'] < len(ids) and bool(c.execute("SELECT fog_url IS NOT NULL FROM locations WHERE location_id = ?",
                                                    (ids[r['round']],)).fetchone()[0])

def wares(c, r, s):
    # what one player may buy in this shop, with the prices: potions to throw
    # (Blindness only where the next place has its fog photo); for the
    # living, Regeneration and, if the room has it, milk (MILK_BUYS at most,
    # then out of stock)
    fog = next_fog(c, r)
    return {k: p for k, p in PRICES.items() if (k not in SELF or s['out'] is None) and (k != 'blindness' or fog)
            and (k != 'milk' or (r['milk'] and s['milk_bought'] < MILK_BUYS))}

def bought(c, r, uid):
    # purchases a player made in the shop open now
    return c.execute("SELECT COUNT(*) FROM room_shop WHERE code = ? AND round = ? AND buyer = ?",
                     (r['code'], r['round'] + 1, uid)).fetchone()[0]

def shopping(c, r, uid, s):
    # can this player still buy something here: emeralds enough, and fewer than SHOP_MAX purchases
    prices = wares(c, r, s).values()
    return bool(prices) and s['emeralds'] >= min(prices) and bought(c, r, uid) < SHOP_MAX

def present(c, r):
    # who a round or the shop still waits for
    return {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND last_seen > ?", (r['code'], time.time() - GONE))}

def shop_shut(c, r, st):
    # the shop closes after SHOP seconds, or once everyone here is ready;
    # who cannot buy anything more is ready already
    if time.time() >= r['round_end'] + REVEAL + SHOP:
        return True
    ready = {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND ready = ?", (r['code'], r['round']))}
    return not any(shopping(c, r, u, st[u]) for u in present(c, r) & set(st) - ready)

def survival_room_tick(c, r):
    # a round closes once everyone alive and here has guessed, or is past their
    # own clock; then the reveal, the shop, the potions bought, PREP, the next round
    now, n, code = time.time(), r['round'], r['code']
    if r['round_end'] is None:
        if now < r['round_start']:
            return r   # potions flying, picture loading
        shop, milked = room_shop_rows(c, code)
        alive = {u for u, s in survivors(c, r, n - 1).items() if s['out'] is None}
        done = {g[0] for g in c.execute("SELECT user_id FROM room_guesses WHERE code = ? AND round = ?", (code, n))}
        ends = {u: survival_deadline(r, room_effects(shop, milked, u, n)) for u in alive - done}
        here = present(c, r)
        if any(now < end + GRACE for u, end in ends.items() if u in here):
            return r
        c.execute("UPDATE rooms SET round_end = ? WHERE code = ?", (now, code))
        # who did not guess: no pin (the creeper), and the time they had, for Wither
        for u, end in ends.items():
            c.execute("""INSERT OR IGNORE INTO room_guesses (code, user_id, round, x, z, score, at, time)
                    VALUES (?, ?, ?, NULL, NULL, 0, ?, ?)""", (code, u, n, now, max(0, min(now, end) - r['round_start'])))
        r = find_room(c, code)
        # the random potions of the next round, thrown with the reveal (never
        # two random ones in a row for the same player, as alone)
        left = [u for u, s in survivors(c, r, n).items() if s['out'] is None]
        if len(left) >= 2 and n < r['rounds']:
            fog = next_fog(c, r)
            had = {row['target'] for row in shop if row['round'] == n and row['buyer'] is None}
            for u in left:
                drawn = potion(r['difficulty'], n + 1, u in had, fog)
                if drawn:
                    c.execute("INSERT INTO room_shop (code, round, buyer, target, item, at) VALUES (?, ?, NULL, ?, ?, ?)",
                              (code, n + 1, u, drawn, now))
        return r
    if now < r['round_end'] + REVEAL:
        return r
    st = survivors(c, r, n)
    if sum(s['out'] is None for s in st.values()) <= 1 or n >= r['rounds']:
        c.execute("UPDATE rooms SET state = 'finished' WHERE code = ?", (code,))
        r = find_room(c, code)
        for u in st:
            survival_room_record(c, r, u)
        return r
    if not shop_shut(c, r, st):
        return r
    thrown = c.execute(f"""SELECT 1 FROM room_shop WHERE code = ? AND round = ? AND buyer IS NOT NULL
            AND item NOT IN {SELF}""", (code, n + 1)).fetchone()
    c.execute("UPDATE rooms SET round = round + 1, round_start = ?, round_end = NULL WHERE code = ?",
              (now + (THROW if thrown else 0) + PREP, code))
    return find_room(c, code)

def survival_room_record(c, r, uid):
    # a finished game on the Survival leaderboard of its difficulty, like a run
    # alone: the locations survived, then the points (not for guests)
    row = c.execute("SELECT recorded FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()
    if not row or row[0] or c.execute("SELECT COALESCE(guest, 0) FROM users WHERE id = ?", (uid,)).fetchone()[0]:
        return
    s = survivors(c, r, r['round']).get(uid)
    if not s or not s['survived']:
        return
    c.execute("UPDATE room_players SET recorded = 1 WHERE code = ? AND user_id = ?", (r['code'], uid))
    points, spent = c.execute("SELECT COALESCE(SUM(score), 0), COALESCE(SUM(time), 0) FROM room_guesses WHERE code = ? AND user_id = ?",
                              (r['code'], uid)).fetchone()
    c.execute("""INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode, difficulty, points, room, milk)
            VALUES (?, ?, ?, 'No', '', NULL, ?, 'survival', ?, ?, ?, ?)""",
            (uid, s['survived'], date.today(), round(spent, 2), r['difficulty'], points, r['code'], r['milk']))

def survival_room_guess(c, r, me, n):
    # a guess in its round, within the player's own clock (Nausea: the hand shakes)
    now, uid = time.time(), me['user_id']
    if (not me['live'] or r['state'] != 'playing' or n != r['round'] or r['round_end'] is not None
            or now < r['round_start'] or uid not in guessers(c, r)):
        return False
    shop, milked = room_shop_rows(c, r['code'])
    fx = room_effects(shop, milked, uid, n)
    deadline = survival_deadline(r, fx)
    if now > deadline + GRACE or c.execute("SELECT 1 FROM room_guesses WHERE code = ? AND user_id = ? AND round = ?",
                                           (r['code'], uid, n)).fetchone():
        return False
    x = z = aim_x = aim_z = None
    if request.form.get('x'):
        try:
            x, z = float(request.form['x']), float(request.form['z'])
        except (KeyError, ValueError):
            return False
        if not (math.isfinite(x) and math.isfinite(z)):
            return False
        if fx.get('nausea'):
            # k times as far at level k
            k = fx['nausea']
            angle = secrets.randbelow(360000) / 1000 * math.pi / 180
            off = k * (SHAKE[0] + secrets.randbelow((SHAKE[1] - SHAKE[0]) * 1000) / 1000)
            aim_x, aim_z = x, z
            x, z = round(x + off * math.cos(angle)), round(z + off * math.sin(angle))
    loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (json.loads(r['locations'])[n - 1],)).fetchone()
    c.execute("""INSERT OR IGNORE INTO room_guesses (code, user_id, round, x, z, score, at, time, aim_x, aim_z)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r['code'], uid, n, x, z, guess_score(x, z, loc) if x is not None else 0, now,
             min(now, deadline) - r['round_start'], aim_x, aim_z))
    return True

def survival_phase(r, now):
    if r['state'] != 'playing':
        return r['state']   # waiting, finished
    if r['round_end'] is None:
        return 'throw' if now < r['round_start'] - PREP else 'prep' if now < r['round_start'] else 'guess'
    return 'reveal' if now < r['round_end'] + REVEAL else 'shop'

def survival_view(c, r, me, out, now):
    # what a player of a survival room may know: everyone's hearts, what hits
    # whom once the shop is shut (the random potions as soon as thrown), their
    # own emeralds and milk; the answer only once the round is over
    n, code, uid = r['round'], r['code'], me['user_id']
    phase = survival_phase(r, now)
    out.update({"difficulty": r['difficulty'], "max": DIFFICULTIES[r['difficulty']], "phase": phase})
    if phase == 'waiting':
        return out
    closed = phase in ('reveal', 'shop', 'finished')
    st = survivors(c, r, n if closed else n - 1)
    shop, milked = room_shop_rows(c, code)
    names = {p['uid']: p['name'] for p in out['players']}
    ready = {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND ready = ?", (code, n))}
    # the potions of the round being played, or of the next one once thrown
    upcoming = n + 1 if closed else n
    for p in out['players']:
        s = st.get(p['uid'])
        if not s:
            continue
        p.update({"left": s['left'], "out": s['out'], "delta": s['delta'], "survived": s['survived']})
        if s['out'] is None and phase != 'finished':
            # before the shop shuts, only the random potions are known
            known = [row for row in shop if row['buyer'] is None] if closed else shop
            p['effects'] = room_effects(known, milked, p['uid'], upcoming)
            p['milked'] = (p['uid'], upcoming) in milked
        if phase == 'shop':
            # who cannot buy anything more is ready already (shop_shut)
            p['ready'] = p['uid'] in ready or not shopping(c, r, p['uid'], s)
        if closed and 'result' in s:
            p['result'] = {k: v for k, v in s['result'].items() if k != 'earned'}
    mine = st.get(uid)
    out['playing'] = bool(mine and mine['out'] is None and me['live'] and phase != 'finished')
    if mine:
        out['me'] = {"emeralds": mine['emeralds'], "milk": mine['milk'], "milk_left": MILK_BUYS - mine['milk_bought'],
                     "earned": mine.get('result', {}).get('earned') if closed else None}
        if phase == 'shop':
            out['me']['buys_left'] = SHOP_MAX - bought(c, r, uid)
    if phase == 'shop':
        out['phase_left'] = max(0, r['round_end'] + REVEAL + SHOP - now)
        if mine:
            out['wares'] = wares(c, r, mine)
            # what this player bought in this shop (the others' stay secret until it shuts)
            out['bought'] = [{"item": row['item'], "to": names.get(row['target'], '?')} for row in shop
                             if row['round'] == n + 1 and row['buyer'] == uid]
    elif phase == 'reveal':
        out['phase_left'] = max(0, r['round_end'] + REVEAL - now)
    elif phase in ('throw', 'prep'):
        out['phase_left'] = max(0, r['round_start'] - (PREP if phase == 'throw' else 0) - now)
        out['starts_in'] = max(0, r['round_start'] - now)
    # the potions bought for this round, thrown for everyone to see
    if not closed:
        out['throws'] = [{"by": names.get(row['buyer'], '?'), "item": row['item'], "to": names.get(row['target'], '?')}
                         for row in shop if row['round'] == n and row['buyer'] is not None and row['item'] not in SELF]
    ids = json.loads(r['locations'])
    if not closed:
        # the picture, from the shop's close on: in the fog under Blindness
        fx = room_effects(shop, milked, uid, n) if out['playing'] else {}
        out['url'] = tile_url(c, ids[n - 1], 'room:%s:%d' % (code, n), fog = 'blindness' in fx)
        if out['playing']:
            out.update({"time": room_time(r['difficulty'], fx), "answered": bool(c.execute(
                "SELECT 1 FROM room_guesses WHERE code = ? AND user_id = ? AND round = ?", (code, uid, n)).fetchone())})
            if phase == 'guess':
                # elapsed: since the start, for what counts from it (Darkness, Wither)
                out.update({"time_left": max(0, survival_deadline(r, fx) - now), "elapsed": now - r['round_start']})
    elif n:
        loc = c.execute("SELECT x_position, z_position FROM locations WHERE location_id = ?", (ids[n - 1],)).fetchone()
        totals = {p['uid']: p['total'] for p in out['players']}
        out['reveal'] = {"X": loc[0], "Z": loc[1], "guesses": [
            {"name": names[u], "x": s['result']['x'], "z": s['result']['z'], "score": s['result']['points'], "upto": totals.get(u, 0)}
            for u, s in st.items() if 'result' in s and u in names]}
    return out

@app.route("/api/room/<code>/buy", methods=['POST'])
def room_buy(code):
    # survival, in the shop: a potion thrown at another player (target), or
    # Regeneration or milk for oneself, paid in emeralds
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['mode'] != 'survival':
            return jsonify({"success": False})
        r = tick(c, r)
        uid, item = me['user_id'], request.form.get('item', '')
        target = uid if item in SELF else request.form.get('target', type = int)
        if (survival_phase(r, time.time()) != 'shop' or request.form.get('round') != str(r['round'])
                or c.execute("SELECT ready FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()[0] == r['round']):
            return jsonify({"success": False, "error": "The shop is closed"})
        st = survivors(c, r, r['round'])
        s = st.get(uid)
        if not s or item not in wares(c, r, s):
            return jsonify({"success": False, "error": "You cannot buy that"})
        if target == uid and item not in SELF or target not in st or st[target]['out'] is not None:
            return jsonify({"success": False, "error": "Pick another player"})
        if s['emeralds'] < PRICES[item]:
            return jsonify({"success": False, "error": "Not enough emeralds"})
        done = bought(c, r, uid)
        if done >= SHOP_MAX:
            return jsonify({"success": False, "error": "That's %d for this round" % SHOP_MAX})
        c.execute("INSERT INTO room_shop (code, round, buyer, target, item, at) VALUES (?, ?, ?, ?, ?, ?)",
                  (r['code'], r['round'] + 1, uid, target, item, time.time()))
    return jsonify({"success": True, "emeralds": s['emeralds'] - PRICES[item], "buys_left": SHOP_MAX - done - 1})

@app.route("/api/room/<code>/ready", methods=['POST'])
def room_ready(code):
    # survival: done with the shop (the shop closes once everyone is)
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['mode'] != 'survival':
            return jsonify({"success": False})
        r = tick(c, r)
        if survival_phase(r, time.time()) != 'shop' or request.form.get('round') != str(r['round']):
            return jsonify({"success": False})
        c.execute("UPDATE room_players SET ready = ? WHERE code = ? AND user_id = ?", (r['round'], r['code'], me['user_id']))
        tick(c, find_room(c, r['code']))
    return jsonify({"success": True})

@app.route("/api/room/<code>/milk", methods=['POST'])
def room_milk(code):
    # survival: a bucket drunk before the round (as the potions fly or the
    # picture loads, a second into the round at most): nothing hits this round
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['mode'] != 'survival':
            return jsonify({"success": False})
        r = tick(c, r)
        uid, n, now = me['user_id'], r['round'], time.time()
        if (r['state'] != 'playing' or r['round_end'] is not None or request.form.get('round') != str(n)
                or now > r['round_start'] + GRACE):
            return jsonify({"success": False})
        s = survivors(c, r, n - 1).get(uid)
        shop, milked = room_shop_rows(c, r['code'])
        if not s or s['out'] is not None or s['milk'] < 1 or not room_effects(shop, milked, uid, n):
            return jsonify({"success": False})
        c.execute("INSERT OR IGNORE INTO room_milk (code, round, user_id, at) VALUES (?, ?, ?, ?)", (r['code'], n, uid, now))
    return jsonify({"success": True})

# ---------- Multiplayer: worlds ----------
# Public games, no code to share (Yasuro: "super duper easy for players to
# quickly play with others"), named after Wynncraft's worlds. One kind of
# world per card of the Multiplayer page, and always a lobby open for each:
# full (WORLD_MAX) or under way, another opens at once (open_world). Nobody
# hosts: the settings are the card's, every province (choosing them is for
# custom games), and the game starts by itself WORLD_COUNTDOWN seconds after
# half the players are ready (2 at least), WORLD_ALL_READY once all are; the
# countdown never stops for someone changing their mind, only when fewer
# than 2 are left. Whoever is not ready then is out of the world (Yasuro:
# "anyone who didn't click ready and missed the game should be kicked"),
# back on the Multiplayer page with a word why; except who came in the
# last WORLD_GRACE seconds, who plays. After the results everyone goes on
# together to the open lobby, where Ready is asked again: the check comes
# back every game. A lobby counts a player for GONE seconds after their last
# poll, not AWAY: a tab in the background stays silent most of a minute, and
# someone ready reading Discord would have been thrown out (see GONE).
# The cards are ordered for who is there now, then how much each was played
# lately (a game counts half as much every WORLD_HALF_LIFE days), and a new
# kind (since) is helped up for its first NEW_FOR days, so it is not buried
# under the old ones.

WORLDS = {   # key: (title, line under it, settings, (rank, suit) of its card, since)
    'survival-normal': ('Survival', 'Normal', {'mode': 'survival', 'difficulty': 'normal', 'milk': 0}, (10, 'hearts'), None),
    'survival-hard': ('Survival', 'Hard', {'mode': 'survival', 'difficulty': 'hard', 'milk': 0}, (5, 'hearts'), None),
    'survival-hardcore': ('Survival', 'Hardcore', {'mode': 'survival', 'difficulty': 'hardcore', 'milk': 0}, (1, 'hardcore'), None),
    'classic': ('Classic', '5 rounds', {'mode': 'classic', 'rounds': 5}, (5, 'pins'), None),
    'survival-normal-milk': ('Survival', 'Normal · Milk', {'mode': 'survival', 'difficulty': 'normal', 'milk': 1}, (10, 'hearts'), None),
    'survival-hard-milk': ('Survival', 'Hard · Milk', {'mode': 'survival', 'difficulty': 'hard', 'milk': 1}, (5, 'hearts'), None),
    'survival-hardcore-milk': ('Survival', 'Hardcore · Milk', {'mode': 'survival', 'difficulty': 'hardcore', 'milk': 1}, (1, 'hardcore'), None),
}
# how each lies on the table (tilt, wear), the same wherever the order puts it
WORLD_LOOKS = [(-1.5, 0), (1, 1), (2, 3), (-0.5, 2), (-2, 1), (1.5, 0), (-1, 2)]
WORLD_MAX = 16          # players in a lobby, then another opens
WORLD_COUNTDOWN = 15    # seconds from half ready to the start
WORLD_ALL_READY = 3     # ...cut to this once everyone is
WORLD_GRACE = 10        # who came in this late before the start plays, ready or not
WORLD_RESULTS = 20      # seconds on the results, then on to the next lobby
WORLD_HALF_LIFE = 3     # days: a game played that long ago counts half
NEW_FOR = 14            # days a new kind of world is helped up the page
RULES = {
    'survival': "The same place for everyone. Guess close to keep your hearts, earn emeralds, throw potions at the others. The last one standing wins.",
    'classic': "Five places, the same for everyone. The closer you guess, the more points. The most points wins.",
}

with connect() as c:
    if 'world' not in [col[1] for col in c.execute("PRAGMA table_info(rooms)")]:
        c.execute("ALTER TABLE rooms ADD COLUMN world TEXT")         # the kind of world, None: a custom game
        c.execute("ALTER TABLE rooms ADD COLUMN starts_at REAL")     # a world's countdown
    if 'lobby_ready' not in [col[1] for col in c.execute("PRAGMA table_info(room_players)")]:
        c.execute("ALTER TABLE room_players ADD COLUMN lobby_ready INTEGER DEFAULT 0")
        c.execute("ALTER TABLE room_players ADD COLUMN joined REAL")
    if 'why' not in [col[1] for col in c.execute("PRAGMA table_info(room_bans)")]:
        c.execute("ALTER TABLE room_bans ADD COLUMN why TEXT")       # 'away': not ready when a world started
    c.execute("CREATE INDEX IF NOT EXISTS rooms_world ON rooms (world, state)")

def world_info(key):
    title, line, settings, (rank, suit), since = WORLDS[key]
    return {'key': key, 'title': title, 'line': line, 'rank': rank, 'suit': suit, 'milk': bool(settings.get('milk')),
            'rules': RULES[settings['mode']], 'look': WORLD_LOOKS[list(WORLDS).index(key)]}

def world_settings(key):
    s = WORLDS[key][2]
    if s['mode'] == 'survival':
        return {'mode': 'survival', 'provinces': PROVINCES, 'rounds': SURVIVAL_ROUNDS, 'time_limit': -1, 'look': 0,
                'difficulty': s['difficulty'], 'milk': s['milk']}
    return {'mode': s['mode'], 'provinces': PROVINCES, 'rounds': s['rounds'], 'time_limit': -1, 'look': 0,
            'difficulty': None, 'milk': 0}

def world_here(c, code):
    return c.execute("SELECT COUNT(*) FROM room_players WHERE code = ? AND last_seen > ?", (code, time.time() - GONE)).fetchone()[0]

def open_world(c, key, uids):
    # the lobby of this kind to send these players to: the fullest with room
    # for them, so that people gather, and nobody there named like one of
    # them (its door would turn the second Steve away, again and again);
    # else a new one
    best = None
    for (code,) in c.execute("SELECT code FROM rooms WHERE world = ? AND state = 'waiting' ORDER BY rowid DESC", (key,)).fetchall():
        n = world_here(c, code)
        if n + len(uids) <= WORLD_MAX and (best is None or n > best[1]) and not name_clash(c, code, uids):
            best = (code, n)
    return best[0] if best else new_room(c, None, world_settings(key), world = key)

def world_tick(c, r):
    # a world's lobby: the countdown and the start; once finished: the next lobby
    now, code = time.time(), r['code']
    if r['state'] == 'waiting':
        here = c.execute("SELECT user_id, lobby_ready, joined FROM room_players WHERE code = ? AND last_seen > ?",
                         (code, now - GONE)).fetchall()
        ready = sum(p['lobby_ready'] for p in here)
        start = r['starts_at']
        if len(here) < 2:
            start = None
        elif start is None and ready >= max(2, math.ceil(len(here) / 2)):
            start = now + WORLD_COUNTDOWN
        if start is not None and ready == len(here):
            start = min(start, now + WORLD_ALL_READY)
        if start != r['starts_at']:
            c.execute("UPDATE rooms SET starts_at = ? WHERE code = ?", (start, code))
        if start is not None and now >= start:
            playing = {p['user_id'] for p in here if p['lobby_ready'] or (p['joined'] or 0) > now - WORLD_GRACE}
            if len(playing) < 2:
                c.execute("UPDATE rooms SET starts_at = NULL WHERE code = ?", (code,))
            else:
                # the game starts without whoever was not ready: out of the world
                for (uid,) in c.execute("SELECT user_id FROM room_players WHERE code = ?", (code,)).fetchall():
                    if uid not in playing:
                        c.execute("DELETE FROM room_players WHERE code = ? AND user_id = ?", (code, uid))
                        c.execute("INSERT OR REPLACE INTO room_bans (code, user_id, why) VALUES (?, ?, 'away')", (code, uid))
                c.execute("UPDATE room_players SET seat = 1 WHERE code = ?", (code,))
                c.execute("UPDATE rooms SET state = 'playing', round = 1, round_start = ?, round_end = NULL WHERE code = ?",
                          (now + (PREP if r['mode'] == 'survival' else 0), code))
        return find_room(c, code)
    if r['state'] == 'finished' and not r['next_code'] and now >= (r['round_end'] or now) + REVEAL + WORLD_RESULTS:
        # everyone still on the results moves on together
        come = [u for (u,) in c.execute("SELECT user_id FROM room_players WHERE code = ? AND live = 1 AND last_seen > ?",
                                        (code, now - GONE))]
        c.execute("UPDATE rooms SET next_code = ? WHERE code = ?", (open_world(c, r['world'], come), code))
        return find_room(c, code)
    return r

@app.route("/api/room/<code>/lobby", methods=['POST'])
def room_lobby(code):
    # Ready, or not any more, in a world's lobby. Or gone: the page closed
    # (or left for another), which says so as it goes. Else the lobby would
    # count it here for GONE more seconds, and a player who was ready would
    # get a seat in the game: hearts lost to the creeper, a loss, the streak
    # broken, without having played
    with room_tx() as c:
        r, me = member(c, code)
        if not r or not r['world'] or r['state'] != 'waiting':
            return jsonify({"success": False})
        if request.form.get('gone'):
            c.execute("UPDATE room_players SET last_seen = 0 WHERE code = ? AND user_id = ?", (r['code'], me['user_id']))
        else:
            c.execute("UPDATE room_players SET lobby_ready = ? WHERE code = ? AND user_id = ?",
                      (int(request.form.get('ready') == '1'), r['code'], me['user_id']))
        world_tick(c, find_room(c, r['code']))
    return jsonify({"success": True})

def world_counts(c):
    # each kind of world now: who waits (and the heads of the first five),
    # how many play. {key: {waiting, playing, heads}}
    now, out = time.time(), {}
    for key in WORLDS:
        waiting = c.execute('''SELECT u.id, u.avatar, u.mc_uuid FROM room_players p JOIN rooms r ON r.code = p.code JOIN users u ON u.id = p.user_id
            WHERE r.world = ? AND r.state = 'waiting' AND p.last_seen > ? ORDER BY p.rowid''', (key, now - GONE)).fetchall()
        playing = c.execute('''SELECT COUNT(*) FROM room_players p JOIN rooms r ON r.code = p.code
            WHERE r.world = ? AND r.state = 'playing' AND p.last_seen > ?''', (key, now - GONE)).fetchone()[0]
        out[key] = {'waiting': len(waiting), 'playing': playing, 'heads': [avatar_url(u) for u in waiting[:5]]}
    return out

def world_list(c):
    # every kind of world, as world_counts, and how much it was played
    # lately: best first, the most played marked
    now, rows, counts = time.time(), [], world_counts(c)
    for key in WORLDS:
        lately = sum(n * .5 ** ((now - t) / 86400 / WORLD_HALF_LIFE) for t, n in c.execute(
            '''SELECT r.round_start, COUNT(*) FROM rooms r JOIN room_players p ON p.code = r.code
            WHERE r.world = ? AND r.state != 'waiting' AND r.round_start > ? GROUP BY r.code''', (key, now - 30 * 86400)))
        since = WORLDS[key][4]
        fresh = since and max(0, 1 - (date.today() - date.fromisoformat(since)).days / NEW_FOR)
        w = counts[key]
        rows.append(dict(world_info(key), **w, lately = lately, new = bool(fresh),
                         score = 100 * w['waiting'] + 40 * w['playing'] + lately + 60 * (fresh or 0)))
    most = max(rows, key = lambda w: w['lately'])
    if most['lately'] >= 1:
        most['most'] = True
    return sorted(rows, key = lambda w: -w['score'])

@app.route("/multiplayer")
def multiplayer():
    # the worlds as cards; ?join=<kind>: straight into its open lobby
    key = request.args.get('join')
    if key:
        if key not in WORLDS:
            return redirect('multiplayer')
        if not session.get('user_id'):
            return redirect('guest?next=' + quote('multiplayer?join=' + key))
        with room_tx() as c:
            code = open_world(c, key, [session['user_id']])
        return redirect('room?code=' + code)
    with connect() as c:
        worlds = world_list(c)
    return render_template('multiplayer.html', worlds = worlds, missed = request.args.get('missed'))

@app.route("/api/multiplayer")
def multiplayer_counts():
    # the page's numbers, every few seconds: only the counts (its order stays,
    # cards do not jump, so the month of games behind it is not added up again)
    with connect() as c:
        return jsonify({"success": True, "worlds": world_counts(c)})

# ---------- Moderation ----------
# Staff ranks, as Wynncraft's chat tags ([Admin], [Mod]...), each with its
# powers, under one rule (Yasuro: "all have different powers over each other
# so no one can just delete everything because we have the highest role"):
# one acts only on someone of a lower rank, gives only ranks lower than one's
# own, and nothing is ever destroyed: a hidden message can be shown again, a
# ban lifted, an old name stays in the log, and the log itself cannot be
# erased from the site. The owner is set here: nobody can take it away.

OWNER = 1                 # Yasuro's account
RANKS = {4: 'Owner', 3: 'Admin', 2: 'Moderator', 1: 'Helper'}
MAY = {                   # the lowest rank with each power
    'pictures': 1, 'hide': 1, 'mute': 1, 'reports': 1, 'players': 1,
    'long_mute': 2, 'ban': 2, 'rename': 2, 'log': 2,
    'contact': 2,         # the messages of the contact page (an email address is personal)
    'staff': 3,           # give and take ranks (below one's own)
    'tags': 2,            # give and take tags
    'make_tags': 3,       # make a tag, or put one away
}
HELPER_MUTE = 3600        # a Helper mutes for an hour at most

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS staff (user_id INTEGER PRIMARY KEY, rank INTEGER, by INTEGER, at REAL);
        CREATE TABLE IF NOT EXISTS mod_log (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, by INTEGER,
            action TEXT, target INTEGER, details TEXT, reason TEXT);
    ''')

def rank_of(c, uid):
    if uid == OWNER:
        return 4
    row = c.execute("SELECT rank FROM staff WHERE user_id = ?", (uid,)).fetchone()
    return row[0] if row else 0

def ranks_of(c, uids):
    # rank_of for many players in one look: {id: rank}
    uids = list(uids)
    out = {u: 0 for u in uids}
    out.update(c.execute(f"SELECT user_id, rank FROM staff WHERE user_id IN ({','.join('?' * len(uids))})", uids).fetchall())
    if OWNER in out:
        out[OWNER] = 4
    return out

def my_rank(c):
    return rank_of(c, session['user_id']) if session.get('loggedin') else 0

def may(c, power, target = None):
    # may this session's player use this power (on that player)?
    r = my_rank(c)
    return r >= MAY[power] and (target is None or rank_of(c, target) < r)

def logged(c, action, target, details = '', reason = ''):
    c.execute("INSERT INTO mod_log (at, by, action, target, details, reason) VALUES (?, ?, ?, ?, ?, ?)",
              (time.time(), session['user_id'], action, target, details, reason))

# Tags: a small word next to a name, Wynncraft style, and only one (Yasuro:
# "don't make them too obnoxious"): the staff rank first, else a tag the
# staff gave (newest first), else a "#1" earned by leading a board, which
# moves by itself to whoever leads it next. The profile shows them all.
TAG_COLORS = ('gold', 'red', 'orange', 'green', 'teal', 'purple', 'stone')
TOPS = {'at': 0, 'tags': {}}
TOPS_EVERY = 120          # seconds a computed "#1" list is kept (the levels are long to work out)

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, label TEXT, color TEXT,
            by INTEGER, at REAL, retired INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS user_tags (user_id INTEGER, tag_id INTEGER, by INTEGER, at REAL,
            PRIMARY KEY (user_id, tag_id));
    ''')
    # the tag a player picked to show, when they have several (see /account)
    if 'shown_tag' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN shown_tag TEXT")

def top_tags(c):
    # who leads each board: {user id: ["#1 Survival Hard", ...]}. Worked out
    # again when due, but never on a connection that holds the write lock
    # (a room's, a write already made): the levels take long to add up
    # (0.2 s for the 124 accounts of October 2026, more with every player),
    # and every room would wait. room_state asks before taking its lock
    if time.time() - TOPS['at'] > TOPS_EVERY and not c.in_transaction:
        tops = {}
        boards = [('#1 Survival ' + d.capitalize(), board(c, {'mode': 'survival', 'difficulty': d})) for d in DIFFICULTIES]
        boards.append(('#1 Classic', board(c, {'mode': 'classic', 'provinces': str(PROVINCES), 'nolook': 'No', 'rounds': '5'})))
        boards += [('#1 Level', ladder(c, 'levels')), ('#1 Wins', ladder(c, 'wins'))]
        for label, rows in boards:
            if rows:
                tops.setdefault(rows[0]['id'], []).append(label)
        TOPS.update(at = time.time(), tags = tops)
    return TOPS['tags']

def tags_of(c, uids):
    # every tag of these players, in the order they are shown: {id: [{label, color}]}
    uids = list({u for u in uids if u})
    out = {u: [] for u in uids}
    if not uids:
        return out
    marks = ','.join('?' * len(uids))
    for u, rank in [(OWNER, 4)] + c.execute(f"SELECT user_id, rank FROM staff WHERE user_id IN ({marks})", uids).fetchall():
        if u in out:
            out[u].append({"label": RANKS[rank], "color": 'rank-%d' % rank})
    for t in c.execute(f'''SELECT ut.user_id, t.label, t.color FROM user_tags ut JOIN tags t ON t.id = ut.tag_id
            WHERE ut.user_id IN ({marks}) AND t.retired = 0 ORDER BY ut.at DESC''', uids):
        out[t[0]].append({"label": t[1], "color": 'tag-' + t[2]})
    for u, labels in top_tags(c).items():
        if u in out:
            out[u] += [{"label": l, "color": 'tag-top'} for l in labels]
    # the one picked goes first, while the player still has it
    for u, label in c.execute(f"SELECT id, shown_tag FROM users WHERE id IN ({marks}) AND shown_tag IS NOT NULL", uids):
        out[u].sort(key = lambda t: t['label'] != label)
    return out

def tag_of(c, uids):
    # the one tag shown next to each name
    return {u: (t[0] if t else None) for u, t in tags_of(c, uids).items()}

@app.context_processor
def staff_menu():
    # the Moderation button of the menu, for the staff only
    def rank():
        if not session.get('loggedin'):
            return 0
        with connect() as c:
            return my_rank(c)
    def waiting():
        with connect() as c:
            return len(pictures_waiting(c)) + len(reports_waiting(c)) + (contact_waiting(c) if my_rank(c) >= MAY['contact'] else 0)
    return {'my_rank': rank, 'RANKS': RANKS, 'mod_waiting': waiting}

@app.route("/moderation")
def moderation():
    with connect() as c:
        r = my_rank(c)
        # each tab says how many wait; the first one with something opens
        waiting = {'reports': len(reports_waiting(c)), 'photos': len(pictures_waiting(c)),
                   'messages': contact_waiting(c) if r >= MAY['contact'] else 0}
        first = next((k for k in waiting if waiting[k]), 'reports')
    if not r:
        return render_template('apology.html', message = "This page is for the moderation team"), 403
    return render_template('moderation.html', rank = r, may = {k: r >= v for k, v in MAY.items()}, first = first, waiting = waiting)

@app.route("/api/mod/staff")
def mod_staff():
    # the team: every rank, who gave it, and what this player may give
    with connect() as c:
        r = my_rank(c)
        if not r:
            return jsonify({"success": False}), 403
        rows = [{"id": OWNER, "rank": 4, "by": None, "at": None}] + [dict(x) for x in c.execute(
            "SELECT user_id AS id, rank, by, at FROM staff WHERE user_id != ? ORDER BY rank DESC, at", (OWNER,))]
        names = {u['id']: u['username'] for u in c.execute(
            f"SELECT id, username FROM users WHERE id IN ({','.join('?' * len(rows))}) OR id IN (SELECT by FROM staff)",
            [x['id'] for x in rows])}
        for x in rows:
            x.update(name = names.get(x['id'], '?'), by = names.get(x['by']) if x['by'] else None, tag = RANKS[x['rank']],
                     mine = x['rank'] < r and r >= MAY['staff'])
    return jsonify({"success": True, "rank": r, "staff": rows,
                    "give": {k: v for k, v in RANKS.items() if k < r} if r >= MAY['staff'] else {}})

@app.route("/api/mod/rank", methods=['POST'])
def mod_rank():
    # give, change or take a rank (0 takes it): only below one's own, only to
    # someone below one's own, never the owner, never a guest. A player's card
    # names the player by id; the team tab by name: then the account first,
    # never an older guest of the same name ("Bob" played as a guest, then
    # made the account "Bob")
    name, reason = ' '.join(request.form.get('name', '').split()), request.form.get('reason', '').strip()[:200]
    new, uid = request.form.get('rank', type = int), request.form.get('id', type = int)
    with room_tx() as c:
        r = my_rank(c)
        user = (c.execute("SELECT id, username, COALESCE(guest, 0) AS guest FROM users WHERE id = ?", (uid,)) if uid else
                c.execute("""SELECT id, username, COALESCE(guest, 0) AS guest FROM users WHERE username = ? COLLATE NOCASE
                    ORDER BY COALESCE(guest, 0), id""", (name,))).fetchone()
        if r < MAY['staff']:
            return jsonify({"success": False, "error": "Only an Admin can change the team"}), 403
        if not user:
            return jsonify({"success": False, "error": "No player with this name"})
        if user['guest']:
            return jsonify({"success": False, "error": user['username'] + " is a guest name, not an account: ranks are for accounts only"})
        old = rank_of(c, user['id'])
        if new not in [0] + list(RANKS) or new >= r or old >= r:
            return jsonify({"success": False, "error": "You can only give ranks below yours, to players below you"})
        if new == old:
            return jsonify({"success": False, "error": "Nothing to change"})
        if new:
            c.execute("INSERT INTO staff (user_id, rank, by, at) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET rank = excluded.rank, by = excluded.by, at = excluded.at",
                      (user['id'], new, session['user_id'], time.time()))
        else:
            c.execute("DELETE FROM staff WHERE user_id = ?", (user['id'],))
        logged(c, 'rank', user['id'], '%s → %s' % (RANKS.get(old, 'Player'), RANKS.get(new, 'Player')), reason)
    return jsonify({"success": True})

with connect() as c:
    # a picture sent waits for the staff: which, since when, and why one was refused
    if 'avatar_pending' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN avatar_pending TEXT")
        c.execute("ALTER TABLE users ADD COLUMN pending_at REAL")
        c.execute("ALTER TABLE users ADD COLUMN avatar_note TEXT")

def pictures_waiting(c):
    # the pictures this session's staff member may look at, oldest first
    r = my_rank(c)
    if r < MAY['pictures']:
        return []
    return [dict(u) for u in c.execute("SELECT id, username AS name, avatar_pending, pending_at FROM users WHERE avatar_pending IS NOT NULL ORDER BY pending_at")
            if rank_of(c, u['id']) < r]

@app.route("/api/mod/pictures")
def mod_pictures():
    with connect() as c:
        if not may(c, 'pictures'):
            return jsonify({"success": False}), 403
        rows = pictures_waiting(c)
    return jsonify({"success": True, "pictures": [{"id": u['id'], "name": u['name'], "at": u['pending_at'],
                    "url": 'avatar?id=%d&pending=1&v=%s' % (u['id'], u['avatar_pending'])} for u in rows]})

@app.route("/api/mod/picture", methods=['POST'])
def mod_picture():
    # yes: it becomes the player's picture; no: it goes, and they are told why
    uid, what = request.form.get('id', type = int), request.form.get('do')
    reason = request.form.get('reason', '').strip()[:200]
    with room_tx() as c:
        if not may(c, 'pictures', uid) or what not in ('approve', 'reject'):
            return jsonify({"success": False}), 403
        if not c.execute("SELECT avatar_pending FROM users WHERE id = ?", (uid,)).fetchone()[0]:
            return jsonify({"success": False, "error": "Already looked at"})
        if what == 'approve':
            approve_picture(c, uid)
            logged(c, 'picture', uid, 'picture approved', reason)
        else:
            drop_picture(c, uid, 'avatar_pending')
            c.execute("UPDATE users SET avatar_note = ? WHERE id = ?", (reason or 'not accepted', uid))
            logged(c, 'picture', uid, 'picture refused', reason)
    return jsonify({"success": True})

@app.route("/api/mod/tags")
def mod_tags():
    # every tag the staff made, with who holds it
    with connect() as c:
        if not may(c, 'tags'):
            return jsonify({"success": False}), 403
        tags = [dict(t) for t in c.execute("SELECT id, label, color, retired FROM tags ORDER BY retired, at DESC")]
        for t in tags:
            t['holders'] = [dict(h) for h in c.execute('''SELECT u.id, u.username AS name FROM user_tags ut JOIN users u ON u.id = ut.user_id
                WHERE ut.tag_id = ? ORDER BY ut.at''', (t['id'],))]
        r = my_rank(c)
    return jsonify({"success": True, "tags": tags, "colors": TAG_COLORS, "make": r >= MAY['make_tags']})

@app.route("/api/mod/tag", methods=['POST'])
def mod_tag():
    # make a tag, put it away (or back), give it or take it
    form, what = request.form, request.form.get('do')
    with room_tx() as c:
        if what in ('make', 'retire'):
            if not may(c, 'make_tags'):
                return jsonify({"success": False, "error": "Only an Admin can make tags"}), 403
            if what == 'make':
                label = ' '.join(form.get('label', '').split())[:20]
                if not label or form.get('color') not in TAG_COLORS:
                    return jsonify({"success": False, "error": "A tag needs a word and a colour"})
                tid = c.execute("INSERT INTO tags (label, color, by, at) VALUES (?, ?, ?, ?)",
                                (label, form['color'], session['user_id'], time.time())).lastrowid
                logged(c, 'tag', None, 'made the tag ' + label, form.get('reason', '')[:200])
            else:
                t = c.execute("SELECT * FROM tags WHERE id = ?", (form.get('tag', type = int),)).fetchone()
                if not t:
                    return jsonify({"success": False})
                c.execute("UPDATE tags SET retired = ? WHERE id = ?", (int(not t['retired']), t['id']))
                logged(c, 'tag', None, ('put back the tag ' if t['retired'] else 'put away the tag ') + t['label'])
            return jsonify({"success": True})
        t = c.execute("SELECT * FROM tags WHERE id = ? AND retired = 0", (form.get('tag', type = int),)).fetchone()
        user = c.execute("SELECT id FROM users WHERE username = ? COLLATE NOCASE AND COALESCE(guest, 0) = 0",
                         (' '.join(form.get('name', '').split()),)).fetchone()
        if not t or not user:
            return jsonify({"success": False, "error": "No such tag or player account"})
        if not may(c, 'tags', user['id']):
            return jsonify({"success": False, "error": "You can only tag players below you"}), 403
        if what == 'give':
            c.execute("INSERT OR IGNORE INTO user_tags (user_id, tag_id, by, at) VALUES (?, ?, ?, ?)",
                      (user['id'], t['id'], session['user_id'], time.time()))
            logged(c, 'tag', user['id'], 'given the tag ' + t['label'], form.get('reason', '')[:200])
        elif what == 'take':
            c.execute("DELETE FROM user_tags WHERE user_id = ? AND tag_id = ?", (user['id'], t['id']))
            logged(c, 'tag', user['id'], 'lost the tag ' + t['label'], form.get('reason', '')[:200])
        else:
            return jsonify({"success": False})
    return jsonify({"success": True})

@app.route("/api/mod/log")
def mod_log_list():
    # the log, newest first, 50 at a time (before: the oldest id already shown)
    with connect() as c:
        if not may(c, 'log'):
            return jsonify({"success": False}), 403
        before = request.args.get('before', type = int) or 2 ** 62
        rows = [dict(x) for x in c.execute('''SELECT m.id, m.at, m.action, m.details, m.reason, a.username AS by, m.target AS tid, t.username AS target
            FROM mod_log m LEFT JOIN users a ON a.id = m.by LEFT JOIN users t ON t.id = m.target
            WHERE m.id < ? ORDER BY m.id DESC LIMIT 50''', (before,))]
    return jsonify({"success": True, "log": rows})

# ---------- Moderation: the chat ----------
# Minecraft's way (chat reports, 1.19.1): a player reports a message, and the
# staff reads it among the messages around it. Each player may also ignore
# someone (Wynncraft's /ignore): their messages stop, for that player only,
# in every room, until undone from the player list. A word filter masks
# insults and slurs with stars, as Minecraft servers do; what was typed stays
# for the staff, who may hide a message for everyone (kept, and in the log).

REPORTS_MAX = 10          # reports a player may send in 10 minutes
LEET = {'a': 'a4@', 'b': 'b8', 'e': 'e3', 'g': 'g9', 'i': 'i1!|', 'l': 'l1|', 'o': 'o0', 's': 's5$', 't': 't7', 'u': 'uv'}

with connect() as c:
    if 'raw' not in [col[1] for col in c.execute("PRAGMA table_info(room_chat)")]:
        c.execute("ALTER TABLE room_chat ADD COLUMN raw TEXT")     # what was typed, when the filter changed it
        c.execute("ALTER TABLE room_chat ADD COLUMN hidden_by INTEGER")
        c.execute("ALTER TABLE room_chat ADD COLUMN hidden_at REAL")
    c.executescript('''
        CREATE INDEX IF NOT EXISTS room_chat_code ON room_chat (code, id);
        CREATE TABLE IF NOT EXISTS chat_reports (message INTEGER, by INTEGER, at REAL, done INTEGER DEFAULT 0,
            PRIMARY KEY (message, by));
        CREATE TABLE IF NOT EXISTS ignores (user_id INTEGER, target INTEGER, at REAL, PRIMARY KEY (user_id, target));
    ''')

def word_filter():
    # bad_words.txt, one regex: each letter repeated, in digits or signs, split
    # by . - _. A *word* is found by itself, then widened to the word around
    # it (filtered): written in the regex, "any letters, then the word" went
    # back and forth without end on a run of letters (200 "f": 59 ms, under
    # the room's write lock, while every room waited)
    inside, alone = [], []
    with open('bad_words.txt', encoding = 'utf-8') as f:
        for line in f:
            w = line.split('#')[0].strip().lower()
            if w:
                body = '[._-]*'.join(r'\s+' if ch == ' ' else '[%s]+' % re.escape(LEET.get(ch, ch)) for ch in w.strip('*'))
                end = '(?:[._-]?[a-z])*' if w.endswith('*') else r'(?![a-z0-9])'
                if w.startswith('*'):
                    inside.append(body + end)
                else:
                    alone.append(r'(?<![a-z0-9@$])' + body + end)
    return re.compile('(?P<inside>%s)|%s' % ('|'.join(inside) or '(?!)', '|'.join(alone) or '(?!)'), re.IGNORECASE)

BAD_WORDS = word_filter()

def filtered(text):
    # each match in stars, as long as it is; a *word* with the whole word
    # around it (letters, maybe split by . - _); never a number: "455" or
    # "4.55" are coordinates, not "ass"
    hide = [False] * len(text)
    letter = lambda i: 'a' <= text[i].lower() <= 'z'
    for m in BAD_WORDS.finditer(text):
        a, b = m.span()
        if re.fullmatch(r'[\d\s._-]+', m.group()):
            continue
        if m.group('inside'):
            while a and (letter(a - 1) or text[a - 1] in '._-' and a > 1 and letter(a - 2)):
                a -= 1
        hide[a:b] = [True] * (b - a)
    return ''.join('*' if h else ch for ch, h in zip(text, hide))

# Names: the same words, also inside a name written in one piece (BigWord:
# "Big Word"), and none that would pass for the site or its staff
RESERVED = ('moderator', 'wynnguessr', 'wynndle')                  # nowhere in a name
RESERVED_START = ('admin',)                                         # starting no word of it
RESERVED_ALONE = ('mod', 'owner', 'staff', 'helper', 'system', 'server')

def name_rule(name):
    split = re.sub(r'([a-z])([A-Z])', r'\1 \2', name).replace('_', ' ')
    plain = re.sub(r'[^a-z]', '', name.lower())
    # a word starts at a letter after anything else, or at a capital after a
    # small letter (BigWord): "admin" may start none, its letters apart or
    # not (Admin, SuperAdmin, AdMin, Ad_min), but Badminton is fine
    starts = [m.start() for m in re.finditer(r'(?<![A-Za-z])[A-Za-z]|(?<=[a-z])[A-Z]', name)]
    if (filtered(name) != name or filtered(split) != split or any(w in plain for w in RESERVED) or plain in RESERVED_ALONE
            or any(re.sub(r'[^a-z]', '', name[i:].lower()).startswith(w) for i in starts for w in RESERVED_START)):
        return "This name is not allowed: pick another one"

def reports_waiting(c):
    # the reported messages this staff member may act on (written below them), oldest first
    r = my_rank(c)
    if r < MAY['reports']:
        return []
    return [dict(x) for x in c.execute('''SELECT m.id, m.code, m.user_id AS uid, m.at, COALESCE(m.raw, m.text) AS text, MIN(cr.at) AS first
        FROM chat_reports cr JOIN room_chat m ON m.id = cr.message WHERE cr.done = 0 AND m.hidden_by IS NULL
        GROUP BY m.id ORDER BY first''') if rank_of(c, x['uid']) < r]

@app.route("/api/mod/reports")
def mod_reports():
    with connect() as c:
        if not may(c, 'reports'):
            return jsonify({"success": False}), 403
        out = []
        for x in reports_waiting(c):
            # the messages around it, as Minecraft sends them with a report
            around = c.execute("SELECT id, user_id, COALESCE(raw, text) AS text, hidden_by FROM room_chat WHERE code = ? AND id < ? ORDER BY id DESC LIMIT 3",
                               (x['code'], x['id'])).fetchall()[::-1] + c.execute(
                "SELECT id, user_id, COALESCE(raw, text) AS text, hidden_by FROM room_chat WHERE code = ? AND id >= ? ORDER BY id LIMIT 4",
                (x['code'], x['id'])).fetchall()
            users = {u['id']: u for u in c.execute(f"SELECT id, username, COALESCE(guest, 0) AS guest FROM users WHERE id IN ({','.join('?' * len(around))})",
                                                   [m['user_id'] for m in around])}
            by = [b[0] for b in c.execute("SELECT u.username FROM chat_reports cr JOIN users u ON u.id = cr.by WHERE cr.message = ? AND cr.done = 0 ORDER BY cr.at", (x['id'],))]
            author = users.get(x['uid'])
            out.append({"id": x['id'], "room": x['code'], "at": x['at'], "by": by,
                        "author": {"id": x['uid'], "name": author['username'] if author else '?', "guest": bool(author and author['guest'])},
                        "around": [{"id": m['id'], "name": users[m['user_id']]['username'] if m['user_id'] in users else '?',
                                    "text": m['text'], "hidden": m['hidden_by'] is not None} for m in around]})
    return jsonify({"success": True, "reports": out})

@app.route("/api/mod/hide", methods=['POST'])
def mod_hide():
    # hide a message for everyone (from the chat, or a report): kept, and in the log
    mid, reason = request.form.get('id', type = int), request.form.get('reason', '').strip()[:200]
    with room_tx() as c:
        m = c.execute("SELECT * FROM room_chat WHERE id = ?", (mid,)).fetchone()
        if not m or not may(c, 'hide', m['user_id']):
            return jsonify({"success": False}), 403
        if m['hidden_by'] is None:
            c.execute("UPDATE room_chat SET hidden_by = ?, hidden_at = ? WHERE id = ?", (session['user_id'], time.time(), mid))
            c.execute("UPDATE chat_reports SET done = 1 WHERE message = ?", (mid,))
            logged(c, 'hide', m['user_id'], 'message hidden: "%s"' % (m['raw'] or m['text']), reason)
    return jsonify({"success": True})

@app.route("/api/mod/report", methods=['POST'])
def mod_report():
    # nothing wrong with it: the report is closed, the message stays
    mid, reason = request.form.get('id', type = int), request.form.get('reason', '').strip()[:200]
    with room_tx() as c:
        m = c.execute("SELECT * FROM room_chat WHERE id = ?", (mid,)).fetchone()
        if not m or not may(c, 'reports', m['user_id']) or request.form.get('do') != 'dismiss':
            return jsonify({"success": False}), 403
        if c.execute("UPDATE chat_reports SET done = 1 WHERE message = ? AND done = 0", (mid,)).rowcount:
            logged(c, 'report', m['user_id'], 'report dismissed: "%s"' % (m['raw'] or m['text']), reason)
    return jsonify({"success": True})

# ---------- Moderation: sanctions ----------
# Mute (no chat) and ban (no playing), as on Discord and Minecraft servers:
# each has a length and a reason, and goes to the log; a Helper mutes for an
# hour at most. A ban logs the player out of every browser. A guest is only a
# name and could come back as a new one: so while a ban lasts (28 days at
# most there: addresses change hands), the player's last address makes no new
# guest or account. The staff never sees an address. Rename: the old name
# stays in the log.

MUTES = (600, 3600, 86400, 7 * 86400, 28 * 86400)
BANS = (86400, 7 * 86400, 28 * 86400, 0)          # 0: forever
FOREVER = 10 ** 11                                 # a date that never comes
PLACE_BAN = 28 * 86400

with connect() as c:
    if 'muted_until' not in [col[1] for col in c.execute("PRAGMA table_info(users)")]:
        c.execute("ALTER TABLE users ADD COLUMN muted_until REAL")
        c.execute("ALTER TABLE users ADD COLUMN banned_until REAL")
        c.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT")
        c.execute("ALTER TABLE users ADD COLUMN seen_from TEXT")    # the last address, for a ban only
    c.execute("CREATE TABLE IF NOT EXISTS place_bans (place TEXT, until REAL, user_id INTEGER)")

def how_long(seconds):
    # "6 more days": the same for everyone, whatever their time zone (a
    # minute of slack: an hour's mute read a moment later is still an hour)
    for unit, size in (('day', 86400), ('hour', 3600), ('minute', 60)):
        if seconds + 60 >= size or unit == 'minute':
            n = max(1, round(seconds / size))
            return '%d more %s%s' % (n, unit, '' if n == 1 else 's')

def seen(c, uid):
    c.execute("UPDATE users SET seen_from = ? WHERE id = ?", (place(), uid))

def ban_note(c, uid):
    # why this player may not come in, or None
    u = c.execute("SELECT banned_until, ban_reason FROM users WHERE id = ?", (uid,)).fetchone()
    left = (u and u['banned_until'] or 0) - time.time()
    if left > 0:
        return ('This account is banned' + ('' if u['banned_until'] >= FOREVER else ' for ' + how_long(left)) +
                ('. Why: ' + u['ban_reason'] if u['ban_reason'] else ''))

def place_note(c):
    # a banned player's address makes no new name while the ban lasts
    if c.execute("SELECT 1 FROM place_bans WHERE place = ? AND until > ?", (place(), time.time())).fetchone():
        return "This connection is banned for now"

PLAYERS_PAGE = 50
KINDS = {   # the filters of the Players tab
    'all': '1',
    'accounts': 'COALESCE(u.guest, 0) = 0',
    'guests': 'u.guest = 1',
    'staff': '(u.id = %d OR u.id IN (SELECT user_id FROM staff))' % OWNER,
    'muted': 'u.muted_until > :now',
    'banned': 'u.banned_until > :now',
    'reported': 'u.id IN (SELECT m.user_id FROM chat_reports cr JOIN room_chat m ON m.id = cr.message)',
}

@app.route("/api/mod/players")
def mod_players():
    # every player, newest first, 50 at a time; filtered by a kind and by
    # anything in the name (an exact name first)
    q, kind = ' '.join(request.args.get('q', '').split()), request.args.get('kind', 'all')
    start = request.args.get('start', 0, type = int)
    with connect() as c:
        if not may(c, 'players') or kind not in KINDS:
            return jsonify({"success": False}), 403
        now = time.time()
        rows = c.execute(f'''SELECT u.id, u.username AS name, COALESCE(u.guest, 0) AS guest, u.avatar, u.mc_uuid,
                u.muted_until > :now AS muted, u.banned_until > :now AS banned,
                (SELECT COUNT(DISTINCT cr.message) FROM chat_reports cr JOIN room_chat m ON m.id = cr.message WHERE m.user_id = u.id) AS reported
            FROM users u WHERE {KINDS[kind]} AND u.username LIKE :q ESCAPE '\\'
            ORDER BY u.username = :exact COLLATE NOCASE DESC, u.id DESC LIMIT :n OFFSET :start''',
            {'now': now, 'q': '%' + re.sub(r'([\\%_])', r'\\\1', q) + '%', 'exact': q, 'n': PLAYERS_PAGE + 1, 'start': start}).fetchall()
        tags = tag_of(c, [u['id'] for u in rows])
        out = [{'id': u['id'], 'name': u['name'], 'guest': bool(u['guest']), 'muted': bool(u['muted']), 'banned': bool(u['banned']),
                'reported': u['reported'], 'tag': tags.get(u['id']), 'picture': avatar_url(u)} for u in rows[:PLAYERS_PAGE]]
    return jsonify({"success": True, "players": out, "more": len(rows) > PLAYERS_PAGE})

@app.route("/api/mod/player")
def mod_player():
    # one player: how things stand, what this staff member may do, what happened
    uid = request.args.get('id', type = int)
    with connect() as c:
        if not may(c, 'players'):
            return jsonify({"success": False}), 403
        u = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not u:
            return jsonify({"success": False})
        now = time.time()
        log = [dict(x) for x in c.execute('''SELECT m.at, m.details, m.reason, a.username AS by FROM mod_log m LEFT JOIN users a ON a.id = m.by
            WHERE m.target = ? ORDER BY m.id DESC LIMIT 30''', (uid,))]
        said = [dict(x) for x in c.execute('''SELECT code AS room, at, COALESCE(raw, text) AS text, hidden_by IS NOT NULL AS hidden
            FROM room_chat WHERE user_id = ? ORDER BY id DESC LIMIT 10''', (uid,))]
        reported = c.execute("SELECT COUNT(DISTINCT cr.message) FROM chat_reports cr JOIN room_chat m ON m.id = cr.message WHERE m.user_id = ?", (uid,)).fetchone()[0]
        out = {"success": True, "id": uid, "name": u['username'], "guest": bool(u['guest']), "tag": tag_of(c, [uid]).get(uid),
               "picture": None if u['guest'] else avatar_url(u), "reported": reported, "log": log, "said": said,
               "muted": how_long(u['muted_until'] - now) if (u['muted_until'] or 0) > now else None,
               "banned": ('forever' if u['banned_until'] >= FOREVER else 'for ' + how_long(u['banned_until'] - now)) if (u['banned_until'] or 0) > now else None,
               "may": {k: may(c, k, uid) for k in ('mute', 'long_mute', 'ban', 'rename')}}
        out['mutes'] = [m for m in MUTES if out['may']['long_mute'] or m <= HELPER_MUTE]
        r = my_rank(c)
        if r >= MAY['staff'] and not u['guest'] and rank_of(c, uid) < r:
            out['ranks'] = {k: v for k, v in RANKS.items() if k < r}
        out['rank'] = rank_of(c, uid)
        out['bans'] = list(BANS)
    return jsonify(out)

@app.route("/api/mod/sanction", methods=['POST'])
def mod_sanction():
    f = request.form
    uid, what, reason = f.get('id', type = int), f.get('do'), f.get('reason', '').strip()[:200]
    need = {'mute': 'mute', 'unmute': 'mute', 'ban': 'ban', 'unban': 'ban', 'rename': 'rename'}.get(what)
    with room_tx() as c:
        u = c.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
        if not u or not need or not may(c, need, uid):
            return jsonify({"success": False, "error": "You can only do this to players below you"}), 403
        now, length = time.time(), f.get('length', type = int)
        if what == 'mute':
            if length not in MUTES or (length > HELPER_MUTE and not may(c, 'long_mute', uid)):
                return jsonify({"success": False, "error": "A Helper mutes for an hour at most"})
            c.execute("UPDATE users SET muted_until = ? WHERE id = ?", (now + length, uid))
            logged(c, 'mute', uid, 'muted for ' + how_long(length).replace(' more', ''), reason)
        elif what == 'unmute':
            c.execute("UPDATE users SET muted_until = NULL WHERE id = ?", (uid,))
            logged(c, 'mute', uid, 'unmuted', reason)
        elif what == 'ban':
            if length not in BANS:
                return jsonify({"success": False})
            until = now + length if length else FOREVER
            c.execute("UPDATE users SET banned_until = ?, ban_reason = ? WHERE id = ?", (until, reason or None, uid))
            if u['seen_from']:
                c.execute("INSERT INTO place_bans (place, until, user_id) VALUES (?, ?, ?)", (u['seen_from'], min(until, now + PLACE_BAN), uid))
            logged(c, 'ban', uid, 'banned ' + ('for ' + how_long(length).replace(' more', '') if length else 'forever'), reason)
        elif what == 'unban':
            c.execute("UPDATE users SET banned_until = NULL, ban_reason = NULL WHERE id = ?", (uid,))
            c.execute("UPDATE place_bans SET until = ? WHERE user_id = ? AND until > ?", (now, uid, now))
            logged(c, 'ban', uid, 'unbanned', reason)
        else:
            name = clean_name(f.get('name', ''))
            problem = name_problem(c, name, uid)
            if problem:
                return jsonify({"success": False, "error": problem})
            c.execute("UPDATE users SET username = ? WHERE id = ?", (name, uid))
            logged(c, 'rename', uid, 'renamed from ' + u['username'], reason)
    return jsonify({"success": True})

# ---------- Contact ----------
# One page for every way to reach the team (Yasuro, 2026-10-19), linked from
# the footer: the Discord, the email, and a form whose messages land in
# Moderation, where they are sorted and answered. The topic shapes the form
# (a player report names the player, a bug says where it happened, a ban
# says which account) and the sender says where to answer: here (their
# messages on the page, and a notice on every page until they read the
# answer), by email or on Discord (the staff writes from there), or not at
# all. Moderators and up read them: an email address is personal. A
# screenshot is made again here, like a profile picture, and only the team
# and its sender see it.

CONTACT_EMAIL = 'wynndle.contact@gmail.com'
TOPICS = {   # key: (label, icon)
    'bug': ('A bug', 'bug_report'),
    'location': ('A location', 'place'),
    'player': ('A player', 'flag'),
    'account': ('My account', 'manage_accounts'),
    'sanction': ('A ban or mute', 'gavel'),
    'idea': ('An idea', 'lightbulb'),
    'partner': ('Partnership', 'handshake'),
    'other': ('Something else', 'chat'),
}
REPLY_BY = ('here', 'email', 'discord', 'none')
CONTACT_TEXT = 2000       # characters in a message or an answer
CONTACT_PAGE = 50
CONTACT_FILES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'contact_files')   # screenshots, not in git
CONTACT_STATES = {'new': "m.state = 'new'", 'open': "m.state = 'open'", 'done': "m.state = 'done'", 'all': '1'}

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS contact (id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, topic TEXT,
            user_id INTEGER, about TEXT, text TEXT, reply TEXT, email TEXT, discord TEXT, context TEXT, file TEXT,
            state TEXT DEFAULT 'new', last REAL, seen REAL);
        CREATE INDEX IF NOT EXISTS contact_state ON contact (state, last);
        CREATE INDEX IF NOT EXISTS contact_user ON contact (user_id);
        CREATE TABLE IF NOT EXISTS contact_replies (id INTEGER PRIMARY KEY AUTOINCREMENT, message INTEGER,
            user_id INTEGER, team INTEGER, text TEXT, at REAL);
        CREATE INDEX IF NOT EXISTS contact_replies_message ON contact_replies (message);
    ''')
# state: 'new' (nobody in the team opened it, or the sender wrote again),
# 'open' (read, or answered), 'done'; last: the last word, either side;
# seen: when the sender last read the answers

def contact_waiting(c):
    return c.execute("SELECT COUNT(*) FROM contact WHERE state = 'new'").fetchone()[0]

def contact_text(text):
    # what was typed, its lines kept, never more than one empty line in a row
    lines = (text or '').replace('\r', '').split('\n')
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(l.rstrip() for l in lines).strip())[:CONTACT_TEXT]

def contact_shot(upload):
    # a screenshot: made again here as a webp (the file sent is never
    # served), 2000 px at most; None if it is no picture
    from PIL import Image, ImageOps
    try:
        img = Image.open(upload.stream)
        if img.format not in ('PNG', 'JPEG', 'WEBP', 'GIF') or img.width * img.height > 40_000_000:
            raise ValueError(img.format)
        img = ImageOps.exif_transpose(img).convert('RGB')
    except Exception:
        return None
    img.thumbnail((2000, 2000))
    name = secrets.token_hex(10) + '.webp'
    os.makedirs(CONTACT_FILES, exist_ok = True)
    img.save(os.path.join(CONTACT_FILES, name), 'WEBP', quality = 82)
    return name

def contact_replies(c, ids):
    # the answers under each message, oldest first: {message id: [rows]}
    out = {i: [] for i in ids}
    if ids:
        for r in c.execute(f'''SELECT r.*, u.username FROM contact_replies r LEFT JOIN users u ON u.id = r.user_id
                WHERE r.message IN ({','.join('?' * len(ids))}) ORDER BY r.id''', list(ids)):
            out[r['message']].append(r)
    return out

def contact_status(m, replies):
    # what the sender reads: sent, read, answered, closed
    if m['state'] == 'done':
        return 'closed'
    if replies and replies[-1]['team']:
        return 'answered'
    return 'read' if m['state'] == 'open' else 'sent'

def contact_mine(m, replies):
    # a message as its sender sees it: the team answers as the team
    return {"id": m['id'], "at": m['at'], "topic": m['topic'], "label": TOPICS[m['topic']][0], "icon": TOPICS[m['topic']][1],
            "about": m['about'], "text": m['text'], "reply": m['reply'], "status": contact_status(m, replies),
            "file": 'contact/file/%d' % m['id'] if m['file'] else None,
            "new": any(r['team'] and r['at'] > (m['seen'] or 0) for r in replies),
            "replies": [{"text": r['text'], "at": r['at'], "team": bool(r['team'])} for r in replies]}

@app.context_processor
def contact_notice():
    # the team answered and the sender has not read it yet: a notice on
    # every page (it slides in once, then stays put until read), but not in
    # a room: a game is not interrupted, and the room has toasts of its own
    def answered():
        uid = session.get('user_id')
        if not uid or request.endpoint in ('contact', 'room'):
            return None
        with connect() as c:
            last = c.execute('''SELECT MAX(r.id) FROM contact m JOIN contact_replies r ON r.message = m.id
                WHERE m.user_id = ? AND r.team = 1 AND r.at > COALESCE(m.seen, 0)''', (uid,)).fetchone()[0]
        if not last:
            return None
        new = session.get('told') != last
        if new:
            session['told'] = last
        return {'new': new}
    return {'contact_answer': answered}

@app.route("/contact")
def contact():
    # ?topic= picks the topic; ?name= (a player), ?x=&z= (a location) fill it in
    a, uid = request.args, session.get('user_id')
    with connect() as c:
        me = uid and c.execute("SELECT username, COALESCE(guest, 0) AS guest, muted_until FROM users WHERE id = ?", (uid,)).fetchone()
    muted = me and (me['muted_until'] or 0) > time.time() and how_long(me['muted_until'] - time.time())
    about = ' '.join(a.get('name', '').split())[:100]
    if re.fullmatch(r'-?\d{1,6}', a.get('x', '')) and re.fullmatch(r'-?\d{1,6}', a.get('z', '')):
        about = a['x'] + ', ' + a['z']
    return render_template('contact.html', topics = TOPICS, topic = a.get('topic') if a.get('topic') in TOPICS else None,
                           about = about, me = me, muted = muted, email = CONTACT_EMAIL, discord = DISCORD,
                           server = discord_counts(), shown = time.time())

@app.route("/api/contact", methods=['POST'])
def contact_send():
    f, uid, now = request.form, session.get('user_id'), time.time()
    def refuse(error, field = None):
        return jsonify({"success": False, "error": error, "field": field})
    # robots: a field nobody sees filled in, or a form sent within 3 s of
    # its page. They are told it worked, and nothing is kept
    try:
        quick = now - float(f.get('t', 0)) < 3
    except ValueError:
        quick = False
    if f.get('website') or quick:
        return jsonify({"success": True})
    topic, reply = f.get('topic'), f.get('reply')
    text, about = contact_text(f.get('text')), ' '.join(f.get('about', '').split())[:100]
    email, discord = f.get('email', '').strip()[:120], f.get('discord', '').strip()[:40]
    if topic not in TOPICS:
        return refuse("Pick what it is about", 'topic')
    if topic == 'player' and not about:
        return refuse("Who is it?", 'about')
    if topic in ('account', 'sanction') and not uid and not about:
        return refuse("Which account?", 'about')
    if len(text) < 10:
        return refuse("Tell us a little more", 'text')
    if reply not in REPLY_BY or reply == 'here' and not uid:
        return refuse("Where should we answer?", 'reply')
    if topic == 'partner' and reply != 'email':
        return refuse("Leave us an email to answer", 'email')
    if reply == 'email' and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        return refuse("This email does not look right", 'email')
    if reply == 'discord' and not re.fullmatch(r'[\w.#]{2,40}', discord):
        return refuse("This Discord name does not look right", 'discord')
    if (request.content_length or 0) > PICTURE_MAX + 100_000:
        return refuse("This picture is too big: 8 MB at most", 'file')
    if too_often('contact'):
        return refuse("Too many messages from here: wait a few minutes")
    upload, shot = request.files.get('file'), None
    if upload and upload.filename:
        shot = contact_shot(upload)
        if not shot:
            return refuse("This file is not a picture", 'file')
    # a bug or a location: where it happened, on what (as the sender saw it written)
    context = json.dumps({'page': f.get('page', '')[:200], 'screen': f.get('screen', '')[:20],
                          'browser': f.get('browser', '')[:60], 'version': VERSION}) if topic in ('bug', 'location') else None
    with connect() as c:
        mid = c.execute('''INSERT INTO contact (at, topic, user_id, about, text, reply, email, discord, context, file, state, last, seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)''',
            (now, topic, uid, about or None, text, reply, email if reply == 'email' else None,
             discord if reply == 'discord' else None, context, shot, now, now)).lastrowid
        done(c, 'contact')
    return jsonify({"success": True, "id": mid})

@app.route("/api/contact/mine")
def contact_list_mine():
    # the sender's messages and the team's answers; reading them ends the notice
    uid = session.get('user_id')
    if not uid:
        return jsonify({"success": True, "messages": []})
    with connect() as c:
        rows = c.execute("SELECT * FROM contact WHERE user_id = ? ORDER BY id DESC LIMIT 30", (uid,)).fetchall()
        replies = contact_replies(c, [m['id'] for m in rows])
        out = [contact_mine(m, replies[m['id']]) for m in rows]
        c.execute("UPDATE contact SET seen = ? WHERE user_id = ?", (time.time(), uid))
    return jsonify({"success": True, "messages": out})

@app.route("/api/contact/<int:mid>/reply", methods=['POST'])
def contact_write_again(mid):
    # the sender writes again under a message: back among the new ones
    uid, text = session.get('user_id'), contact_text(request.form.get('text'))
    if not text:
        return jsonify({"success": False, "error": "Write something first"})
    if too_often('contact'):
        return jsonify({"success": False, "error": "Too many messages from here: wait a few minutes"})
    with connect() as c:
        m = c.execute("SELECT user_id FROM contact WHERE id = ?", (mid,)).fetchone()
        if not uid or not m or m['user_id'] != uid:
            return jsonify({"success": False}), 403
        now = time.time()
        c.execute("INSERT INTO contact_replies (message, user_id, team, text, at) VALUES (?, ?, 0, ?, ?)", (mid, uid, text, now))
        c.execute("UPDATE contact SET state = 'new', last = ?, seen = ? WHERE id = ?", (now, now, mid))
        done(c, 'contact')
    return jsonify({"success": True})

@app.route("/api/contact/player")
def contact_player():
    # the player a report is about, while the name is typed: their head, or nobody
    name = ' '.join(request.args.get('name', '').split())[:40]
    with connect() as c:
        u = c.execute("SELECT id, username, avatar, mc_uuid FROM users WHERE username = ? COLLATE NOCASE ORDER BY COALESCE(guest, 0), id LIMIT 1",
                      (name,)).fetchone()
    return jsonify({"found": bool(u), "name": u['username'] if u else None, "picture": avatar_url(u) if u else None})

@app.route("/contact/file/<int:mid>")
def contact_file(mid):
    # a screenshot: for the team, and for whoever sent it
    with connect() as c:
        m = c.execute("SELECT user_id, file FROM contact WHERE id = ?", (mid,)).fetchone()
        if not m or not m['file'] or not (may(c, 'contact') or m['user_id'] and m['user_id'] == session.get('user_id')):
            return '', 404
    response = send_from_directory(CONTACT_FILES, m['file'], max_age = 0)
    response.cache_control.public, response.cache_control.private = False, True
    return response

@app.route("/api/mod/contact")
def mod_contact():
    # the messages, 50 at a time: by state (new first), by topic, by anything
    # in them or in the sender's name; by the last word, newest or oldest first
    a = request.args
    state, topic, q = a.get('state', 'new'), a.get('topic', ''), ' '.join(a.get('q', '').split())
    with connect() as c:
        if not may(c, 'contact') or state not in CONTACT_STATES or topic and topic not in TOPICS:
            return jsonify({"success": False}), 403
        where, args = [CONTACT_STATES[state]], {'n': CONTACT_PAGE + 1, 'start': a.get('start', 0, type = int)}
        if topic:
            where.append('m.topic = :topic')
            args['topic'] = topic
        if q:
            args['q'] = '%' + re.sub(r'([\\%_])', r'\\\1', q) + '%'
            where.append('''(m.text LIKE :q ESCAPE '\\' OR m.about LIKE :q ESCAPE '\\' OR m.email LIKE :q ESCAPE '\\'
                OR m.discord LIKE :q ESCAPE '\\' OR u.username LIKE :q ESCAPE '\\'
                OR m.id IN (SELECT message FROM contact_replies WHERE text LIKE :q ESCAPE '\\'))''')
        rows = c.execute(f'''SELECT m.*, u.username, COALESCE(u.guest, 0) AS guest, u.avatar, u.mc_uuid
            FROM contact m LEFT JOIN users u ON u.id = m.user_id WHERE {' AND '.join(where)}
            ORDER BY m.last {'ASC' if a.get('sort') == 'old' else 'DESC'} LIMIT :n OFFSET :start''', args).fetchall()
        shown = rows[:CONTACT_PAGE]
        replies = contact_replies(c, [m['id'] for m in shown])
        tags = tag_of(c, [m['user_id'] for m in shown if m['user_id']])
        out = []
        for m in shown:
            # the account a report or a ban is about, if the name is one: its card is a click away
            named = m['about'] and m['topic'] in ('player', 'account', 'sanction') and c.execute(
                "SELECT id FROM users WHERE username = ? COLLATE NOCASE ORDER BY COALESCE(guest, 0), id LIMIT 1", (m['about'],)).fetchone()
            out.append({"id": m['id'], "at": m['at'], "last": m['last'], "topic": m['topic'], "state": m['state'],
                        "text": m['text'], "about": m['about'], "about_id": named[0] if named else None,
                        "reply": m['reply'], "email": m['email'], "discord": m['discord'],
                        "context": json.loads(m['context']) if m['context'] else None,
                        "file": 'contact/file/%d' % m['id'] if m['file'] else None,
                        "from": {"id": m['user_id'], "name": m['username'], "guest": bool(m['guest']), "tag": tags.get(m['user_id']),
                                 "picture": avatar_url({'id': m['user_id'], 'avatar': m['avatar'], 'mc_uuid': m['mc_uuid']})}
                                if m['user_id'] and m['username'] else None,
                        "replies": [{"text": r['text'], "at": r['at'], "team": bool(r['team']), "by": r['username']} for r in replies[m['id']]]})
        counts = dict(c.execute("SELECT state, COUNT(*) FROM contact GROUP BY state").fetchall())
        topics = dict(c.execute(f"SELECT m.topic, COUNT(*) FROM contact m WHERE {CONTACT_STATES[state]} GROUP BY m.topic").fetchall())
    return jsonify({"success": True, "messages": out, "more": len(rows) > CONTACT_PAGE, "counts": counts, "topics": topics,
                    "labels": {k: v[0] for k, v in TOPICS.items()}, "icons": {k: v[1] for k, v in TOPICS.items()}})

@app.route("/api/mod/contact", methods=['POST'])
def mod_contact_do():
    # open (the sender reads "Read"), answer (and close), close, open again, delete
    f, now = request.form, time.time()
    mid, what = f.get('id', type = int), f.get('do')
    with connect() as c:
        m = c.execute("SELECT * FROM contact WHERE id = ?", (mid,)).fetchone()
        if not m or not may(c, 'contact') or what not in ('open', 'answer', 'done', 'reopen', 'delete'):
            return jsonify({"success": False}), 403
        if what == 'open':
            c.execute("UPDATE contact SET state = 'open' WHERE id = ? AND state = 'new'", (mid,))
        elif what == 'answer':
            text = contact_text(f.get('text'))
            if not text:
                return jsonify({"success": False, "error": "Write something first"})
            c.execute("INSERT INTO contact_replies (message, user_id, team, text, at) VALUES (?, ?, 1, ?, ?)", (mid, session['user_id'], text, now))
            c.execute("UPDATE contact SET state = ?, last = ? WHERE id = ?", ('done' if f.get('close') else 'open', now, mid))
        elif what in ('done', 'reopen'):
            c.execute("UPDATE contact SET state = ? WHERE id = ?", ('done' if what == 'done' else 'open', mid))
        else:
            c.execute("DELETE FROM contact_replies WHERE message = ?", (mid,))
            c.execute("DELETE FROM contact WHERE id = ?", (mid,))
            if m['file']:
                try:
                    os.remove(os.path.join(CONTACT_FILES, m['file']))
                except OSError:
                    pass
            text = m['text'] if len(m['text']) <= 80 else m['text'][:79] + '…'
            logged(c, 'contact', m['user_id'], 'message deleted (%s): "%s"' % (TOPICS[m['topic']][0], text))
    return jsonify({"success": True})

fcntl.flock(STARTING, fcntl.LOCK_UN)   # this process is ready: the next may start (see the top)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
