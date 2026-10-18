from flask import Flask, render_template, url_for, request, redirect, session, send_from_directory, send_file, jsonify
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
import base64
import hashlib
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
# never sent with another site's forms (nobody can act for a player from
# elsewhere), and only over https
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = True

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

@app.after_request
def only_one_site_in_search(response):
    # beta.wynndle.com and the old ts.net address are the same site: kept out
    # of search engines, so Google only lists wynndle.com
    if request.host != 'wynndle.com':
        response.headers['X-Robots-Tag'] = 'noindex'
    return response

@app.after_request
def no_tricks(response):
    # no page of this site inside another site's frame (fake buttons over
    # real ones), and a file is only ever read as the type it is served as
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

def next_page():
    # where to go after logging in: only a page of this site, e.g. "room?code=ABC234"
    page = request.args.get('next', '')
    return page if re.fullmatch(r'[a-z]+(\?(code|play)=[A-Za-z0-9_-]+)?', page) else './'

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
        query += " AND s.provinces = ? AND s.nolook = ? AND s.rounds = ?"
        params += [form.get('provinces', ''), form.get('nolook', 'No'), form.get('rounds', '')]
        order = " ORDER BY s.score DESC, s.time ASC"
    else:
        query += " AND s.difficulty = ?"
        params.append(form.get('difficulty', 'normal'))
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
        rows = rows[:50]
        # each player's picture; a Minecraft head is drawn sharp
        for row in rows:
            row['pic'], row['head'] = avatar_url(row), not row.pop('avatar')
            row.pop('mc_uuid')
    return jsonify({"rows": rows, "me": session.get('user_id')})

@app.route("/")
def index():
    return render_template('index.html')

@app.route("/mode")
def play():
    return render_template('mode.html')

@app.route("/leaderboard")
def leaderboard():
    return render_template('leaderboard.html')

DISCORD = 'https://discord.gg/fMqQ2p5mZr'

@app.route("/about")
def about():
    return render_template('about.html', discord = DISCORD)

@app.route("/game", methods=['POST', 'GET'])
def game():
    # the mode page sends its settings in the address, so "Play Again" is a plain reload
    form = request.values
    if form.get('mode') == 'survival':
        # Survival has its own page (and no settings but the difficulty)
        return redirect('survival?' + urlencode({'difficulty': form.get('difficulty', 'normal')}))
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

        return render_template('game.html', provinces = provinces, time_limit = time_limit, look = look, rounds = rounds, mode = mode)
    return render_template('game.html', provinces = "['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse', 'fruma']", time_limit = -1, look = False, rounds = 5, mode = 'classic')

# ---------- Accounts ----------

TRIES = 10       # wrong passwords (or recovery codes) for one account from one place...
WINDOW = 900     # ...in this many seconds, then it has to wait
FAILS = {}       # (place, name) and name -> times of the recent failures (one worker: memory is enough)

def place():
    # behind Cloudflare or Funnel every request comes from 127.0.0.1: the
    # real address is in their header
    return request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr

def too_many(name):
    # also a cap per account whatever the place, a little higher
    now, name = time.time(), name.lower()
    if len(FAILS) > 10000:
        FAILS.clear()
    for k in ((place(), name), name):
        FAILS[k] = [t for t in FAILS.get(k, ()) if now - t < WINDOW]
    return len(FAILS[(place(), name)]) >= TRIES or len(FAILS[name]) >= 3 * TRIES

def failed(name):
    for k in ((place(), name.lower()), name.lower()):
        FAILS.setdefault(k, []).append(time.time())

def stamp(hashed):
    # a trace of the password in the session: when it changes, every other
    # browser logged in with the old one is logged out
    return hashlib.sha256((hashed or '').encode()).hexdigest()[:16]

@app.before_request
def still_logged_in():
    if request.endpoint == 'static' or not session.get('loggedin'):
        return
    with connect() as c:
        me = c.execute("SELECT password FROM users WHERE id = ? AND COALESCE(guest, 0) = 0", (session.get('user_id'),)).fetchone()
    if me and session.setdefault('stamp', stamp(me[0])) == stamp(me[0]):
        return
    session.clear()

def log_in(c, uid, wynn = False):
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
                log_in(c, user[0])
                return redirect(next_page())
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
            problem = name_problem(c, username) or password_problem(password, confirmation)
            if problem:
                return render_template('apology.html', message = problem)
            uid = c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed(password))).lastrowid
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
            log_in(c, user['id'])
            return redirect('account?saved=recovered')
    failed(username)
    return render_template('apology.html', message = "Wrong username or recovery code")

@app.route("/logout")
def logout():
    session.clear()
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

ADMINS = (1,)    # user ids that may take down someone's picture: Yasuro
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
    return render_template('profile.html', user = user, username = user['username'], mc_name = user['mc_name'],
                           avatar = avatar_url(user), own = uid == session.get('user_id') and session.get('loggedin'),
                           admin = session.get('loggedin') and session.get('user_id') in ADMINS,
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
        # an admin takes down a picture that should not be there
        if not (session.get('loggedin') and session.get('user_id') in ADMINS):
            return render_template('apology.html', message = "Not allowed"), 403
        with connect() as c:
            drop_picture(c, uid)
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
    with connect() as c:
        user = c.execute("SELECT avatar, mc_uuid FROM users WHERE id = ?", (request.args.get('id', type = int),)).fetchone()
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
    drop_picture(c, uid)
    c.execute("UPDATE users SET avatar = ? WHERE id = ?", (name, uid))

def drop_picture(c, uid):
    # back to the Minecraft head
    old = c.execute("SELECT avatar FROM users WHERE id = ?", (uid,)).fetchone()
    if old and old[0]:
        c.execute("UPDATE users SET avatar = NULL WHERE id = ?", (uid,))
        try:
            os.remove(os.path.join(AVATAR_DIR, old[0] + '.webp'))
        except OSError:
            pass

@app.route("/account", methods=['GET', 'POST'])
def account():
    # one's own picture, name, password and recovery code
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
            problem = save_picture(c, uid, request.files['picture']) if 'picture' in request.files else "Pick a picture"
        elif what == 'head':
            problem = drop_picture(c, uid)
        elif what in ('name', 'mc-name'):
            name = me['mc_name'] if what == 'mc-name' else clean_name(form.get('username', ''))
            problem = name_problem(c, name or '', uid)
            if not problem:
                c.execute("UPDATE users SET username = ? WHERE id = ?", (name, uid))
            what = 'name'
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
    return render_template('account.html', me = me, avatar = avatar_url(me), section = section, error = error,
                           code = code, saved = request.args.get('saved'), need_current = bool(me['password']) and not session.get('wynn'))

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
        games.append({'multi': True, 'code': r['code'], 'mode': r['mode'], 'rank': rank, 'of': len(players), 'win': rank == 1,
                      'score': totals.get(uid, 0), 'rounds': r['round'], 'when': when or 0,
                      'left': st.get(uid, {}).get('left'), 'out': st.get(uid, {}).get('out'),
                      'survived': st.get(uid, {}).get('survived')})
    for g in c.execute('''SELECT score, rounds, time, date, COALESCE(mode, 'classic') AS mode, difficulty FROM scores
            WHERE user_id = ? AND room IS NULL''', (uid,)).fetchall():
        try:
            when = time.mktime(time.strptime(g['date'], '%Y-%m-%d'))
        except (TypeError, ValueError):
            when = 0
        games.append({'multi': False, 'mode': g['mode'], 'score': g['score'], 'rounds': g['rounds'],
                      'difficulty': g['difficulty'], 'time': g['time'], 'when': when})
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
        log_in(c, uid, wynn = True)
    return redirect('../../' + session.pop('wynn_next', './'))

@app.route("/apology")
def apology():
    message = request.args.get('message', 'Something went wrong')
    return render_template('apology.html', message = message)

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
                'difficulty': form['difficulty']}, None
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
            'time_limit': time_limit, 'look': int(form.get('look') == 'on'), 'difficulty': None}, None

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

def new_room(c, host, s):
    locations = pick_locations(c, s)
    if not locations:
        return None
    code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    while find_room(c, code):
        code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    c.execute('''INSERT INTO rooms (code, host_id, mode, provinces, rounds, time_limit, look, locations, state, round, round_start, difficulty)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', 0, 0, ?)''',
        (code, host, s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations, s['difficulty']))
    c.execute("INSERT INTO room_players (code, user_id, live, last_seen) VALUES (?, ?, 1, ?)", (code, host, time.time()))
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
        if c.execute("SELECT 1 FROM room_bans WHERE code = ? AND user_id = ?", (r['code'], session['user_id'])).fetchone():
            return render_template('apology.html', message = "The host removed you from this room")
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
        if r['mode'] in ('duel', 'royale') and r['state'] != 'waiting':
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
        # players keep their id: the host's tools (make host, kick) name them by it
        for p in out['chat']:
            del p['uid']
        if r['mode'] == 'duel':
            out['multiplier'] = multiplier(max(n, 1))
        if r['mode'] == 'survival':
            out['settings']['difficulty'] = r['difficulty']
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
        c.execute("UPDATE rooms SET mode = ?, provinces = ?, rounds = ?, time_limit = ?, look = ?, locations = ?, difficulty = ? WHERE code = ?",
                  (s['mode'], json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations, s['difficulty'], r['code']))
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
                                              'difficulty': r['difficulty'] or ('normal' if mode == 'survival' else None)})
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
                    img.crop((j * TILE, i * TILE, (j + 1) * TILE, (i + 1) * TILE)).save(
                        os.path.join(tmp, str(level), f'{letter}{i}_{j}.jpg'), quality=90)
        os.makedirs(os.path.join(tmp, 'fallback'), exist_ok=True)
        face.resize((1024, 1024), Image.Resampling.LANCZOS).save(os.path.join(tmp, 'fallback', letter + '.jpg'), quality=90)
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
        row = c.execute("""SELECT CASE WHEN t.fog = 1 AND l.fog_url IS NOT NULL THEN l.fog_url ELSE l.image_url END
                FROM tiles t JOIN locations l ON l.location_id = t.location_id WHERE t.token = ?""", (token,)).fetchone()
    if not row or not row[0].startswith('static/tiles/'):
        return '', 404
    response = send_from_directory(os.path.join(TILES_DIR, row[0][len('static/tiles/'):].strip('/')), name, max_age = 3600)
    response.cache_control.private = True   # the browser keeps it, Cloudflare does not (see Survival)
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
    # the settings of the mode page, checked: provinces in the order of
    # PROVINCES (the leaderboard compares them as text), rounds, time, view
    chosen = form.getlist('province')
    provinces = [p for p in PROVINCES if p in chosen]
    try:
        rounds, limit = int(form.get('rounds', '')), int(form.get('time_limit', -1))
    except ValueError:
        return None
    if not provinces or rounds not in SOLO_ROUNDS or not (limit == -1 or 1 <= limit <= 1800):
        return None
    return {'provinces': provinces, 'rounds': rounds, 'time_limit': limit, 'look': form.get('look') == 'true'}

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
MILK = 2                   # milk buckets a run starts with: each one cancels the potion thrown with a result

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
    # the milk buckets left, and the potion a bucket cancelled (with the result it was thrown at)
    if 'milk' not in [col[1] for col in c.execute("PRAGMA table_info(survival_runs)")]:
        c.execute(f"ALTER TABLE survival_runs ADD COLUMN milk INTEGER DEFAULT {MILK}")
        c.execute("ALTER TABLE survival_guesses ADD COLUMN milked TEXT")
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
        c.execute("UPDATE scores SET score = ?, points = ?, time = ? WHERE id = ?",
                  (run['survived'], run['points'], round(run['time'], 2), run['score_id']))
    else:
        sid = c.execute("""INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode, difficulty, points)
                VALUES (?, ?, ?, 'No', '', NULL, ?, 'survival', ?, ?)""",
                (run['user_id'], run['survived'], date.today(), round(run['time'], 2), run['difficulty'], run['points'])).lastrowid
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
           "phase": run['phase'], "test": bool(run['test'])}
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
                           test = request.args.get('test') == '1' and survival_tester())

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
        rid = c.execute("INSERT INTO survival_runs (user_id, difficulty, hp, phase, started, test, milk) VALUES (?, ?, ?, 'new', ?, ?, ?)",
                        (uid, difficulty, DIFFICULTIES[difficulty], time.time(), int(test), MILK)).lastrowid
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
    response.cache_control.private = True
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
# As in the other rooms, once someone guessed the others have LAST_CALL
# seconds (Yasuro: nobody may hold the room up), or less if their own clock
# (Swiftness) ends sooner. Against cheating, as alone: the server's clock, a
# purchase checked against the emeralds left and the shop's hours, a guess
# only in its round. Known limits: the picture
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
# the median player buys a cheap potion every round, a dear one every three
PRICES = {'mining_fatigue': 5, 'swiftness': 5, 'wither': 10, 'nausea': 10, 'blindness': 10, 'milk': 10,
          'darkness': 15, 'regeneration': 15}
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

def survival_deadline(r, fx, cut):
    # a player's end of the round: their own clock, or the last call if sooner
    own = r['round_start'] + room_time(r['difficulty'], fx)
    return min(own, cut) if cut else own

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
    # living, Regeneration and milk (MILK_BUYS at most, then out of stock)
    fog = next_fog(c, r)
    return {k: p for k, p in PRICES.items() if (k not in SELF or s['out'] is None) and (k != 'blindness' or fog)
            and (k != 'milk' or s['milk_bought'] < MILK_BUYS)}

def present(c, r):
    return {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND last_seen > ?", (r['code'], time.time() - AWAY))}

def shop_shut(c, r, st):
    # the shop closes after SHOP seconds, or once everyone here is ready;
    # who cannot pay for anything is ready already
    if time.time() >= r['round_end'] + REVEAL + SHOP:
        return True
    ready = {p[0] for p in c.execute("SELECT user_id FROM room_players WHERE code = ? AND ready = ?", (r['code'], r['round']))}
    for u in present(c, r) & set(st) - ready:
        prices = wares(c, r, st[u]).values()
        if prices and st[u]['emeralds'] >= min(prices):
            return False
    return True

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
        cut, _ = round_deadline(c, r)
        ends = {u: survival_deadline(r, room_effects(shop, milked, u, n), cut) for u in alive - done}
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
    c.execute("""INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time, mode, difficulty, points, room)
            VALUES (?, ?, ?, 'No', '', NULL, ?, 'survival', ?, ?, ?)""",
            (uid, s['survived'], date.today(), round(spent, 2), r['difficulty'], points, r['code']))

def survival_room_guess(c, r, me, n):
    # a guess in its round, within the player's own clock (Nausea: the hand shakes)
    now, uid = time.time(), me['user_id']
    if (not me['live'] or r['state'] != 'playing' or n != r['round'] or r['round_end'] is not None
            or now < r['round_start'] or uid not in guessers(c, r)):
        return False
    shop, milked = room_shop_rows(c, r['code'])
    fx = room_effects(shop, milked, uid, n)
    deadline = survival_deadline(r, fx, round_deadline(c, r)[0])
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
            # who cannot pay for anything is ready already (shop_shut)
            prices = wares(c, r, s).values()
            p['ready'] = p['uid'] in ready or not prices or s['emeralds'] < min(prices)
        if closed and 'result' in s:
            p['result'] = {k: v for k, v in s['result'].items() if k != 'earned'}
    mine = st.get(uid)
    out['playing'] = bool(mine and mine['out'] is None and me['live'] and phase != 'finished')
    if mine:
        out['me'] = {"emeralds": mine['emeralds'], "milk": mine['milk'], "milk_left": MILK_BUYS - mine['milk_bought'],
                     "earned": mine.get('result', {}).get('earned') if closed else None}
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
                cut, out['first'] = round_deadline(c, r)
                # elapsed: since the start, for what counts from it (Darkness, Wither)
                out.update({"time_left": max(0, survival_deadline(r, fx, cut) - now), "elapsed": now - r['round_start']})
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
        c.execute("INSERT INTO room_shop (code, round, buyer, target, item, at) VALUES (?, ?, ?, ?, ?, ?)",
                  (r['code'], r['round'] + 1, uid, target, item, time.time()))
    return jsonify({"success": True, "emeralds": s['emeralds'] - PRICES[item]})

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


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
