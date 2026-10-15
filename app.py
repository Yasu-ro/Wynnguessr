from flask import Flask, render_template, url_for, request, redirect, session, send_from_directory, jsonify 
from flask_session import Session
from flask_cors import CORS
import os
import sqlite3
import json
import math
import secrets
import time
from datetime import date
from flask_bcrypt import Bcrypt 
from config import Config

app = Flask(__name__)
CORS(app)
bcrypt = Bcrypt(app) 
app.config.from_object(Config)
conn = sqlite3.connect('database.db', check_same_thread=False)
db = conn.cursor()

@app.route("/api/locations", methods = ['GET'])
def get_locations():
    #if there are no provinces in session, return apology
    if 'provinces' not in session:
        return jsonify({"success": False})
    provinces = session['provinces']
    placeholders = ', '.join('?' for _ in provinces)
    query = f"SELECT * FROM locations WHERE province IN ({placeholders})"
    locations = db.execute(query, provinces).fetchall()
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
        db.execute("INSERT INTO scores (user_id, score, date, nolook, provinces, rounds, time) VALUES (?, ?, ?, ?, ?, ?, ?)", (session['user_id'], score, date.today(), look, provinces, rounds, totalTime))
        conn.commit()
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/api/updaterank", methods=['POST'])
def update_rank():
    if request.method == 'POST':
        form = request.form
        rankings = db.execute('''
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
        
        return jsonify({"rankings": rankings})
    return jsonify({"success": False})

@app.route("/api/updateprofile", methods=['POST'])
def update_profile():
    if request.method == 'POST':
        form = request.form
        games = db.execute('SELECT username, score, date, nolook, rounds, time FROM users JOIN scores ON users.id = scores.user_id WHERE user_id = ? AND provinces = ? AND nolook = ? AND rounds = ? ORDER BY score DESC, time ASC LIMIT 50', (session['user_id'], str(form['provinces']), form['nolook'], form['rounds'])).fetchall()
        return jsonify({"games": games})
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
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and bcrypt.check_password_hash(user[2], password):
            session['loggedin'] = True
            session['user_id'] = user[0]
            return redirect('/')
        else:
            return render_template('apology.html', message = "Invalid username or password")
    else:
        return render_template('login.html')

@app.route("/register", methods=['POST', 'GET'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirmation = request.form['confirmation']
        if len(username) > 20:
            return render_template('apology.html', message = "Username must be less than 32 characters")
        if len(password) > 64:
            return render_template('apology.html', message = "Password must be less than 128 characters")
        if password != confirmation:
            return render_template('apology.html', message = "Passwords do not match")
        elif db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchall():
            return render_template('apology.html', message = "Username is already taken")
        elif username == "" or password == "" or confirmation == "":
            return render_template('apology.html', message = "Please fill in all fields")
        else:
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            db.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
            conn.commit()
            user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            session['loggedin'] = True
            session['user_id'] = user[0]
            return redirect('/')
    else:
        return render_template('register.html')
    
@app.route("/logout")
def logout():
    session['loggedin'] = False
    session['user_id'] = None
    return redirect('/')

@app.route("/profile")
def profile():
    if not session.get('loggedin'):
        return redirect('/login')
    profile = db.execute("SELECT username FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    return render_template('profile.html', username = profile[0])
    
@app.route("/apology")
def apology():
    message = request.args.get('message', 'Something went wrong')
    return render_template('apology.html', message = message)

# ---------- Multiplayer rooms ----------
# A room is a fixed list of locations. Players who join before the host starts
# play live (same round at the same time); anyone opening the invite link later
# plays the same locations at their own pace and lands in the same ranking.

PROVINCES = ['wynn', 'gavel', 'corkus', 'ocean', 'silent-expanse']

def room_db():
    # one connection per request: the room pages poll every second
    c = sqlite3.connect('database.db', timeout=10)
    c.row_factory = sqlite3.Row
    return c

with room_db() as c:
    c.executescript('''
        CREATE TABLE IF NOT EXISTS rooms (
            code TEXT PRIMARY KEY, host_id INTEGER, provinces TEXT, rounds INTEGER,
            time_limit INTEGER, look INTEGER, locations TEXT,
            state TEXT, round INTEGER, round_start REAL);
        CREATE TABLE IF NOT EXISTS room_players (
            code TEXT, user_id INTEGER, live INTEGER, last_seen REAL, PRIMARY KEY (code, user_id));
        CREATE TABLE IF NOT EXISTS room_guesses (
            code TEXT, user_id INTEGER, round INTEGER, x REAL, z REAL, score INTEGER,
            PRIMARY KEY (code, user_id, round));
    ''')

def guess_score(x, z, loc):
    # same formula as game.js
    d = ((loc['x_position'] - x) ** 2 + (loc['z_position'] - z) ** 2) ** .5
    return max(0, round(5200 / (1 + .002 * math.e ** (.0042 * d + 3)) + .822))

def room_round_closed(c, room, n):
    # live rounds close when every live player answered or the timer ran out;
    # a player whose page stopped polling for 10 s is not waited for
    if room['state'] == 'finished' or room['round'] > n:
        return True
    if room['state'] != 'playing' or room['round'] < n:
        return False
    if room['time_limit'] > 0 and time.time() > room['round_start'] + room['time_limit']:
        return True
    waiting = c.execute('''SELECT COUNT(*) FROM room_players p WHERE code = ? AND live = 1 AND last_seen > ? AND NOT EXISTS
        (SELECT 1 FROM room_guesses g WHERE g.code = p.code AND g.user_id = p.user_id AND g.round = ?)''',
        (room['code'], time.time() - 10, n)).fetchone()[0]
    return waiting == 0

@app.route("/room/create", methods=['POST'])
def room_create():
    if not session.get('loggedin'):
        return redirect('/login')
    provinces = [p for p in request.form.getlist('province') if p in PROVINCES]
    if not provinces:
        return render_template('apology.html', message = "Please select at least one province")
    rounds = request.form.get('rounds')
    if rounds not in ['3', '5', '10', '25']:
        return render_template('apology.html', message = "Invalid number of rounds")
    time_limit = -1
    if request.form.get('time-limit-checkbox') == 'on':
        t = request.form.get('time-limit', '')
        if not t.isnumeric() or not 0 < int(t) <= 1800:
            return render_template('apology.html', message = "Time limit must be between 1 and 1800 seconds")
        time_limit = int(t)
    with room_db() as c:
        ids = [r[0] for r in c.execute(
            f"SELECT location_id FROM locations WHERE province IN ({', '.join('?' for _ in provinces)}) ORDER BY RANDOM() LIMIT ?",
            (*provinces, int(rounds)))]
        if len(ids) < int(rounds):
            return render_template('apology.html', message = "Not enough locations in these provinces")
        code = secrets.token_urlsafe(6)
        c.execute("INSERT INTO rooms VALUES (?, ?, ?, ?, ?, ?, ?, 'waiting', 0, 0)",
                  (code, session['user_id'], json.dumps(provinces), int(rounds), time_limit,
                   int(request.form.get('look') == 'on'), json.dumps(ids)))
        c.execute("INSERT INTO room_players VALUES (?, ?, 1, ?)", (code, session['user_id'], time.time()))
    return redirect('/room?code=' + code)

@app.route("/room")
def room():
    if not session.get('loggedin'):
        return redirect('/login')
    with room_db() as c:
        r = c.execute("SELECT * FROM rooms WHERE code = ?", (request.args.get('code', ''),)).fetchone()
        if not r:
            return render_template('apology.html', message = "This room does not exist")
        c.execute("INSERT OR IGNORE INTO room_players VALUES (?, ?, ?, ?)",
                  (r['code'], session['user_id'], int(r['state'] == 'waiting'), time.time()))
    return render_template('room.html', code = r['code'], rounds = r['rounds'],
                           time_limit = r['time_limit'], look = bool(r['look']))

@app.route("/api/room/<code>")
def room_state(code):
    if not session.get('loggedin'):
        return jsonify({"success": False})
    uid = session['user_id']
    with room_db() as c:
        r = c.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        me = r and c.execute("SELECT live FROM room_players WHERE code = ? AND user_id = ?", (code, uid)).fetchone()
        if not me:
            return jsonify({"success": False})
        c.execute("UPDATE room_players SET last_seen = ? WHERE code = ? AND user_id = ?", (time.time(), code, uid))
        players = c.execute('''SELECT u.username, p.live, p.user_id = ? AS you, COALESCE(SUM(g.score), 0) AS total, COUNT(g.round) AS played
            FROM room_players p JOIN users u ON u.id = p.user_id
            LEFT JOIN room_guesses g ON g.code = p.code AND g.user_id = p.user_id
            WHERE p.code = ? GROUP BY p.user_id ORDER BY total DESC''', (uid, code)).fetchall()
        # live players follow the room's round, the others pick any round they reached
        if me['live']:
            n = r['round']
        else:
            done = c.execute("SELECT COUNT(*) FROM room_guesses WHERE code = ? AND user_id = ?",
                             (code, uid)).fetchone()[0]
            n = min(done + 1, r['rounds'])
            if request.args.get('round', '').isnumeric():
                n = max(1, min(n, int(request.args['round'])))
        out = {"success": True, "state": r['state'], "host": r['host_id'] == uid, "live": bool(me['live']),
               "rounds": r['rounds'], "round": n,
               "players": [dict(p) for p in players]}
        if n > 0 and (r['state'] != 'waiting' or not me['live']):
            loc = c.execute("SELECT * FROM locations WHERE location_id = ?",
                            (json.loads(r['locations'])[n - 1],)).fetchone()
            out['url'] = loc['image_url']
            mine = c.execute("SELECT 1 FROM room_guesses WHERE code = ? AND user_id = ? AND round = ?",
                             (code, uid, n)).fetchone()
            out['answered'] = bool(mine)
            if me['live'] and r['time_limit'] > 0 and r['state'] == 'playing':
                out['time_left'] = max(0, r['round_start'] + r['time_limit'] - time.time())
            if mine and (not me['live'] or room_round_closed(c, r, n)):
                out['answer'] = {"X": loc['x_position'], "Z": loc['z_position']}
                out['guesses'] = [dict(g) for g in c.execute('''SELECT u.username, g.x, g.z, g.score
                    FROM room_guesses g JOIN users u ON u.id = g.user_id
                    WHERE g.code = ? AND g.round = ? ORDER BY g.score DESC''', (code, n))]
            elif me['live'] and r['state'] == 'playing' and room_round_closed(c, r, n):
                # timer ran out before this player guessed: count it as a 0
                c.execute("INSERT OR IGNORE INTO room_guesses VALUES (?, ?, ?, NULL, NULL, 0)", (code, uid, n))
        return jsonify(out)

@app.route("/api/room/<code>/start", methods=['POST'])
def room_start(code):
    # host only: starts the game, then moves to the next round once the current one is closed
    with room_db() as c:
        r = c.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        if not r or r['host_id'] != session.get('user_id') or r['state'] == 'finished':
            return jsonify({"success": False})
        if r['state'] == 'playing' and not room_round_closed(c, r, r['round']):
            return jsonify({"success": False})
        if r['round'] >= r['rounds']:
            c.execute("UPDATE rooms SET state = 'finished' WHERE code = ?", (code,))
        else:
            c.execute("UPDATE rooms SET state = 'playing', round = round + 1, round_start = ? WHERE code = ?",
                      (time.time(), code))
    return jsonify({"success": True})

@app.route("/api/room/<code>/guess", methods=['POST'])
def room_guess(code):
    uid = session.get('user_id')
    with room_db() as c:
        r = c.execute("SELECT * FROM rooms WHERE code = ?", (code,)).fetchone()
        me = r and c.execute("SELECT live FROM room_players WHERE code = ? AND user_id = ?", (code, uid)).fetchone()
        if not me:
            return jsonify({"success": False})
        n = int(request.form['round'])
        if me['live'] and (r['state'] != 'playing' or n != r['round'] or room_round_closed(c, r, n)):
            return jsonify({"success": False})
        done = c.execute("SELECT COUNT(*) FROM room_guesses WHERE code = ? AND user_id = ?", (code, uid)).fetchone()[0]
        if not me['live'] and (n != done + 1 or n > r['rounds']):
            return jsonify({"success": False})
        loc = c.execute("SELECT * FROM locations WHERE location_id = ?",
                        (json.loads(r['locations'])[n - 1],)).fetchone()
        if request.form.get('x'):
            x, z = float(request.form['x']), float(request.form['z'])
            score = guess_score(x, z, loc)
        else:
            x, z, score = None, None, 0  # timer ran out with no marker
        c.execute("INSERT OR IGNORE INTO room_guesses VALUES (?, ?, ?, ?, ?, ?)", (code, uid, n, x, z, score))
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)