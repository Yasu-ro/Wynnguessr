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

// the potions: name, what they do; their bottles in static/potions.png, in
// this order (tools/potions.py draws them)
var POTIONS = {
    swiftness: ['Swiftness', '20 seconds to find it, but a bigger safe zone.'],
    mining_fatigue: ['Mining Fatigue', 'No zooming on the map.'],
    wither: ['Wither', 'You lose 0.5 {heart} every 5 seconds until you guess.'],
    regeneration: ['Regeneration', 'Guess inside the safe zone to get 2 {heart} back.'],
    nausea: ['Nausea', 'The world sways.'],
    darkness: ['Darkness', 'You see the picture for 10 seconds, then it goes dark.']
};
var BOTTLES = ['swiftness', 'mining_fatigue', 'wither', 'regeneration', 'nausea', 'darkness', 'blindness'];
var THROW_MS = 1050;    // the length of static/potion-throw.gif (a temporary one: Yasuro draws the real one)
var SPLASH_MS = 560;    // when the bottle breaks in it
var DARK_AFTER = 10;    // Darkness: seconds of picture before the dark
var darkTimer = null, witherShown = null;

function potionIcon(name) {
    return "<i class='potion-icon' style='--i:" + BOTTLES.indexOf(name) + "'></i>";
}

// a heart drawn in the text, and an amount of half-hearts: 13 -> "6.5"
function heartIcon() {
    return "<i class='heart inline" + (DIFFICULTY == 'hardcore' ? ' hc' : '') + "'></i>";
}
function amount(half) {
    return String(half / 2);
}

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
    $('body').addClass('guessing');
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
    effects();
    // the server's clock: what is left of it when the round came
    deadline = Date.now() + s.time_left * 1000;
    clearInterval(clockTimer);
    clockTimer = setInterval(clock, 100);
    clock();
}

// the potion of this round, if any: its bottle in the menu, and what it does
// to the page (the server takes care of the rest: time, zone, hearts)
function effects() {
    var e = s.effect, spent = s.time - s.time_left;
    $('#sv-effect').prop('hidden', !e).html(e ? potionIcon(e) + '<span>' + POTIONS[e][0] + '</span>' : '');
    $('#game-panorama').toggleClass('nausea', e == 'nausea');
    clearTimeout(darkTimer);
    $('#sv-dark').prop('hidden', true);
    if (e == 'darkness') {
        darkTimer = setTimeout(function () { $('#sv-dark').prop('hidden', false); }, Math.max(0, DARK_AFTER - spent) * 1000);
    }
    if (e == 'mining_fatigue') {
        // no zoom at all: the map stays as it opens
        map.setMinZoom(map.getZoom()).setMaxZoom(map.getZoom());
        ['scrollWheelZoom', 'doubleClickZoom', 'touchZoom', 'boxZoom', 'keyboard'].forEach(function (h) { map[h].disable(); });
        map.zoomControl.remove();
    }
    witherShown = s.hp;
}

// Wither: the hearts the server will take, shown as they go
function wither(left) {
    if (s.effect != 'wither') {
        return;
    }
    var hp = Math.max(0, s.hp - Math.floor((s.time - left) / 5));
    if (hp != witherShown) {
        witherShown = hp;
        var el = document.getElementById('hearts');
        drawHearts(el, hp, s.max);
        replay(el, 'hurt');
        Sfx.play('hurt', 1, .6);
    }
}

// the time left; the creeper hisses for the last seconds, then the pin goes
// by itself, or the creeper explodes
function clock() {
    var left = Math.max(0, (deadline - Date.now()) / 1000);
    wither(left);
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
    clearTimeout(darkTimer);
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
    $('body').removeClass('guessing');
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
    $('#sv-effect').prop('hidden', true);
    $('#potion-throw, #potion-card').prop('hidden', true);
    if (s.potion && !over) {
        // the next round's potion: thrown right after a guess (a reload just shows it)
        $('#next-button').prop('hidden', true);
        if (before && before.phase == 'guess' && !REDUCED) {
            setTimeout(throwPotion, 900);
        } else {
            showPotion();
        }
    }
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

// the potion flies, breaks, and shows what it is; then the next round may start
function throwPotion() {
    if (s.phase != 'result') {
        return;
    }
    Sfx.play('throw');
    $('#potion-gif').attr('src', 'static/potion-throw.gif?' + Date.now());   // from its first frame
    $('#potion-throw').prop('hidden', false);
    setTimeout(function () { Sfx.play('splash'); }, SPLASH_MS);
    setTimeout(function () {
        $('#potion-throw').prop('hidden', true);
        showPotion();
    }, THROW_MS);
}

function showPotion() {
    var p = POTIONS[s.potion];
    $('#potion-card').html(potionIcon(s.potion) + '<div><b>' + p[0] + '!</b><span>' + p[1].replace(/\{heart\}/g, heartIcon()) +
        '</span></div>').prop('hidden', false);
    $('#next-button').prop('hidden', false);
}

// what happened, in words and in one sound
function verdict(r, over) {
    var lost = r.damage + r.wither, words;
    if (r.creeper) {
        words = 'Boom! No guess in time · −' + amount(lost) + ' ' + heartIcon();
    } else if (!lost) {
        words = r.heal ? 'Spot on! +' + amount(r.heal) + ' ' + heartIcon() : 'Safe!';
    } else {
        words = '−' + amount(lost) + ' ' + heartIcon() + (r.heal ? ' · +' + amount(r.heal) + ' ' + heartIcon() : '');
    }
    if (r.wither) {
        words += ' <small>(Wither: −' + amount(r.wither) + ')</small>';
    }
    if (over) {
        words = "Game over! You survived " + s.survived + (s.survived == 1 ? ' location' : ' locations');
    }
    $('#sv-verdict').html(words).toggleClass('bad', !!lost && !over).toggleClass('over', over);
    var far = Math.round(r.distance);
    var detail = r.x === null ? '' : far.toLocaleString('en-US') + (far == 1 ? ' block' : ' blocks') + ' away · +' + r.points.toLocaleString('en-US') + ' pts';
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
