from flask import Flask, render_template, url_for, request, redirect, session, send_from_directory, jsonify
from flask_session import Session
from flask_cors import CORS
import os
import re
import sqlite3
import json
import math
import secrets
import time
from datetime import date
from urllib.parse import quote
from flask_bcrypt import Bcrypt
from config import Config

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app)
app.config.from_object(Config)
# other sites share this domain behind Tailscale Funnel
app.config['SESSION_COOKIE_NAME'] = 'wynnguessr_session'

def connect():
    # one connection per request: a single shared one is not safe across threads
    c = sqlite3.connect('database.db', timeout=10)
    c.row_factory = sqlite3.Row
    return c

def next_page():
    # where to go after logging in: only a page of this site, e.g. "room?code=ABC234"
    page = request.args.get('next', '')
    return page if re.fullmatch(r'[a-z]+(\?code=[A-Za-z0-9_-]+)?', page) else './'

@app.route("/api/locations", methods = ['GET'])
def get_locations():
    #if there are no provinces in session, return apology
    if 'provinces' not in session:
        return jsonify({"success": False})
    provinces = session['provinces']
    placeholders = ', '.join('?' for _ in provinces)
    query = f"SELECT * FROM locations WHERE province IN ({placeholders})"
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
        if request.form['rounds'] not in ['3', '5', '10', '25']:
            return render_template('apology.html', message = "Invalid number of rounds")
        rounds = request.form['rounds']
        totalTime = request.form['totalTime']
        print(int(rounds) * 5000)
        if(int(score) > int(rounds) * 5000):
            return jsonify({"success": False})
        if(int(rounds) * 5000 == int(score) and int(totalTime) < .5):
            return jsonify({"success": False})
        with connect() as c:
            c.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time) VALUES (?, ?, ?, ?, ?, ?, ?)", (session['user_id'], score, date.today(), look, provinces, rounds, totalTime))
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/api/updaterank", methods=['POST'])
def update_rank():
    if request.method == 'POST':
        form = request.form
        with connect() as c:
            rankings = c.execute('''
            SELECT users.username, scores.score, scores.date, scores.nolook, scores.rounds, scores.time
            FROM users
            JOIN (SELECT user_id,
                    MAX(score) as max_score
                 FROM
                    scores
                 WHERE
                    provinces = ? AND nolook = ? AND rounds = ?
                 GROUP BY
                    user_id
                ) as top_scores
            ON
                users.id = top_scores.user_id
            JOIN
                scores
            ON
                scores.user_id = top_scores.user_id AND scores.score = top_scores.max_score
            WHERE
                scores.provinces = ? AND scores.nolook = ? AND scores.rounds = ?
            ORDER BY
                scores.score DESC, scores.time ASC
            LIMIT 50
        ''', (str(form['provinces']), form['nolook'], form['rounds'], str(form['provinces']), form['nolook'], form['rounds'])).fetchall()

        return jsonify({"rankings": [tuple(r) for r in rankings]})
    return jsonify({"success": False})

@app.route("/api/updateprofile", methods=['POST'])
def update_profile():
    if request.method == 'POST':
        if not session.get('loggedin'):
            return jsonify({"games": []})
        form = request.form
        with connect() as c:
            games = c.execute('SELECT username, score, date, nolook, rounds, time FROM users JOIN scores ON users.id = scores.user_id WHERE user_id = ? AND provinces = ? AND nolook = ? AND rounds = ? ORDER BY score DESC, time ASC LIMIT 50', (session['user_id'], str(form['provinces']), form['nolook'], form['rounds'])).fetchall()
        return jsonify({"games": [tuple(g) for g in games]})
    return jsonify({"success": False})

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
    session['provinces'] = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']
    if request.method == 'POST':
        #if there are no provinces selected, return apology
        if request.form.getlist('province') == []:
            return render_template('apology.html', message = "Please select at least one province")
        provinces = request.form.getlist('province')
        #if time limit is not selected, set time limit to -1
        if request.form.get('time-limit-checkbox') == None:
            time_limit = -1
        #if time limit is selected, check if time limit is a number and greater than 0
        elif request.form.get('time-limit-checkbox') == 'on':
            #if time limit is not entered, return apology
            if request.form.get('time-limit') == "":
                return render_template('apology.html', message = "Please enter a time limit")
            #if time limit is not a number, return apology
            if request.form.get('time-limit').isnumeric() == False:
                return render_template('apology.html', message = "Time limit must be a number")
            #if time limit is less than 1, return apology
            if int(request.form.get('time-limit')) < 0:
                return render_template('apology.html', message = "Time limit cannot be less than 0 seconds")
            if int(request.form.get('time-limit')) > 1800:
                return render_template('apology.html', message = "Time limit cannot be greater than 30 minutes")
            time_limit = int(request.form.get('time-limit'))
        #if look is not selected, set look to False
        look = request.form.get('look') == 'on'
        rounds = request.form.get('rounds')
        #store provinces in session
        session['provinces'] = provinces
        print(provinces, time_limit, look, rounds)

        return render_template('game.html', provinces = provinces, time_limit = time_limit, look = look, rounds = rounds)
    return render_template('game.html', provinces = "['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']", time_limit = -1, look = False, rounds = 5)

@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.method == 'POST':#user login request
        username = request.form['username']
        password = request.form['password']

        if username == "" or password == "":
            return render_template('apology.html', message = "Please fill in all fields")
        with connect() as c:
            user = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and bcrypt.check_password_hash(user[2], password):
            session.permanent = True
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
            elif c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchall():
                return render_template('apology.html', message = "Username is already taken")
            elif username == "" or password == "" or confirmation == "":
                return render_template('apology.html', message = "Please fill in all fields")
            else:
                hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
                c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
                user = c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
                session.permanent = True
                session['loggedin'] = True
                session['user_id'] = user[0]
                return redirect(next_page())
    else:
        return render_template('register.html')

@app.route("/logout")
def logout():
    session['loggedin'] = False
    session['user_id'] = None
    return redirect('./')

@app.route("/profile")
def profile():
    if not session.get('loggedin'):
        return redirect('login?next=profile')
    with connect() as c:
        profile = c.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    return render_template('profile.html', username = profile[0])

@app.route("/apology")
def apology():
    message = request.args.get('message', 'Something went wrong')
    return render_template('apology.html', message = message)

# ---------- Multiplayer rooms ----------
# A room is a fixed list of locations, played live by everyone who joins before
# the end: same round at the same time, the round closes once all have guessed
# (or the clock runs out) and the next one starts by itself after the reveal.
# Anyone opening the room after the end plays the same locations alone and
# lands in the same ranking. Rooms only move forward when someone asks: every
# room request first runs tick().

PROVINCES = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']
ROUNDS = ['3', '5', '10', '25']
LAST_CALL = 15   # once someone guessed, the others have this long
REVEAL = 10      # the answer stays on screen this long before the next round
AWAY = 10        # a page that stopped polling this long is not waited for
HOST_AWAY = 30   # a host gone this long hands the room over (else nobody could start)
GRACE = 1        # guesses still accepted this long after the deadline (network lag)
CODE_CHARS = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # no 0/O or 1/I/L to mistype

with connect() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY, host_id INTEGER, provinces TEXT, rounds INTEGER,
            time_limit INTEGER, look INTEGER, locations TEXT, state TEXT,
            round INTEGER, round_start REAL, round_end REAL, next_code TEXT);
        CREATE TABLE IF NOT EXISTS room_players (
            code TEXT, user_id INTEGER, live INTEGER, last_seen REAL,
            recorded INTEGER DEFAULT 0, PRIMARY KEY (code, user_id));
        CREATE TABLE IF NOT EXISTS room_guesses (
            code TEXT, user_id INTEGER, round INTEGER, x REAL, z REAL, score INTEGER,
            at REAL, time REAL, PRIMARY KEY (code, user_id, round));
    ''')

def room_tx():
    # room requests read then write: taking the write lock first means two
    # requests can never both move the same room forward
    c = connect()
    c.execute('BEGIN IMMEDIATE')
    return c

def find_room(c, code):
    return c.execute("SELECT * FROM rooms WHERE code = ? COLLATE NOCASE", (code.strip(),)).fetchone()

def room_settings(form):
    # the same choices as the solo mode page; returns (settings, error)
    provinces = [p for p in PROVINCES if p in form.getlist('province')]
    if not provinces:
        return None, "Please select at least one province"
    if form.get('rounds') not in ROUNDS:
        return None, "Invalid number of rounds"
    time_limit = -1
    if form.get('time-limit-checkbox') == 'on':
        t = form.get('time-limit', '')
        if not t.isnumeric() or not 0 < int(t) <= 1800:
            return None, "Time limit must be between 1 and 1800 seconds"
        time_limit = int(t)
    return {'provinces': provinces, 'rounds': int(form['rounds']), 'time_limit': time_limit,
            'look': int(form.get('look') == 'on')}, None

def pick_locations(c, s):
    ids = [r[0] for r in c.execute(
        f"SELECT location_id FROM locations WHERE province IN ({', '.join('?' * len(s['provinces']))}) ORDER BY RANDOM() LIMIT ?",
        (*s['provinces'], s['rounds']))]
    return json.dumps(ids) if len(ids) == s['rounds'] else None

def new_room(c, host, s):
    locations = pick_locations(c, s)
    if not locations:
        return None
    code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    while find_room(c, code):
        code = ''.join(secrets.choice(CODE_CHARS) for _ in range(6))
    c.execute('''INSERT INTO rooms (code, host_id, provinces, rounds, time_limit, look, locations, state, round, round_start)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting', 0, 0)''',
        (code, host, json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations))
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

def record(c, r, uid):
    # a finished room game also counts for the leaderboard and the profile
    if c.execute("SELECT recorded FROM room_players WHERE code = ? AND user_id = ?", (r['code'], uid)).fetchone()[0]:
        return
    c.execute("UPDATE room_players SET recorded = 1 WHERE code = ? AND user_id = ?", (r['code'], uid))
    total, spent, guessed = c.execute('''SELECT COALESCE(SUM(score), 0), COALESCE(SUM(time), 0), COUNT(x)
        FROM room_guesses WHERE code = ? AND user_id = ?''', (r['code'], uid)).fetchone()
    if guessed:
        c.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (uid, total, date.today(), 'Yes' if r['look'] else 'No', str(json.loads(r['provinces'])),
                   r['rounds'], round(spent, 2)))

def next_round(c, r):
    if r['round'] < r['rounds']:
        c.execute("UPDATE rooms SET round = round + 1, round_start = ?, round_end = NULL WHERE code = ?",
                  (time.time(), r['code']))
    else:
        c.execute("UPDATE rooms SET state = 'finished' WHERE code = ?", (r['code'],))
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
        waiting = c.execute('''SELECT COUNT(*) FROM room_players p WHERE code = ? AND live = 1 AND last_seen > ?
            AND NOT EXISTS (SELECT 1 FROM room_guesses g WHERE g.code = p.code AND g.user_id = p.user_id AND g.round = ?)''',
            (r['code'], now - AWAY, r['round'])).fetchone()[0]
        if waiting and (deadline is None or now < deadline + GRACE):
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
    if not session.get('loggedin'):
        return redirect('../login?next=mode')
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
    if not session.get('loggedin'):
        return redirect('login?next=' + quote('room?code=' + code))
    with room_tx() as c:
        r = find_room(c, code)
        if not r:
            return render_template('apology.html', message = "No room with the code " + code)
        # joining before the end means playing live, even mid-game
        c.execute("INSERT OR IGNORE INTO room_players (code, user_id, live, last_seen) VALUES (?, ?, ?, ?)",
                  (r['code'], session['user_id'], int(r['state'] != 'finished'), time.time()))
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
        players = c.execute('''SELECT u.username AS name, p.user_id = ? AS you, p.user_id = ? AS host,
                p.last_seen > ? AS here, COALESCE(SUM(g.score), 0) AS total, COUNT(g.round) AS played,
                COALESCE(MAX(g.round = ?), 0) AS guessed
            FROM room_players p JOIN users u ON u.id = p.user_id
            LEFT JOIN room_guesses g ON g.code = p.code AND g.user_id = p.user_id
            WHERE p.code = ? GROUP BY p.user_id ORDER BY p.rowid''',
            (me['user_id'], r['host_id'], now - AWAY, n, r['code'])).fetchall()
        out = {"success": True, "code": r['code'], "state": r['state'], "host": r['host_id'] == me['user_id'],
               "live": live, "round": n, "rounds": r['rounds'], "next": r['next_code'],
               "settings": {"provinces": json.loads(r['provinces']), "rounds": r['rounds'],
                            "time_limit": r['time_limit'], "look": bool(r['look'])},
               # the colour of a player is their place in the join order
               "players": [dict(p, color = i) for i, p in enumerate(players)]}
        if n == 0 or (live and r['state'] == 'waiting'):
            return jsonify(out)
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?", (json.loads(r['locations'])[n - 1],)).fetchone()
        out['url'] = loc['image_url']
        out['answered'] = bool(c.execute("SELECT 1 FROM room_guesses WHERE code = ? AND user_id = ? AND round = ?",
                                         (r['code'], me['user_id'], n)).fetchone())
        if live and r['state'] == 'playing' and r['round_end'] is None:
            deadline, first = round_deadline(c, r)
            if deadline:
                out['time_left'] = max(0, deadline - now)
            out['first'] = first
        elif live or out['answered']:
            # the round is over for this player: everyone's guesses can be shown
            # upto: total up to this round, so that a late player compares like with like
            out['reveal'] = {"X": loc['x_position'], "Z": loc['z_position'], "guesses": [dict(g) for g in c.execute(
                '''SELECT u.username AS name, g.x, g.z, g.score, (SELECT SUM(h.score) FROM room_guesses h
                    WHERE h.code = g.code AND h.user_id = g.user_id AND h.round <= g.round) AS upto
                FROM room_guesses g JOIN users u ON u.id = g.user_id WHERE g.code = ? AND g.round = ?''', (r['code'], n))]}
            if live and r['state'] == 'playing':
                out['next_in'] = max(0, r['round_end'] + REVEAL - now)
        return jsonify(out)

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
        c.execute("UPDATE rooms SET provinces = ?, rounds = ?, time_limit = ?, look = ?, locations = ? WHERE code = ?",
                  (json.dumps(s['provinces']), s['rounds'], s['time_limit'], s['look'], locations, r['code']))
    return jsonify({"success": True})

@app.route("/api/room/<code>/start", methods=['POST'])
def room_start(code):
    # host only: starts the game, or cuts a reveal short
    with room_tx() as c:
        r, me = member(c, code)
        if not r or r['host_id'] != me['user_id']:
            return jsonify({"success": False})
        r = tick(c, r)
        if r['state'] == 'waiting':
            c.execute("UPDATE rooms SET state = 'playing', round = 1, round_start = ?, round_end = NULL WHERE code = ?",
                      (time.time(), r['code']))
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
            if r['state'] != 'playing' or n != r['round'] or r['round_end'] is not None:
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
            nxt = new_room(c, me['user_id'], {'provinces': json.loads(r['provinces']), 'rounds': r['rounds'],
                                              'time_limit': r['time_limit'], 'look': r['look']})
            c.execute("UPDATE rooms SET next_code = ? WHERE code = ?", (nxt, r['code']))
    return jsonify({"success": bool(nxt), "code": nxt})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
