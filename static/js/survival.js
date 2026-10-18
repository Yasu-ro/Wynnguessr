// Survival, solo: the run lives on the server (app.py, "Survival"). This page
// shows the round it is given, sends the guess, and draws what it cost: the
// hearts, the zone around the answer, the creeper when time runs out.

var DIFFICULTY = document.body.dataset.difficulty;
var BOUNDS = [[0, -2560], [6144, 2048]];   // the map, as in game.js and room.js
var ANSWER = '#3cb44b', MINE = '#4363d8';
var FUSE = 3;                               // seconds of hissing before the creeper explodes
var s = null;                               // the last state from the server
var viewer = null, map = null, scoreMap = null, marker = null;
var deadline = null, clockTimer = null, fused = false, sending = false;

function api(path, data) {
    return $.ajax({url: 'api/survival' + path, type: data ? 'POST' : 'GET', data: data, dataType: 'json', timeout: 10000});
}

// the hearts, as in Minecraft: max is counted in half-hearts
function drawHearts(el, hp, max) {
    var html = '', hard = DIFFICULTY == 'hardcore' ? ' hc' : '';
    for (var i = 0; i < max / 2; i++) {
        var left = hp - 2 * i;
        html += "<i class='heart " + (left >= 2 ? 'full' : left == 1 ? 'half' : 'empty') + hard + "'></i>";
    }
    el.innerHTML = html;
}

function stats() {
    $('#sv-round').text('Round ' + s.round);
    $('#sv-points').text(s.points.toLocaleString('en-US') + ' pts');
}

function show(state) {
    if (!state || !state.success) {
        // refused (an old tab, a lost connection): the server says where the
        // run stands; only without any run does a new one start
        return api('').done(function (r) { r.success ? show(r) : start(); });
    }
    var before = s;
    s = state;
    stats();
    if (s.phase == 'guess') {
        guessScreen();
    } else {
        resultScreen(before);
    }
}

function start() {
    api('/start', {difficulty: DIFFICULTY}).done(show);
}

// ---------- a round ----------

function panoramaConfig(url, options) {
    var config = url.slice(-1) == '/'
        ? {type: 'multires', multiRes: {basePath: url.slice(0, -1), path: '/%l/%s%y_%x', fallbackPath: '/fallback/%s',
            extension: 'jpg', tileResolution: 512, maxLevel: 4, cubeResolution: 4096}}
        : {type: 'equirectangular', panorama: url};
    for (var k in options) config[k] = options[k];
    return config;
}

function pin(fill, star) {
    var inside = star
        ? "<path d='M13 7l1.5 4 4.2.2-3.3 2.6 1.1 4.1L13 15.5l-3.5 2.4 1.1-4.1-3.3-2.6 4.2-.2z' fill='white'/>"
        : "<circle cx='13' cy='13' r='4.5' fill='white'/>";
    return L.divIcon({
        className: 'room-pin',
        html: "<svg width='26' height='40' viewBox='0 0 26 40'><path d='M13 1.5C6.6 1.5 1.5 6.6 1.5 13c0 8.6 11.5 25 11.5 25s11.5-16.4 11.5-25C24.5 6.6 19.4 1.5 13 1.5z' fill='" + fill + "' stroke='black' stroke-width='2.5'/>" + inside + "</svg>",
        iconSize: [26, 40],
        iconAnchor: [13, 39]
    });
}

function makeMap(id, zoom) {
    var m = L.map(id, {crs: L.CRS.Simple, minZoom: -3, maxZoom: 5});
    L.imageOverlay('static/map-2026.webp', BOUNDS, {attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'}).addTo(m);
    m.setView([3072, -256], zoom);
    m.on('zoomend', function () { m.getContainer().classList.toggle('crisp', m.getZoom() > 0); });
    return m;
}

function guessScreen() {
    $('#score-screen').prop('hidden', true);
    $('#guess-screen').prop('hidden', false);
    drawHearts(document.getElementById('hearts'), s.hp, s.max);
    marker = null;
    fused = false;
    sending = false;
    $('#guess-button').prop('disabled', false).removeClass('room-warn').text('Guess!');
    if (viewer) {
        viewer.destroy();
    }
    viewer = pannellum.viewer('game-panorama', panoramaConfig(s.url, {autoLoad: true}));
    if (map) {
        map.remove();
    }
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
        marker = L.marker(blockSpot(b.x, b.z), {icon: pin(MINE)}).addTo(map);
        drop(marker);
        Sfx.play('pin');
        $('#guess-button').removeClass('room-warn').text('Guess!');
    });
    // the server's clock: what is left of it when the round came
    deadline = Date.now() + s.time_left * 1000;
    clearInterval(clockTimer);
    clockTimer = setInterval(clock, 100);
    clock();
}

// the time left; the creeper hisses for the last seconds, then the pin goes
// by itself, or the creeper explodes
function clock() {
    var left = Math.max(0, (deadline - Date.now()) / 1000);
    $('#sv-time').prop('hidden', false).html("<i class='material-icons'>timer</i>" + Math.ceil(left) + ' s')
        .toggleClass('urgent', left <= 10);
    if (left <= FUSE && !fused && !sending) {
        fused = true;
        Sfx.play('fuse');
    }
    if (left <= 0) {
        clearInterval(clockTimer);
        send(true);
    }
}

$('#guess-button').on('click', function () {
    if (!marker) {
        $(this).addClass('room-warn').text('Select a location first!');
        return;
    }
    send(false);
});

function send(auto) {
    if (sending || !s || s.phase != 'guess') {
        return;
    }
    sending = true;
    clearInterval(clockTimer);
    var data = {round: s.round};
    if (marker) {
        var b = blockAt(marker.getLatLng());
        data.x = b.x;
        data.z = b.z;
        Sfx.play('guess');
    }
    $('#guess-button').prop('disabled', true).text('...');
    api('/guess', data).done(function (r) {
        if (r.success && r.result && r.result.creeper) {
            explode();
            setTimeout(function () { show(r); }, 650);
        } else {
            show(r);
        }
    }).fail(function () {
        // the server keeps the round: ask it where things stand
        sending = false;
        api('').done(show);
    });
}

// the creeper: a flash, the screen shakes, the bang
function explode() {
    Sfx.play('boom');
    var flash = document.createElement('div');
    flash.className = 'boom';
    document.body.appendChild(flash);
    replay(document.getElementById('guess-screen'), 'shake');
    setTimeout(function () { flash.remove(); }, 900);
}

// ---------- what the guess cost ----------

function resultScreen(before) {
    var r = s.result;
    $('#sv-time').prop('hidden', true);
    $('#guess-screen').prop('hidden', true);
    $('#score-screen').prop('hidden', false);
    if (viewer) {
        viewer.destroy();
        viewer = null;
    }
    var hearts = document.getElementById('hearts-result');
    drawHearts(hearts, s.hp, s.max);
    if (r && (r.damage || r.wither)) {
        replay(hearts, 'hurt');
    }
    if (scoreMap) {
        scoreMap.remove();
    }
    scoreMap = makeMap('scoreMap', -1);
    var over = s.phase == 'over';
    if (r) {
        var answer = blockSpot(r.X, r.Z);
        // the zone around the answer: green, no damage; yellow, damage; red, death
        L.circle(answer, {radius: r.kill || r.far, color: '#c9a227', weight: 2, fillColor: '#ffd75e', fillOpacity: .14, interactive: false}).addTo(scoreMap);
        if (r.kill) {
            // drawn over the yellow edge, which it is
            L.circle(answer, {radius: r.kill, color: '#b3302a', weight: 3, dashArray: '10 6', fill: false, interactive: false}).addTo(scoreMap);
        }
        L.circle(answer, {radius: r.safe, color: '#2f7a22', weight: 2, fillColor: '#88cc42', fillOpacity: .22, interactive: false}).addTo(scoreMap);
        drop(L.marker(answer, {icon: pin(ANSWER, true), zIndexOffset: 1000}).addTo(scoreMap), true);
        var spots = [answer, L.latLng(answer.lat + r.safe, answer.lng + r.safe), L.latLng(answer.lat - r.safe, answer.lng - r.safe)];
        if (r.x !== null) {
            var mine = blockSpot(r.x, r.z);
            drop(L.marker(mine, {icon: pin(MINE)}).addTo(scoreMap), true);
            drawLine(L.polyline([answer, answer], {color: MINE, weight: 3, dashArray: '8 6'}).addTo(scoreMap), answer, mine, 300);
            spots.push(mine);
        }
        scoreMap.fitBounds(L.latLngBounds(spots), {padding: [50, 50], maxZoom: 2});
        verdict(r, over);
    }
    $('#next-button').prop('hidden', over).prop('disabled', false);
    $('#again-button, #menu-button').prop('hidden', !over);
    var slot = document.getElementById('xp-slot');
    slot.innerHTML = '';
    if (over) {
        if (s.xp !== undefined) {
            xpGain(slot, s.xp, s.gained);
        } else if (s.pending) {
            slot.innerHTML = "<p class='xp-note'><a href='login?next=profile'>Log in</a> or <a href='register?next=profile'>make an account</a> to save this run and earn XP.</p>";
        }
    }
}

// what happened, in words and in one sound
function verdict(r, over) {
    var lost = r.damage + r.wither, words;
    if (r.creeper) {
        words = 'Boom! No guess in time';
    } else if (!lost) {
        words = r.heal ? 'Spot on! Half a heart back' : 'Safe!';
    } else {
        words = '−' + hearts(lost);
    }
    if (r.wither) {
        words += ' · Wither: −' + hearts(r.wither);
    }
    if (over) {
        words = "Game over! You survived " + s.survived + (s.survived == 1 ? ' location' : ' locations');
    }
    $('#sv-verdict').text(words).toggleClass('bad', !!lost && !over).toggleClass('over', over);
    var detail = r.x === null ? '' : Math.round(r.distance).toLocaleString('en-US') + ' blocks away · +' + r.points.toLocaleString('en-US') + ' pts';
    if (over) {
        detail = s.points.toLocaleString('en-US') + ' points';
    }
    $('#sv-detail').text(detail);
    if (over) {
        Sfx.play('lose');
    } else if (!r.creeper) {
        Sfx.play(lost ? 'hurt' : r.heal ? 'perfect' : 'good');
    }
}

// half-hearts, in words: 3 -> "1½ hearts"
function hearts(half) {
    var whole = Math.floor(half / 2), text = (whole ? whole : '') + (half % 2 ? '½' : '');
    return text + (half > 2 ? ' hearts' : ' heart');
}

$('#next-button').on('click', function () {
    $(this).prop('disabled', true);
    api('/next', {round: s.round}).done(show).fail(function () { api('').done(show); });
});

$('#again-button').on('click', function () {
    $(this).prop('disabled', true);
    start();
});

// a run in progress at this difficulty goes on (a reload brings back the same
// round and its clock); otherwise a new one starts
api('').done(function (r) {
    if (r.success && r.phase != 'over' && r.difficulty == DIFFICULTY) {
        show(r);
    } else {
        start();
    }
}).fail(start);
