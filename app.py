from flask import Flask, render_template, url_for, request, redirect, session, send_from_directory, jsonify
from flask_session import Session
from flask_cors import CORS
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
from datetime import date
import urllib.request
from urllib.parse import quote, urlencode
from flask_bcrypt import Bcrypt
from config import Config

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app)
app.config.from_object(Config)
# other sites share this domain behind Tailscale Funnel
app.config['SESSION_COOKIE_NAME'] = 'wynnguessr_session'

# only these locations are played; 'new' ones wait for the review
PLAYABLE = "('old', 'kept')"

def connect():
    # one connection per request: a single shared one is not safe across threads
    c = sqlite3.connect('database.db', timeout=10)
    c.row_factory = sqlite3.Row
    return c

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

def next_page():
    # where to go after logging in: only a page of this site, e.g. "room?code=ABC234"
    page = request.args.get('next', '')
    return page if re.fullmatch(r'[a-z]+(\?(code|play)=[A-Za-z0-9_-]+)?', page) else './'

@app.route("/api/locations", methods = ['GET'])
def get_locations():
    #if there are no provinces in session, return apology
    if 'provinces' not in session:
        return jsonify({"success": False})
    provinces = session['provinces']
    placeholders = ', '.join('?' for _ in provinces)
    query = f"SELECT * FROM locations WHERE province IN ({placeholders}) AND review IN {PLAYABLE}"
    with connect() as c:
        locations = c.execute(query, provinces).fetchall()
    locations_list = [{"id": location[0], "X" : location[1], "Z" : location[2], "url" : location[3]} for location in locations]
    return jsonify(locations_list)


@app.route("/api/score", methods=['POST'])
def post_score():
    if request.method == 'POST':
        if not session.get('loggedin'):
            return jsonify({"success": False})
        score = request.form['score']
        look = request.form['look']
        if look == 'True':
            look = 'Yes'
        else:
            look = 'No'
        provinces = request.form['provinces']
        totalTime = request.form['totalTime']
        mode = request.form.get('mode', 'classic')
        if mode == 'survival':
            # the score is the number of locations found in a row
            rounds = None
            if not score.isnumeric() or int(score) > 1000:
                return jsonify({"success": False})
        else:
            mode = 'classic'
            if request.form['rounds'] not in ['3', '5', '10', '25']:
                return render_template('apology.html', message = "Invalid number of rounds")
            rounds = request.form['rounds']
            if(int(score) > int(rounds) * 5000):
                return jsonify({"success": False})
            if(int(rounds) * 5000 == int(score) and float(totalTime) < .5):
                return jsonify({"success": False})
        with connect() as c:
            c.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (session['user_id'], score, date.today(), look, provinces, rounds, totalTime, mode))
        return jsonify({"success": True})
    return jsonify({"success": False})

def board(c, form, user_id = None):
    # the games played with exactly the settings of the filters, best first
    mode = 'survival' if form.get('mode') == 'survival' else 'classic'
    query = '''SELECT u.username AS name, u.mc_name AS mc, s.score, s.time, s.date FROM scores s JOIN users u ON u.id = s.user_id
        WHERE s.provinces = ? AND s.nolook = ? AND COALESCE(s.mode, 'classic') = ?'''
    params = [form.get('provinces', ''), form.get('nolook', 'No'), mode]
    if mode == 'classic':
        query += " AND s.rounds = ?"
        params.append(form.get('rounds', ''))
    if user_id:
        query += " AND s.user_id = ?"
        params.append(user_id)
    return [dict(row) for row in c.execute(query + " ORDER BY s.score DESC, s.time ASC", params)]

@app.route("/api/updaterank", methods=['POST'])
def update_rank():
    # each player's best game
    with connect() as c:
        rows, seen = [], set()
        for row in board(c, request.form):
            if row['name'] not in seen:
                seen.add(row['name'])
                rows.append(row)
        me = session.get('user_id') and c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    return jsonify({"rows": rows[:50], "me": me[0] if me else None})

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/mode")
def play():
    return render_template('mode.html')

@app.route("/leaderboard")
def leaderboard():
    return render_template('leaderboard.html')

@app.route("/game", methods=['POST', 'GET'])
def game():
    # the mode page sends its settings in the address, so "Play Again" is a plain reload
    form = request.values
    session['provinces'] = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']
    if 'rounds' in form:
        if form.get('mode') in ('duel', 'royale'):
            return render_template('apology.html', message = "This mode is played with friends: create a room")
        mode = 'survival' if form.get('mode') == 'survival' else 'classic'
        #if there are no provinces selected, return apology
        if form.getlist('province') == []:
            return render_template('apology.html', message = "Please select at least one province")
        provinces = form.getlist('province')
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
        #store provinces in session
        session['provinces'] = provinces
        print(provinces, time_limit, look, rounds)

        return render_template('game.html', provinces = provinces, time_limit = time_limit, look = look, rounds = rounds, mode = mode)
    return render_template('game.html', provinces = "['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']", time_limit = -1, look = False, rounds = 5, mode = 'classic')

@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.method == 'POST':#user login request
        username = request.form['username']
        password = request.form['password']

        if username == "" or password == "":
            return render_template('apology.html', message = "Please fill in all fields")
        with connect() as c:
            user = c.execute("SELECT * FROM users WHERE username = ? AND COALESCE(guest, 0) = 0", (username,)).fetchone()
        if user and user[2] and bcrypt.check_password_hash(user[2], password):
            session.permanent = True
            session['guest'] = False
            session['loggedin'] = True
            session['user_id'] = user[0]
            return redirect(next_page())
        else:
            return render_template('apology.html', message = "Invalid username or password")
    else:
        return render_template('login.html')

@app.route("/register", methods=['POST', 'GET'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        confirmation = request.form['confirmation']
        with connect() as c:
            if len(username) > 20:
                return render_template('apology.html', message = "Username must be 20 characters or less")
            if len(password) > 64:
                return render_template('apology.html', message = "Password must be 64 characters or less")
            if password != confirmation:
                return render_template('apology.html', message = "Passwords do not match")
            elif c.execute("SELECT * FROM users WHERE (username = ? AND COALESCE(guest, 0) = 0) OR mc_name = ? COLLATE NOCASE", (username, username)).fetchall():
                return render_template('apology.html', message = "Username is already taken")
            elif username == "" or password == "" or confirmation == "":
                return render_template('apology.html', message = "Please fill in all fields")
            else:
                hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                user = c.execute("SELECT * FROM users WHERE username = ? AND COALESCE(guest, 0) = 0", (username,)).fetchone()
                session.permanent = True
                session['guest'] = False
                session['loggedin'] = True
                session['user_id'] = user[0]
                return redirect(next_page())
    else:
        return render_template('register.html')

@app.route("/logout")
def logout():
    session['loggedin'] = False
    session['guest'] = False
    session['user_id'] = None
    return redirect('./')

@app.route("/guest", methods=['POST', 'GET'])
def guest():
    # multiplayer without an account: just a nickname. A guest is a user row
    # marked guest: no password, and never on the leaderboard
    if request.method == 'GET':
        return render_template('guest.html')
    name = ' '.join(request.form.get('username', '').split())
    if not name or len(name) > 20:
        return render_template('apology.html', message = "Pick a nickname of 1 to 20 characters")
    with connect() as c:
        if c.execute("SELECT 1 FROM users WHERE username = ? COLLATE NOCASE AND COALESCE(guest, 0) = 0", (name,)).fetchone():
            return render_template('apology.html', message = "This name belongs to a registered player: pick another one, or log in")
        uid = c.execute("INSERT INTO users (username, password, guest) VALUES (?, '', 1)", (name,)).lastrowid
    session.permanent = True
    session['loggedin'] = False
    session['guest'] = True
    session['user_id'] = uid
    return redirect(next_page())

@app.route("/profile")
def profile():
    if not session.get('loggedin'):
        return redirect('login?next=profile')
    with connect() as c:
        profile = c.execute("SELECT username, mc_name FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        games = history(c, session['user_id'])
    multi = [g for g in games if g['multi']]
    return render_template('profile.html', username = profile[0], mc_name = profile[1], games = games[:30],
                           played = len(multi), wins = sum(g['win'] for g in multi))

def history(c, uid):
    # the player's games, newest first: finished rooms with at least two
    # players (with their place), and solo games (room games also sit in
    # scores, marked with their room: they are not counted twice)
    games = []
    for r in c.execute('''SELECT r.* FROM rooms r JOIN room_players p ON p.code = r.code
            WHERE p.user_id = ? AND r.state = 'finished' ''', (uid,)).fetchall():
        totals = dict(c.execute("SELECT user_id, SUM(score) FROM room_guesses WHERE code = ? GROUP BY user_id", (r['code'],)).fetchall())
        when = c.execute("SELECT MAX(at) FROM room_guesses WHERE code = ?", (r['code'],)).fetchone()[0]
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
        games.append({'multi': True, 'mode': r['mode'], 'rank': rank, 'of': len(players), 'win': rank == 1,
                      'score': totals.get(uid, 0), 'rounds': r['round'], 'when': when or 0,
                      'left': st.get(uid, {}).get('left'), 'out': st.get(uid, {}).get('out')})
    for g in c.execute('''SELECT score, rounds, time, date, COALESCE(mode, 'classic') AS mode FROM scores
            WHERE user_id = ? AND room IS NULL''', (uid,)).fetchall():
        try:
            when = time.mktime(time.strptime(g['date'], '%Y-%m-%d'))
        except (TypeError, ValueError):
            when = 0
        games.append({'multi': False, 'mode': g['mode'], 'score': g['score'], 'rounds': g['rounds'],
                      'time': g['time'], 'when': when})
    for g in games:
        g['day'] = time.strftime('%b %d, %Y', time.localtime(g['when'])) if g['when'] else ''
    return sorted(games, key = lambda g: g['when'], reverse = True)

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

def wynn_fail(message):
    # these routes sit two folders deep: show the error on the normal page
    return redirect('../../apology?' + urlencode({'message': message}))

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
        else:
            uid = c.execute("INSERT INTO users (username, password, mc_uuid, mc_name) VALUES (?, '', ?, ?)", (name, uuid, name)).lastrowid
    session.permanent = True
    session['guest'] = False
    session['loggedin'] = True
    session['user_id'] = uid
    return redirect('../../' + session.pop('wynn_next', './'))

@app.route("/apology")
def apology():
    message = request.args.get('message', 'Something went wrong')
    return render_template('apology.html', message = message)

# ---------- Multiplayer rooms ----------
# A room is a fixed list of locations, played live by everyone who joins before
# the end: same round at the same time, the round closes once all have guessed
# (or the clock runs out) and the next one starts by itself after the reveal.
# Three modes: classic (most points after N rounds), duel (health points, the
# gap to the round's best guess hurts, more and more each round) and royale
# (lives: the worst guess of a round loses one, a bullseye wins one back).
# Anyone opening a finished classic room plays the same locations alone and
# lands in the same ranking. Rooms only move forward when someone asks: every
# room request first runs tick().

PROVINCES = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']
ROUNDS = ['3', '5', '10', '25']
MODES = ['classic', 'duel', 'royale']
LAST_CALL = 15   # once someone guessed, the others have this long
REVEAL = 10      # the answer stays on screen this long before the next round
AWAY = 10        # a page that stopped polling this long is not waited for
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
        return None, "Survival is played solo" if mode == 'survival' else "Unknown game mode"
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
            'time_limit': time_limit, 'look': int(form.get('look') == 'on')}, None

def pick_locations(c, s):
    ids = [r[0] for r in c.execute(
        f"SELECT location_id FROM locations WHERE province IN ({', '.join('?' * len(s['provinces']))}) AND review IN {PLAYABLE} ORDER BY RANDOM() LIMIT ?",
        (*s['provinces'], s['rounds']))]
    return json.dumps(ids) if len(ids) == s['rounds'] else None

def new_room(c, host, s):
    locations = pick_locations(c, s)
    if not locations:
        return None
    code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    while find_room(c, code):
        code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    c.execute('''INSERT INTO rooms (code, host_id, mode, provinces, rounds, time_limit, look, locations, state, round, round_start)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 0, 0)''',
        (code, host, s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations))
    c.execute("INSERT INTO room_players (code, user_id, live, last_seen) VALUES (?, ?, 1, ?)", (code, host, time.time()))
    return code

def guess_score(x, z, loc):
    # same formula as game.js
    d = ((loc['x_position'] - x) ** 2 + (loc['z_position'] - z) ** 2) ** .5
    return max(0, round(5200 / (1 + .002 * math.e ** (.0042 * d + 3)) + .822))

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
    if r['state'] != 'playing':
        host = c.execute("SELECT last_seen FROM room_players WHERE code = ? AND user_id = ?", (r['code'], r['host_id'])).fetchone()
        if host and host[0] > now - HOST_AWAY:
            return r
        heir = c.execute("SELECT user_id FROM room_players WHERE code = ? AND live = 1 AND last_seen > ? ORDER BY rowid LIMIT 1",
                         (r['code'], now - AWAY)).fetchone()
        if heir:
            c.execute("UPDATE rooms SET host_id = ? WHERE code = ?", (heir[0], r['code']))
        return find_room(c, r['code'])
    if r['round_end'] is None:
        deadline, _ = round_deadline(c, r)
        here = {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND last_seen > ?", (r['code'], now - AWAY))}
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

@app.route("/room/create", methods=['POST'])
def room_create():
    if not session.get('user_id'):
        return redirect('../guest?next=' + quote('mode?play=friends'))
    s, error = room_settings(request.form)
    if error:
        return render_template('apology.html', message = error)
    with room_tx() as c:
        code = new_room(c, session['user_id'], s)
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
        # names tell players apart on screen: two of the same in a room would mix up
        clash = c.execute('''SELECT 1 FROM room_players p JOIN users u ON u.id = p.user_id, users me
            WHERE p.code = ? AND me.id = ? AND p.user_id != me.id AND u.username = me.username COLLATE NOCASE''',
            (r['code'], session['user_id'])).fetchone()
        if clash:
            return render_template('apology.html', message = "Someone in this room already has your name: pick another nickname")
        # joining before the end means playing live, even mid-game; a finished
        # classic room can still be played alone, the other modes only looked at
        c.execute("INSERT OR IGNORE INTO room_players (code, user_id, live, last_seen) VALUES (?, ?, ?, ?)",
                  (r['code'], session['user_id'], int(r['state'] != 'finished' or r['mode'] != 'classic'), time.time()))
    return render_template('room.html', code = r['code'])

@app.route("/api/room/<code>")
def room_state(code):
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
                p.seat, p.last_seen > ? AS here, COALESCE(SUM(g.score), 0) AS total, COUNT(g.round) AS played,
                COALESCE(MAX(g.round = ?), 0) AS guessed
            FROM room_players p JOIN users u ON u.id = p.user_id
            LEFT JOIN room_guesses g ON g.code = p.code AND g.user_id = p.user_id
            WHERE p.code = ? GROUP BY p.user_id ORDER BY p.rowid''',
            (me['user_id'], r['host_id'], now - AWAY, n, r['code'])).fetchall()
        # duel and royale: health or lives after the last finished round
        st = {}
        if r['mode'] != 'classic' and r['state'] != 'waiting':
            st = standings(c, r, r['round'] if r['state'] == 'finished' or r['round_end'] is not None else r['round'] - 1)
        out = {"success": True, "code": r['code'], "mode": r['mode'], "state": r['state'],
               "host": r['host_id'] == me['user_id'], "live": live, "round": n, "rounds": r['rounds'],
               "next": r['next_code'],
               "settings": {"mode": r['mode'], "provinces": json.loads(r['provinces']), "rounds": r['rounds'],
                            "time_limit": r['time_limit'], "look": bool(r['look'])},
               # the colour of a player is their place in the join order
               "players": [dict(p, color = i, **st.get(p['uid'], {})) for i, p in enumerate(players)]}
        # chat: the messages the page has not seen yet (it says which was its last)
        colors = {p['uid']: p['color'] for p in out['players']}
        since = request.args.get('chat', '')
        out['chat'] = [dict(m, color = colors.get(m['uid'], 0)) for m in reversed(c.execute(
            '''SELECT m.id, m.user_id AS uid, u.username AS name, m.text FROM room_chat m JOIN users u ON u.id = m.user_id
            WHERE m.code = ? AND m.id > ? ORDER BY m.id DESC LIMIT 50''',
            (r['code'], int(since) if since.isnumeric() else 0)).fetchall())]
        for p in out['players'] + out['chat']:
            del p['uid']
        if r['mode'] == 'duel':
            out['multiplier'] = multiplier(max(n, 1))
        if n == 0 or (live and r['state'] == 'waiting'):
            return jsonify(out)
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (json.loads(r['locations'])[n - 1],)).fetchone()
        out['url'] = loc['image_url']
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
                    out['next_url'] = c.execute("SELECT image_url FROM locations WHERE location_id = ?", (ids[n],)).fetchone()[0]
        return jsonify(out)

@app.route("/api/room/<code>/chat", methods=['POST'])
def room_chat(code):
    text = ' '.join(request.form.get('text', '').split())[:200]
    with room_tx() as c:
        r, me = member(c, code)
        if not r or not text:
            return jsonify({"success": False})
        last = c.execute("SELECT MAX(at) FROM room_chat WHERE code = ? AND user_id = ?", (r['code'], me['user_id'])).fetchone()[0]
        if last and time.time() - last < 0.7:
            return jsonify({"success": False, "error": "Slow down a little"})
        c.execute("INSERT INTO room_chat (code, user_id, at, text) VALUES (?, ?, ?, ?)", (r['code'], me['user_id'], time.time(), text))
    return jsonify({"success": True})

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
        c.execute("UPDATE rooms SET mode = ?, provinces = ?, rounds = ?, time_limit = ?, look = ?, locations = ? WHERE code = ?",
                  (s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations, r['code']))
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
            c.execute("UPDATE rooms SET state = 'playing', round = 1, round_start = ?, round_end = NULL WHERE code = ?",
                      (now, r['code']))
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
            nxt = new_room(c, me['user_id'], {'mode': r['mode'], 'provinces': json.loads(r['provinces']),
                                              'rounds': r['rounds'], 'time_limit': r['time_limit'], 'look': r['look']})
            c.execute("UPDATE rooms SET next_code = ? WHERE code = ?", (nxt, r['code']))
    return jsonify({"success": bool(nxt), "code": nxt})

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
REVIEWERS = ('Yasuro', 'kemmi')   # exact usernames
REVIEW_PROVINCES = PROVINCES + ['fruma']

def capture_key():
    try:
        with open(CAPTURE_KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None

def key_ok():
    key = capture_key()
    return bool(key) and secrets.compare_digest(request.headers.get('X-Wynndle-Key', ''), key)

def is_reviewer():
    if not session.get('loggedin') or not capture_key():
        return False
    with connect() as c:
        me = c.execute("SELECT username FROM users WHERE id = ? AND COALESCE(guest, 0) = 0", (session.get('user_id'),)).fetchone()
    return bool(me) and me['username'] in REVIEWERS

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
                    img.crop((j * TILE, i * TILE, (j + 1) * TILE, (i + 1) * TILE)).save(
                        os.path.join(tmp, str(level), f'{letter}{i}_{j}.jpg'), quality=90)
        os.makedirs(os.path.join(tmp, 'fallback'), exist_ok=True)
        face.resize((1024, 1024), Image.Resampling.LANCZOS).save(os.path.join(tmp, 'fallback', letter + '.jpg'), quality=90)
    os.rename(tmp, os.path.join(TILES_DIR, name))
    return 'static/tiles/' + name + '/'

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
    return render_template('review.html', provinces = REVIEW_PROVINCES)

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

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
