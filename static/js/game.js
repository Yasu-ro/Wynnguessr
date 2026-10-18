// The Classic game alone. It is played on the server (app.py, "Solo"): this
// page shows the round it is given, sends the guess, and draws the answer and
// the points it is told. It never knows where a location is before its guess.

var vars = $('#game-variables');
var settings = {
    province: JSON.parse(vars.attr('provinces').replace(/'/g, '"')),
    rounds: vars.attr('rounds'),
    time_limit: vars.attr('timeLimit') > 0 ? vars.attr('timeLimit') : -1,
    look: vars.attr('look') == 'True'
};
var s = null;            // the last state from the server
var map, scoreMap, viewer = null, marker = null;
var timer = null, deadline = null, sending = false;
var greenIcon = new L.Icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});
var BOUNDS = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block

// leaving before the end of the game asks first
window.addEventListener('beforeunload', function (e) {
    if (s && s.phase != 'over') {
        e.preventDefault();
        e.returnValue = '';
    }
});

function api(path, data) {
    return $.ajax({url: 'api/solo' + path, type: data ? 'POST' : 'GET', data: data, dataType: 'json', timeout: 10000, traditional: true});
}

// a game in progress with these settings goes on (a reload brings back the
// same round); otherwise a new one starts
$(document).ready(function () {
    api('').done(function (r) {
        if (r.success && r.phase != 'over' && String(r.rounds) == settings.rounds && r.look == settings.look &&
                (r.time_limit > 0 ? String(r.time_limit) : '-1') == String(settings.time_limit) &&
                r.provinces.join() == settings.province.join()) {
            show(r);
        } else {
            start();
        }
    }).fail(start);
});

function start() {
    api('/start', settings).done(function (r) {
        if (!r.success) {
            location.href = 'apology?message=' + encodeURIComponent(r.error || 'This game could not start');
            return;
        }
        show(r);
    });
}

function show(state) {
    if (!state || !state.success) {
        // refused (an old tab, a lost connection): ask where the game stands
        return api('').done(function (r) { r.success ? show(r) : start(); });
    }
    var before = s;
    s = state;
    document.getElementById('totalScore').innerHTML = "Score: " + s.score;
    if (s.phase == 'guess') {
        showNextLocation();
    } else if (s.phase == 'result' || (before && before.phase == 'guess')) {
        // the last round too has its score screen; then the results
        showScoreScreen();
    } else {
        finalScore();
    }
}

// same formula as guess_score() in app.py: the right block, or within PERFECT
// blocks of it, is a perfect 5,000
var PERFECT = 2;

function makeMap(id, zoom) {
    var m = L.map(id, {crs: L.CRS.Simple, minZoom: -3, maxZoom: 5, attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'});
    mapTiles(m);
    m.setView([3072, -256], zoom);
    crisp(m);
    return m;
}

function showNextLocation() {
    showContent('guess-screen');
    if (s.round > 1) {
        Sfx.play('round');
    }
    sending = false;
    marker = null;
    document.getElementById('guess-screen').innerHTML =
    "<div id='game-panorama'></div>" +
    "<div class='map-container' id='map-container'>" +
        "<div class='map' id='map'></div>" +
        "<button id='guess-button' class='guess-button' type='submit'>Guess!</button></div>";

    map = makeMap('map', -2);
    blockCursor(map);
    map.on('click', function (e) {
        if (sending) {
            return;
        }
        if (marker) {
            map.removeLayer(marker);
        }
        var b = blockAt(e.latlng);
        marker = L.marker(blockSpot(b.x, b.z)).addTo(map);
        drop(marker);
        Sfx.play('pin');
    });

    document.getElementById('guess-button').onclick = function () {
        if (!marker) {
            document.getElementById('guess-button').innerHTML = "Select a location first!";
            document.getElementById('guess-button').style.backgroundColor = "red";
            return;
        }
        Sfx.play('guess');
        send();
    };

    var locked = s.look;
    if (viewer) {
        viewer.destroy();
    }
    viewer = pannellum.viewer('game-panorama', panoramaConfig(s.url, {
        "autoLoad": true,
        "draggable": !locked,
        "mouseZoom": !locked,
        "keyboardZoom": !locked,
        "disableKeyboardCtrl": locked,
        "showControls": !locked
    }));
    document.getElementById('round-number').innerHTML = "Round: " + s.round + "/" + s.rounds;

    // the server's clock, when there is one; the last seconds out loud, as in rooms
    clearInterval(timer);
    if (s.time_left !== undefined) {
        deadline = Date.now() + s.time_left * 1000;
        var lastSecond = null;
        timer = setInterval(function () {
            var left = Math.max(0, (deadline - Date.now()) / 1000), second = Math.ceil(left);
            if (second != lastSecond && left > 0) {
                if (second == 10 || second == 5) {
                    Sfx.play('warn');
                } else if (second <= 3) {
                    Sfx.play('tick', [1.5, 1.26, 1.06][second - 1]);
                }
            }
            lastSecond = second;
            document.getElementById('time-left').innerHTML = "Time: " + left.toFixed(1);
            if (left <= 0) {
                clearInterval(timer);
                send();
            }
        }, 100);
    }
}

function send() {
    if (sending || !s || s.phase != 'guess') {
        return;
    }
    sending = true;
    clearInterval(timer);
    var data = {round: s.round};
    if (marker) {
        var b = blockAt(marker.getLatLng());
        data.x = b.x;
        data.z = b.z;
    }
    api('/guess', data).done(show).fail(function () {
        sending = false;
        api('').done(show);
    });
}

// Display the score screen
function showScoreScreen() {
    var r = s.result;
    showContent('score-screen');
    document.getElementById('score-screen').innerHTML =
        "<div class = 'score-map' id='scoreMap'></div>" +
        "<div id = 'score-container'>" +
        "<p id='score' class='score-info'></p>" +
        "<div class = 'progress-bar'>" +
        "<div class = 'progress' id = 'progress'></div></div>" +
        "<p id='distance' class='score-info'></p>" +
        "<button id='next-button' class='next-button'>Next Location</button></div>";
    document.getElementById('guess-screen').innerHTML = "";
    if (viewer) {
        viewer.destroy();
        viewer = null;
    }
    scoreMap = makeMap('scoreMap', -1);
    var button = document.getElementById('next-button');
    if (s.phase == 'over') {
        button.innerHTML = "See Results";
        button.onclick = finalScore;
    } else {
        button.onclick = next;
    }
    var actual = blockSpot(r.X, r.Z);
    if (r.x === null) {
        document.getElementById('score').innerHTML = "No location selected!";
        document.getElementById('progress').style.width = "0%";
        document.getElementById('distance').innerHTML = "Distance: 0 blocks away!";
        Sfx.play('bad');
        drop(L.marker(actual, { icon: greenIcon }).addTo(scoreMap), true);
        scoreMap.fitBounds(L.latLngBounds([actual]));
        return;
    }
    document.getElementById('distance').innerHTML = "Distance: " + r.distance.toFixed(2) + " blocks away!";
    document.getElementById('progress').style.width = (r.score / 5000) * 100 + "%";
    // the points count up, then one sound says how it went
    var verdict = r.score >= 4950 ? 'perfect' : r.score >= 4000 ? 'good' : r.score <= 1500 ? 'bad' : null;
    countUp(document.getElementById('score'), r.score, verdict);
    // the answer lands, then the line runs from it to your guess
    var guessed = blockSpot(r.x, r.z);
    drop(L.marker(actual, { icon: greenIcon }).addTo(scoreMap), true);
    drop(L.marker(guessed).addTo(scoreMap), true);
    drawLine(L.polyline([actual, actual], { color: 'red' }).addTo(scoreMap), actual, guessed, 300);
    scoreMap.fitBounds(L.latLngBounds([actual, guessed]));
}

function next() {
    $('#next-button').prop('disabled', true);
    api('/next', {round: s.round}).done(show).fail(function () { api('').done(show); });
}

// the points of a round, counted up with a tick now and then (the same as in rooms)
function countUp(el, points, verdict) {
    var from = Date.now(), tick = 0;
    var step = function () {
        if (!document.body.contains(el)) {
            return;
        }
        var t = Math.min(1, (Date.now() - from) / 900);
        el.innerHTML = Math.round(points * t) + " points!";
        if (t < 1) {
            if (Date.now() - tick > 140) {
                tick = Date.now();
                Sfx.play('tick', 0.8 + t * 0.7, 0.5);
            }
            requestAnimationFrame(step);
            return;
        }
        if (verdict == 'perfect') {
            // as in rooms: "Bullseye!" stamps once the points are counted
            el.innerHTML = "Bullseye! " + points + " points!";
            replay(el, 'stamp');
        }
        if (verdict) {
            Sfx.play(verdict);
        }
    };
    step();
}

function showContent(contentId){
    document.getElementById('guess-screen').style.display = "none";
    document.getElementById('score-screen').style.display = "none";
    document.getElementById(contentId).style.display = contentId == 'score-screen' ? "flex" : "block";
}

// the end screen: every round on the map, the total, the time, and the XP
// (without an account the game waits in the session for a login)
function finalScore() {
    showContent('score-screen');
    document.getElementById('score-screen').innerHTML =
        "<div class = 'score-map' id='scoreMap'></div>" +
        "<div id = 'score-container'>" +
        "<p id='Finish Message' class='score-info'></p>" +
        "<div class = 'progress-bar'>" +
        "<div class = 'progress' id = 'progress'></div></div>" +
        "<p id='score' class='score-info'></p>" +
        "<div id='xp-slot' class='xp-slot'></div>" +
        "<button id='next-button' class='next-button'>Play Again!</button></div>";
    document.getElementById('guess-screen').innerHTML = "";
    if (viewer) {
        viewer.destroy();
        viewer = null;
    }
    var slot = document.getElementById('xp-slot');
    if (s.pending) {
        slot.innerHTML = "<p class='xp-note'><a href='login?next=profile'>Log in</a> or <a href='register?next=profile'>make an account</a> " +
            "to save this score and earn XP.</p>";
    } else if (s.xp !== undefined) {
        xpGain(slot, s.xp, s.gained);
    }
    scoreMap = makeMap('scoreMap', -1);
    var spots = [];
    s.history.forEach(function (g) {
        var actual = blockSpot(g.X, g.Z);
        L.marker(actual, { icon: greenIcon }).addTo(scoreMap);
        spots.push(actual);
        if (g.x !== null) {
            var guessed = blockSpot(g.x, g.z);
            L.marker(guessed).addTo(scoreMap);
            L.polyline([actual, guessed], { color: 'red' }).addTo(scoreMap);
            spots.push(guessed);
        }
    });
    scoreMap.fitBounds(L.latLngBounds(spots));
    var time = s.time;
    var hours = Math.floor(time / 3600), minutes = Math.floor((time % 3600) / 60), seconds = Math.floor(time % 60);
    var timeString = (hours > 0 ? hours + 'h ' : '') + (minutes > 0 ? minutes + 'm ' : '') + (seconds > 0 ? seconds + 's ' : '') +
        Math.round(time % 1 * 1000) + 'ms';
    document.getElementById('Finish Message').innerHTML = "Game Finished! Total Time: " + timeString;
    document.getElementById('score').innerHTML = "Final Score: " + s.score + "/" + s.rounds * 5000;
    document.getElementById('progress').style.width = (s.score / (s.rounds * 5000)) * 100 + "%";
    $('#next-button').click(function () {
        $(this).prop('disabled', true);
        start();
    });
}

// zoomed past 1 px per block, show blocks instead of a blur
function crisp(m) {
    m.on('zoomend', function () { m.getContainer().classList.toggle('crisp', m.getZoom() > 0); });
    m.getContainer().classList.toggle('crisp', m.getZoom() > 0);
}

// a location is one equirectangular image, or (URL ending with "/") a folder
// of multires tiles cut by the server (see make_tiles in app.py)
function panoramaConfig(url, options) {
    var config = url.slice(-1) == '/'
        ? {type: 'multires', multiRes: {basePath: url.slice(0, -1), path: '/%l/%s%y_%x', fallbackPath: '/fallback/%s',
            extension: 'webp', tileResolution: 512, maxLevel: 4, cubeResolution: 4096}}
        : {type: 'equirectangular', panorama: url};
    for (var k in options) config[k] = options[k];
    return config;
}
