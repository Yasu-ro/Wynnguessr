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

// the potions, the hearts and the throw: potions.js
var HARDCORE = DIFFICULTY == 'hardcore';
var TEST = document.body.dataset.test == '1';   // the beta's test panel (reviewers only, runs off the leaderboard)
// the milk: a bucket cancels the potion thrown with a result (2 a run).
// Drunk as in Minecraft: 1.6 s, a gulp every 0.2 s from the 0.4th on
var DRINK_MS = 1600;
var GULPS = [400, 600, 800, 1000, 1200, 1400, 1600];
var darkTimer = null, witherShown = null;

function api(path, data) {
    return $.ajax({url: 'api/survival' + path, type: data ? 'POST' : 'GET', data: data, dataType: 'json', timeout: 10000});
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
    api('/start', {difficulty: DIFFICULTY, test: TEST ? 1 : 0}).done(show);
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
    drawHearts(document.getElementById('hearts'), s.hp, s.max, HARDCORE);
    marker = null;
    fused = false;
    sending = false;
    $('#guess-button').prop('disabled', false).removeClass('room-warn').text('Guess!');
    if (viewer) {
        viewer.destroy();
    }
    var view = {autoLoad: true};
    if (s.effect == 'nausea') {
        // Nausea: the view turns by itself, and the player cannot hold it (the
        // server shakes the pin); Pannellum turns it, no costly CSS motion
        view = {autoLoad: true, autoRotate: NAUSEA_SPIN, draggable: false, mouseZoom: false, keyboardZoom: false,
                disableKeyboardCtrl: true, showControls: false};
    }
    viewer = pannellum.viewer('game-panorama', panoramaConfig(s.url, view));
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
    var hp = Math.max(0, s.hp - Math.floor((s.time - left) / WITHER_EVERY));
    if (hp != witherShown) {
        witherShown = hp;
        var el = document.getElementById('hearts');
        drawHearts(el, hp, s.max, HARDCORE);
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
    drawHearts(hearts, s.hp, s.max, HARDCORE);
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
        if (r.aim_x !== null && r.aim_x !== undefined) {
            // Nausea: where the pin was aimed, before it landed off
            var aimed = blockSpot(r.aim_x, r.aim_z);
            L.circleMarker(aimed, {radius: 6, color: '#3f2724', weight: 2, fillColor: '#ffffff', fillOpacity: .8, interactive: false}).addTo(scoreMap);
            if (r.x !== null) {
                L.polyline([aimed, blockSpot(r.x, r.z)], {color: '#3f2724', weight: 2, dashArray: '2 5', interactive: false}).addTo(scoreMap);
            }
            spots.push(aimed);
        }
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
    if (s.milked && !s.potion && !over) {
        showMilked();   // a reload after the milk
    }
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
// (no picture: the potion at once, never a game stuck without its button)
function throwPotion() {
    if (s.phase == 'result') {
        throwAnimation(showPotion);
    }
}

function showPotion() {
    var p = POTIONS[s.potion];
    $('#potion-card').html(potionIcon(s.potion) + '<div><b>' + p[0] + '!</b><span>' + potionText(s.potion, HARDCORE) +
        '</span>' + (s.milk ? "<button type='button' class='btn wood milk-button' id='milk-button'><i class='bucket-icon'></i>Drink Milk<small>" +
        s.milk + ' left</small></button>' : '') + '</div>').prop('hidden', false);
    replay(document.getElementById('potion-card'));
    $('#next-button').prop('hidden', false);
}

// the potion, gone: what the bucket left
function showMilked() {
    $('#potion-card').html("<i class='bucket-icon empty'></i><div><b>Milk!</b><span>No more " + POTIONS[s.milked][0] +
        '.</span></div>').prop('hidden', false);
    replay(document.getElementById('potion-card'));
    $('#next-button').prop('hidden', false);
}

// the bucket goes up and gulps, as in Minecraft; the card changes once it is
// empty. Next waits only for the server's answer, not for the drinking
$('#potion-card').on('click', '#milk-button', function () {
    var button = $(this).prop('disabled', true), round = s.round, answer = null, drunk = false;
    $('#next-button').prop('disabled', true);
    button.find('.bucket-icon').addClass('drinking');
    GULPS.forEach(function (t) {
        setTimeout(function () {
            if (s.round == round && s.phase == 'result') {
                Sfx.play('drink', .9 + Math.random() * .1);
            }
        }, t);
    });
    var done = function () {
        if (!drunk || !answer || s.round != round || s.phase != 'result') {
            return;
        }
        if (answer.success) {
            s = answer;
            showMilked();
        } else {
            api('').done(show);
        }
    };
    setTimeout(function () { drunk = true; done(); }, DRINK_MS);
    api('/milk', {round: round}).done(function (r) { answer = r; }).fail(function () { answer = {success: false}; })
        .always(function () { $('#next-button').prop('disabled', false); done(); });
});

// what happened, in words and in one sound
function verdict(r, over) {
    var lost = r.damage + r.wither, words;
    if (r.creeper) {
        words = 'Boom! No guess in time · −' + amount(lost) + ' ' + heartIcon(HARDCORE);
    } else if (!lost) {
        words = r.heal ? 'Spot on! +' + amount(r.heal) + ' ' + heartIcon(HARDCORE) : 'Safe!';
    } else {
        words = '−' + amount(lost) + ' ' + heartIcon(HARDCORE) + (r.heal ? ' · +' + amount(r.heal) + ' ' + heartIcon(HARDCORE) : '');
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
    if (r.success && r.phase != 'over' && r.difficulty == DIFFICULTY && r.test == TEST) {
        show(r);
    } else {
        start();
    }
}).fail(start);

// ---------- the beta's test panel ----------
// any potion now (or for the next round, from a result), the hearts, the
// round (to feel the zone of round 20), the creeper in 4 seconds

if (TEST) {
    if (window.innerWidth < 700) {
        document.getElementById('test-panel').open = false;   // folded on a phone: it would hide the picture
    }
    $('#t-potion').html("<option value=''>None</option>" + Object.keys(POTIONS).map(function (k) {
        return "<option value='" + k + "'>" + POTIONS[k][0] + '</option>';
    }).join(''));
    var test = function (data) {
        api('/test', data).done(function (r) {
            if (r.success) {
                s = null;   // what follows is drawn as a fresh screen, not as the answer to a guess
                show(r);
            }
        });
    };
    $('#test-panel').on('click', '[data-t]', function () {
        var what = $(this).data('t');
        if (what == 'potion') {
            test({'do': 'potion', potion: $('#t-potion').val()});
        } else if (what == 'hearts') {
            test({'do': 'hearts', hp: Math.round(parseFloat($('#t-hp').val()) * 2)});
        } else if (what == 'milk') {
            test({'do': 'milk'});
        } else if (what == 'round') {
            test({'do': 'round', round: $('#t-round').val()});
        } else {
            test({'do': 'creeper'});
        }
    });
}
