// Multiplayer room. The server runs the game (rounds, timers, scores); this
// page asks it for the state every second and redraws a screen only when the
// screen changes.
var code = $('#room').attr('data-code');
var COLORS = ['#e6194b', '#4363d8', '#ffe119', '#911eb4', '#f58231', '#42d4f4', '#f032e6', '#9a6324'];
var ANSWER = '#3cb44b';
var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
var s = null;            // last state received
var view = '';           // screen on display, e.g. "guess3"
var cur = 0;             // round shown to a player who is not playing live
var finished = false;    // that player asked for the results
var settingsKey = null;  // settings shown in the lobby
var pending = 0;         // settings changes on their way to the server
var map = null, revealMap = null, viewer = null, marker = null;
var submitted = false;
var deadline = null;     // when the round closes, local clock
var shownAt = 0;         // when the round appeared, local clock
var nextAt = null;       // when the next round starts by itself, local clock
var polling = false, pollAgain = false, pollTimer = null;
var heard = null;        // players already known to have guessed this round
var lastSecond = null;   // last whole second of the clock shown
var seenNames = null;    // players already known, to tell who comes in
var seenHost = null;     // who held the room at the last look

$(document).ready(function () {
    setNav();
    poll();
    setInterval(clocks, 200);
});
$(window).on('resize', setNav);

// leaving in the middle of a game (closing the tab, a menu link, back, reload)
// asks first; the page's own moves (next room, reload on error) do not
var leaving = false;
window.addEventListener('beforeunload', function (e) {
    if (!leaving && (view.indexOf('guess') == 0 || view.indexOf('reveal') == 0 || view.indexOf('shop') == 0)) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// ---------- server ----------

function poll() {
    clearTimeout(pollTimer);
    if (polling) {
        pollAgain = true;
        return;
    }
    polling = true;
    $.ajax({url: 'api/room/' + code, data: cur ? {round: cur, chat: chatId} : {chat: chatId}, dataType: 'json', timeout: 8000})
        .always(function (data) {
            polling = false;
            try {
                if (data && typeof data.success == 'boolean') {
                    render(data);
                }
            } catch (e) {
                console.error(e);
            }
            pollTimer = setTimeout(poll, pollAgain ? 0 : 1000);
            pollAgain = false;
        });
}

// During the reveal the next picture loads in the background: the browser
// keeps it, so the round starts for everyone with the picture already there.
// Multires: the tiles of levels 1 to 3 (what a first look needs, ~130
// tiles); the sharpest level only loads when zooming. Same crossOrigin as
// Pannellum, or the browser would not reuse them.
var preloaded = null, preloads = [];
function preload(url) {
    if (url == preloaded) return;
    preloaded = url;
    preloads = [];
    var load = function (src) {
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.src = src;
        preloads.push(img);
    };
    if (url.slice(-1) != '/') {
        load(url);
        return;
    }
    for (var level = 1; level <= 3; level++) {
        var n = 1 << (level - 1);
        'fbudlr'.split('').forEach(function (face) {
            for (var i = 0; i < n; i++) for (var j = 0; j < n; j++) load(url + level + '/' + face + i + '_' + j + '.jpg');
        });
    }
}

function send(action, data) {
    var req = $.ajax({url: 'api/room/' + code + '/' + action, type: 'POST', data: data, dataType: 'json', timeout: 8000});
    req.always(poll);
    return req;
}

function render(data) {
    if (!data.success) {
        // logged out, or the room is gone: the page itself will say which
        leaving = true;
        location.reload();
        return;
    }
    s = data;
    if (s.next_url) preload(s.next_url);
    chat(s.chat);
    arrivals();
    if (s.next && s.live && s.state == 'finished') {
        leaving = true;
        location.href = 'room?code=' + s.next;
        return;
    }
    if (!s.live && !cur) {
        cur = s.round;
    }
    if (s.live && s.state == 'waiting') {
        lobby();
    } else if (s.live ? s.state == 'finished' : finished) {
        results();
    } else if (s.phase == 'shop') {
        shop();
    } else if (s.reveal) {
        reveal();
    } else {
        guess();
    }
}

// who came in (a door in the lobby, a toast everywhere: several at once make
// one toast) and who holds the room now (not on the first look)
function arrivals() {
    var names = s.players.map(function (p) { return p.name; });
    var host = s.players.filter(function (p) { return p.host; })[0];
    if (seenNames) {
        var come = names.filter(function (n) { return seenNames.indexOf(n) < 0; });
        if (come.length) {
            if (s.live && s.state == 'waiting') {
                Sfx.play('join');
            }
            var old = document.querySelector('[data-group="join"]:not(.out)');
            var all = (old && old.names || []).concat(come);
            toast(esc(all[0]) + (all.length > 1 ? ' and ' + (all.length - 1) + ' more' : '') + ' joined',
                  toastIcon('person_add'), 'join').names = all;
        }
        if (host && host.name != seenHost) {
            Sfx.play('toast');
            toast(host.you ? 'You are now the host' : esc(host.name) + ' is now the host', toastIcon('star'));
        }
    }
    seenNames = names;
    seenHost = host ? host.name : null;
}

// ---------- helpers ----------

function setNav() {
    document.documentElement.style.setProperty('--nav', $('.navbar').outerHeight() + 'px');
}

function show(id) {
    ['lobby', 'guess-screen', 'reveal-screen', 'shop-screen', 'results'].forEach(function (x) {
        $('#' + x).prop('hidden', x != id);
    });
    var playing = id == 'guess-screen' || id == 'reveal-screen';
    $('body').toggleClass('room-playing', playing);
    // one chat, moved where it belongs: under the players, over the panorama,
    // in the side panel of a reveal (never over the map), under the results
    var slot = {'guess-screen': '#chat-slot-game', 'reveal-screen': '#chat-slot-reveal', 'shop-screen': '#chat-slot-shop',
                'results': '#chat-slot-results'}[id] || '#chat-slot-lobby';
    if (!$('#room-chat').parent().is(slot)) {
        // on a phone the panorama is small: the chat starts folded over it
        $('#room-chat').appendTo(slot).toggleClass('folded', id == 'guess-screen' && window.innerWidth <= 800);
    }
    $('#chat-slot-game').prop('hidden', id != 'guess-screen');
    chatPlace();
    if (playing) {
        window.scrollTo(0, 0);
    }
    setNav();
}

function esc(text) {
    return $('<div>').text(text).html();
}

function me() {
    return s.players.filter(function (p) { return p.you; })[0];
}

function player(name) {
    return s.players.filter(function (p) { return p.name == name; })[0];
}

function color(p) {
    return COLORS[p.color % COLORS.length];
}

function dot(p) {
    return "<span class='room-dot' style='background-color:" + color(p) + "'></span>";
}

function points(n) {
    return n.toLocaleString('en-US') + ' pts';
}

function clock(seconds) {
    seconds = Math.ceil(seconds);
    return Math.floor(seconds / 60) + ':' + ('0' + seconds % 60).slice(-2);
}

// map pin in a player's colour; the answer gets a star
function pin(fill, star) {
    var inside = star
        ? "<path d='M13 7l1.5 4 4.2.2-3.3 2.6 1.1 4.1L13 15.5l-3.5 2.4 1.1-4.1-3.3-2.6 4.2-.2z' fill='white'/>"
        : "<circle cx='13' cy='13' r='4.5' fill='white'/>";
    return L.divIcon({
        className: 'room-pin',
        html: "<svg width='26' height='40' viewBox='0 0 26 40'><path d='M13 1.5C6.6 1.5 1.5 6.6 1.5 13c0 8.6 11.5 25 11.5 25s11.5-16.4 11.5-25C24.5 6.6 19.4 1.5 13 1.5z' fill='" + fill + "' stroke='black' stroke-width='2.5'/>" + inside + "</svg>",
        iconSize: [26, 40],
        iconAnchor: [13, 39],
        tooltipAnchor: [0, -36]
    });
}

function makeMap(id, zoom) {
    var m = L.map(id, {crs: L.CRS.Simple, minZoom: -3, maxZoom: 5});
    L.imageOverlay('static/map-2026.webp', bounds, {attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'}).addTo(m);
    crisp(m);
    m.setView([3072, -256], zoom);
    return m;
}

function inviteLink() {
    return location.href.split(/[?#]/)[0] + '?code=' + code;
}

function copy(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }
    return new Promise(function (ok, ko) {
        var area = $('<textarea>').val(text).css({position: 'fixed', opacity: 0}).appendTo('body');
        area[0].select();
        try {
            document.execCommand('copy') ? ok() : ko();
        } catch (e) {
            ko();
        }
        area.remove();
    });
}

$(document).on('click', '[data-copy]', function (e) {
    e.preventDefault();
    var el = $(this), link = inviteLink();
    if (!el.data('label')) {
        el.data('label', el.text());
    }
    copy(link).then(function () {
        el.text('Copied!');
        setTimeout(function () { el.text(el.data('label')); }, 1500);
    }, function () {
        window.prompt('Copy this link:', link);
    });
});

// ---------- chat ----------

var chatId = 0;          // last message shown
var unread = 0;          // messages that came while the chat was folded
// where the player left the chat: following the newest message, or scrolled
// up to read. Kept here because the chat moves from screen to screen, and a
// moved (or folded) list forgets its scroll and jumps back to the top
var chatStick = true, chatTop = 0;

$('#chat-log').on('scroll', function () {
    if (this.clientHeight) {
        chatStick = this.scrollHeight - this.scrollTop - this.clientHeight < 30;
        chatTop = this.scrollTop;
    }
});

function chatPlace() {
    var log = $('#chat-log')[0];
    log.scrollTop = chatStick ? log.scrollHeight : chatTop;
}

var bubbleAt = 0;         // the last chat sound: one every 2 seconds at most
var chatSeen = false;     // the messages already there when the page opened make no sound

function chat(messages) {
    var log = $('#chat-log'), theirs = false;
    (messages || []).forEach(function (m) {
        if (m.id <= chatId) {
            return;
        }
        chatId = m.id;
        log.append("<p>" + dot(m) + "<b>" + esc(m.name) + "</b><span>" + esc(m.text) + "</span></p>");
        theirs = theirs || m.name != me().name;
        if ($('#room-chat').hasClass('folded') && m.name != me().name) {
            unread++;
        }
    });
    log.children().slice(0, -100).remove();
    // follow the conversation, unless the player scrolled up to read
    chatPlace();
    // someone else wrote (not the messages already there when the page opened)
    if (chatSeen && theirs && Date.now() - bubbleAt > 2000) {
        bubbleAt = Date.now();
        Sfx.play('bubble');
    }
    chatSeen = true;
    $('#chat-title').text(unread ? 'Chat (' + unread + ')' : 'Chat');
}

$('#chat-form').on('submit', function (e) {
    e.preventDefault();
    var input = $('#chat-input'), text = $.trim(input.val());
    if (!text) {
        return;
    }
    input.val('');
    send('chat', {text: text}).done(function (r) {
        if (!r.success) {
            input.val(text);
        }
    }).fail(function () { input.val(text); });
});

// in game the chat can be folded away; its title then counts what was missed
$('.room-chat-head').on('click', function (e) {
    if ($(e.target).closest('#sound-button').length) {
        return;
    }
    $('#room-chat').toggleClass('folded');
    chatPlace();
    unread = 0;
    $('#chat-title').text('Chat');
});

// ---------- modes ----------
// duel: health points; royale (replaced by survival, its old games still
// shown): lives; survival: hearts, in halves. All come from the server
// (left, out, delta) for the contestants (seat) after the last finished round.

var MODE_NAMES = {classic: 'Classic', duel: 'Duel', royale: 'Battle Royale', survival: 'Survival'};
var DUEL_HP = 6000, LIVES = 3, BULLSEYE = 4950;

function hearts(n) {
    var html = '';
    for (var i = 0; i < LIVES; i++) {
        html += "<i class='material-icons room-heart" + (i < n ? '' : ' empty') + "'>favorite</i>";
    }
    return html;
}

// duel: health bar
function health(p) {
    var share = Math.max(0, p.left) / DUEL_HP * 100;
    return "<span class='room-hp" + (share < 30 ? ' low' : '') + "'><span style='width:" + share + "%'></span></span>";
}

// what a contestant has left
function standing(p) {
    return s.mode == 'duel' ? health(p) + p.left.toLocaleString('en-US') : s.mode == 'survival' ? lifeLeft(p.left) : hearts(p.left);
}

// what the last round did to them
function change(p) {
    if (!p.delta) {
        return '';
    }
    if (s.mode == 'duel') {
        return " <span class='room-loss'>" + p.delta.toLocaleString('en-US') + "</span>";
    }
    if (s.mode == 'survival') {
        return " <span class='" + (p.delta < 0 ? "room-loss'>−" : "room-gain'>+") + amount(Math.abs(p.delta)) + heartIcon(hardcore()) + "</span>";
    }
    return " <span class='" + (p.delta < 0 ? "room-loss'>-1" : "room-gain'>+1") + "<i class='material-icons room-heart'>favorite</i></span>";
}

function contestants() {
    return s.players.filter(function (p) { return p.seat; });
}

function standingNow() {
    return contestants().filter(function (p) { return p.out == null; });
}

// ---------- lobby ----------

function lobby() {
    if (view != 'lobby') {
        view = 'lobby';
        show('lobby');
    }
    $('#lobby-players').html(s.players.map(function (p) {
        // the host can hand the room over, or kick (a second click confirms)
        var tools = s.host && !p.you ? "<span class='room-tools'>" +
            (p.here ? "<button type='button' class='room-tool' data-host='" + p.uid + "' title='Make host'><i class='material-icons'>star_border</i></button>" : '') +
            (kickArmed == p.uid && Date.now() - kickAt < KICK_ARMED
                ? "<button type='button' class='room-tool armed' data-kick='" + p.uid + "'>Kick?</button>"
                : "<button type='button' class='room-tool' data-kick='" + p.uid + "' title='Kick'><i class='material-icons'>person_remove</i></button>") +
            "</span>" : '';
        return "<div class='room-player" + (p.here ? '' : ' away') + "'>" + dot(p) + esc(p.name) +
            (p.host ? "<i class='material-icons' title='Host'>star</i>" : '') + tools + "</div>";
    }).join(''));
    if (!pending && JSON.stringify(s.settings) != settingsKey) {
        settingsKey = JSON.stringify(s.settings);
        showSettings(s.settings);
    }
    $('#room-settings-fields').prop('disabled', !s.host);
    var host = s.players.filter(function (p) { return p.host; })[0];
    var here = s.players.filter(function (p) { return p.here; }).length;
    var tooFew = s.settings.mode != 'classic' && here < 2;
    $('#start-button').prop('disabled', !s.host || tooFew).text(
        !s.host ? 'Waiting for ' + (host ? host.name : 'the host') + ' to start...'
        : tooFew ? MODE_NAMES[s.settings.mode] + ' needs at least 2 players'
        : 'Start the Game');
}

var KICK_ARMED = 3000;     // ms the "Kick?" button waits for the second click
var kickArmed = null, kickAt = 0;

$('#lobby-players').on('click', '[data-host]', function () {
    send('host', {uid: $(this).data('host')});
}).on('click', '[data-kick]', function () {
    var uid = $(this).data('kick');
    if (kickArmed == uid && Date.now() - kickAt < KICK_ARMED) {
        kickArmed = null;
        send('kick', {uid: uid});
    } else {
        kickArmed = uid;
        kickAt = Date.now();
        lobby();
        setTimeout(function () { if (view == 'lobby') lobby(); }, KICK_ARMED + 50);
    }
});

function showSettings(st) {
    $('#room-settings [name=mode]').each(function () {
        this.checked = this.value == st.mode;
    });
    $('#room-settings [name=province]').each(function () {
        this.checked = st.provinces.indexOf(this.value) >= 0;
    });
    // duel and royale have no set number of rounds: keep the classic choice
    if (st.mode == 'classic') {
        $('#room-settings [name=rounds]').each(function () {
            this.checked = Number(this.value) == st.rounds;
        });
    }
    $('#time-limit-checkbox').prop('checked', st.time_limit > 0);
    if (st.time_limit > 0) {
        $('#time-limit').val(st.time_limit);
    }
    $('#no-look').prop('checked', st.look);
    if (st.difficulty) {
        $('#room-settings [name=difficulty]').each(function () {
            this.checked = this.value == st.difficulty;
        });
    }
    showDifficulty();
    showRules();
}

// the host changes a setting: the server checks it and picks new locations.
// One request at a time, else quick changes could arrive in the wrong order:
// a change made meanwhile is sent afterwards, with the form as it is then.
var saving = false, saveAgain = false;

function saveSettings() {
    if (saving) {
        saveAgain = true;
        return;
    }
    saving = true;
    pending++;
    send('settings', $('#room-settings').serialize())
        .done(function (r) {
            if (!r.success) {
                $('#settings-error').text(r.error || 'These settings were refused');
            }
        })
        .fail(function () { $('#settings-error').text('Connection problem, try again'); })
        .always(function () {
            saving = false;
            pending--;
            if (saveAgain) {
                saveAgain = false;
                saveSettings();
            } else {
                settingsKey = null;
            }
        });
}

$('#room-settings').on('change', function () {
    if (s && s.host) {
        $('#settings-error').text('');
        saveSettings();
    }
});

$('#start-button').on('click', function () {
    $(this).prop('disabled', true);
    send('start').done(function (r) {
        if (!r.success && r.error) {
            $('#settings-error').text(r.error);
        }
    });
});

// ---------- a round ----------

function guess() {
    if (s.mode == 'survival') {
        return guessSurvival();
    }
    var key = 'guess' + s.round;
    var watching = s.live && !s.playing;
    if (view != key) {
        if (view) {
            Sfx.play(view == 'lobby' ? 'start' : 'round');
        }
        view = key;
        show('guess-screen');
        marker = null;
        submitted = s.answered;
        shownAt = Date.now();
        deadline = !s.live && s.settings.time_limit > 0 ? shownAt + s.settings.time_limit * 1000 : null;

        if (map) {
            map.remove();
        }
        map = makeMap('map', -2);
        blockCursor(map);
        map.on('click', function (e) {
            if (submitted || (s.live && !s.playing)) {
                return;
            }
            if (marker) {
                map.removeLayer(marker);
            }
            var b = blockAt(e.latlng);
            marker = L.marker(blockSpot(b.x, b.z), {icon: pin(color(me()))}).addTo(map);
            drop(marker);
            Sfx.play('pin');
            $('#guess-button').removeClass('room-warn').text('Guess!');
        });

        if (viewer) {
            viewer.destroy();
        }
        var locked = s.settings.look;
        viewer = pannellum.viewer('room-panorama', panoramaConfig(s.url, {
            "autoLoad": true,
            "draggable": !locked,
            "mouseZoom": !locked,
            "keyboardZoom": !locked,
            "disableKeyboardCtrl": locked,
            "showControls": !locked
        }));
        $('#guess-button').prop('disabled', false).removeClass('room-warn').text('Guess!');
        heard = null;
        lastSecond = null;
    }
    // a sound each time another player guesses (not for those already in when the page opened)
    var now = s.players.filter(function (p) { return p.guessed && !p.you; }).map(function (p) { return p.name; });
    if (heard && now.some(function (n) { return heard.indexOf(n) < 0; })) {
        Sfx.play('other');
    }
    heard = now;
    // live rounds follow the server's clock
    if (s.live && s.time_left !== undefined) {
        var d = Date.now() + s.time_left * 1000;
        if (deadline === null || Math.abs(d - deadline) > 700) {
            deadline = d;
        }
    }
    if (s.answered) {
        submitted = true;
    }
    var mine = me();
    if (watching) {
        $('#guess-button').prop('disabled', true).text(mine.seat ? "You're out" : 'Spectating');
    } else if (submitted) {
        $('#guess-button').prop('disabled', true).text(s.live ? 'Waiting for the others...' : 'Guess sent');
    }

    if (s.mode == 'classic') {
        $('#hud-round').text('Round ' + s.round + '/' + s.rounds);
        $('#hud-mult').empty();
        $('#hud-score').text(points(mine.total));
    } else {
        $('#hud-round').text('Round ' + s.round);
        $('#hud-mult').text(s.mode == 'duel' && s.multiplier > 1 ? 'Damage ×' + s.multiplier : '');
        $('#hud-score').html(watching ? 'Watching' : s.mode == 'duel' ? mine.left.toLocaleString('en-US') + ' HP' : hearts(mine.left));
    }
    $('#hud-call').text(s.live && s.first && !submitted && !watching ? s.first + ' has guessed, hurry up!' : '');
    var inRound = s.players.filter(function (p) {
        return s.mode == 'classic' ? p.here || p.guessed : p.seat && p.out == null;
    });
    // everyone's health or lives stay in sight during the round
    $('#hud-players').html(!s.live ? '' : inRound.map(function (p) {
        var left = s.mode == 'duel' ? ' ' + p.left.toLocaleString('en-US') + ' HP' : s.mode == 'royale' ? hearts(p.left) : '';
        return "<span class='room-hud-player'>" + dot(p) + esc(p.name) + left +
            "<i class='material-icons'>" + (p.guessed ? 'check_circle' : 'more_horiz') + "</i></span>";
    }).join(''));
}

// auto: the clock ran out, send the marker if there is one
function submit(auto) {
    if (submitted || (s.live && !s.playing)) {
        return;
    }
    if (!marker && (s.live || !auto)) {
        if (!auto) {
            $('#guess-button').addClass('room-warn').text('Select a location first!');
        }
        return;
    }
    submitted = true;
    if (marker) {
        Sfx.play('guess');
    }
    var key = view, data = {round: s.round};
    if (marker) {
        var b = blockAt(marker.getLatLng());
        data.x = b.x;
        data.z = b.z;
    }
    if (!s.live) {
        data.time = ((Date.now() - shownAt) / 1000).toFixed(2);
    }
    $('#guess-button').prop('disabled', true).text(s.live ? 'Waiting for the others...' : 'Guess sent');
    send('guess', data).fail(function () {
        if (view == key) {
            submitted = false;
            $('#guess-button').prop('disabled', false).addClass('room-warn').text('Connection problem, guess again');
        }
    });
}

$('#guess-button').on('click', function () { submit(false); });

function clocks() {
    if (!s) {
        return;
    }
    if (s.mode == 'survival') {
        return clocksSurvival();
    }
    if (view.indexOf('guess') != 0) {
        $('#room-countdown').prop('hidden', true);
    }
    if (view.indexOf('guess') == 0) {
        if (deadline === null) {
            $('#room-countdown').prop('hidden', true);
        } else {
            // the time left, in its own box under the banner, red for the last ten seconds;
            // out loud too, for whoever still has to guess
            var left = Math.max(0, (deadline - Date.now()) / 1000);
            var second = Math.ceil(left), guessing = !submitted && (!s.live || s.playing);
            $('#room-countdown').prop('hidden', false).html("<i class='material-icons'>timer</i>" + clock(left))
                .toggleClass('urgent', left <= 10);
            if (guessing && second != lastSecond && left > 0) {
                if (second == 10 || second == 5) {
                    Sfx.play('warn');
                } else if (second <= 3) {
                    Sfx.play('tick', [1.5, 1.26, 1.06][second - 1]);   // rising to the last second
                }
            }
            lastSecond = second;
            if (left <= 0.2) {
                submit(true);
            }
        }
    } else if (view.indexOf('reveal') == 0) {
        nextButton();
    }
}

// ---------- end of a round ----------

function reveal() {
    var key = 'reveal' + s.round, fresh = view != key, from = view;
    if (view != key) {
        view = key;
        show('reveal-screen');
        nextAt = null;
        if (revealMap) {
            revealMap.remove();
        }
        revealMap = makeMap('reveal-map', -1);
        $('#reveal-mine').removeClass('stamp');
        var answer = blockSpot(s.reveal.X, s.reveal.Z);
        drop(L.marker(answer, {icon: pin(ANSWER, true), zIndexOffset: 1000}).addTo(revealMap), true);
        // the guesses land one by one, the furthest first, each on a higher note
        var spots = [answer], drops = s.reveal.guesses.filter(function (g) {
            return g.x !== null && player(g.name);
        }).sort(function (a, b) { return a.score - b.score; });
        drops.forEach(function (g, i) {
            var p = player(g.name), pos = blockSpot(g.x, g.z);
            spots.push(pos);
            setTimeout(function () {
                if (view != key) {
                    return;
                }
                drawLine(L.polyline([answer, answer], {color: color(p), weight: 3, dashArray: '8 6'}).addTo(revealMap), answer, pos, 260);
                drop(L.marker(pos, {icon: pin(color(p))}).addTo(revealMap)
                    .bindTooltip(esc(g.name), {permanent: true, direction: 'top', className: 'room-tip'}), true);
                Sfx.play('note', noteBlock(SCALE[Math.min(i, SCALE.length - 1)]));
            }, DROP * (i + 1));
        });
        if (s.mode == 'survival') {
            zones(answer, spots);
        }
        revealMap.fitBounds(L.latLngBounds(spots), {padding: [60, 60], maxZoom: 1});
        // then your points count up, and one sound says how it went
        counting = {key: key, from: Date.now() + DROP * (drops.length + 1), score: 0, done: false};
    }

    var you = me();
    var mine = s.reveal.guesses.filter(function (g) { return g.name == you.name; })[0];
    var guessed = mine && mine.x !== null;
    var line = guessed ? "+<span id='reveal-count'>" + points(mine.score) + '</span>' : 'No guess this round';
    var counted = !counting || counting.key != key || counting.done;
    var bullseye = guessed && mine.score >= BULLSEYE && counted;
    if (bullseye) {
        line = 'Bullseye! ' + line;
    }
    var bad = "<span class='room-loss'> · ", good = "<span class='room-gain'> · ";
    if (s.mode == 'survival' && you.seat && (you.out == null || you.out == s.round)) {
        line = survivalLine(you, guessed ? line : 'Boom! No guess in time', bad, good);
    } else if (s.mode != 'classic' && you.seat && (you.out == null || you.out == s.round)) {
        if (you.out == s.round) {
            line += bad + "you're out!</span>";
        } else if (s.mode == 'duel') {
            line += you.delta ? bad + you.delta.toLocaleString('en-US') + ' HP</span>' : good + 'no damage</span>';
        } else if (you.delta) {
            line += you.delta < 0 ? bad + 'you lose a life</span>' : good + 'a life back!</span>';
        }
    }
    if (fresh) {
        // only for who played this round (not a spectator, not someone already out)
        var played = s.mode == 'classic' || (you.seat && (you.out == null || you.out == s.round));
        counting.score = guessed ? mine.score : 0;
        counting.verdict = !played ? null
            : s.mode != 'classic' && you.out == s.round ? 'out'
            : guessed && mine.score >= BULLSEYE ? 'perfect'
            : s.mode != 'classic' && you.delta < 0 ? 'hurt'
            : s.mode == 'survival' ? 'good'
            : guessed && mine.score >= GOOD ? 'good'
            : guessed && mine.score > BAD ? null : 'bad';
        counting.earned = s.me && s.me.earned;
        requestAnimationFrame(count);
        if (s.mode == 'survival') {
            randomPotion(from == 'guess' + s.round);
        }
    }
    $('#reveal-title').text(s.mode == 'classic' ? 'Round ' + s.round + '/' + s.rounds
        : 'Round ' + s.round + (s.mode == 'duel' && s.multiplier > 1 ? ' · damage ×' + s.multiplier : ''));
    $('#reveal-mine').html(line).toggleClass('none', !guessed).toggleClass('room-bullseye', bullseye);
    $('#reveal-total').text({classic: 'Total', duel: 'HP', royale: 'Lives', survival: 'Hearts'}[s.mode]);

    var rows = s.players.map(function (p) {
        var g = s.reveal.guesses.filter(function (x) { return x.name == p.name; })[0];
        return {p: p, guessed: !!g, score: g && g.x !== null ? g.score : -1, total: g ? g.upto : p.total};
    }).filter(function (r) {
        if (s.mode != 'classic') {
            return r.p.seat;
        }
        return r.guessed || (s.live && r.p.here);
    }).sort(function (a, b) {
        // whoever was already out goes last
        var outA = a.p.out != null && a.p.out < s.round, outB = b.p.out != null && b.p.out < s.round;
        return outA - outB || b.score - a.score;
    });
    var knock = counting && counting.key == key && counting.done && !counting.knocked;
    var html = rows.map(function (r) {
        var gone = r.p.out != null && r.p.out < s.round, last;
        var round = r.score >= 0 ? '+' + r.score.toLocaleString('en-US') : '-';
        if (s.mode == 'survival') {
            round = gone ? '-' : roundCost(r.p);
        }
        if (s.mode == 'classic') {
            last = r.total.toLocaleString('en-US');
        } else if (gone) {
            last = 'Out';
        } else if (r.p.out == s.round) {
            last = (s.mode == 'royale' ? hearts(0) + ' ' : '') + "<span class='room-loss'>Out!</span>";
        } else if (s.mode == 'duel') {
            last = '<div>' + r.p.left.toLocaleString('en-US') + change(r.p) + '</div>' + health(r.p);
        } else if (s.mode == 'survival') {
            last = lifeLeft(r.p.left);
        } else {
            last = hearts(r.p.left) + change(r.p);
        }
        var hit = knock && !gone && s.mode != 'classic' && (r.p.out == s.round || r.p.delta < 0);
        var heal = knock && !gone && s.mode == 'royale' && r.p.delta > 0;
        return "<tr class='" + (r.p.you ? 'you' : '') + (gone ? ' room-out' : '') + (hit ? ' hit' : '') + (heal ? ' heal' : '') + "'>" +
            "<td>" + dot(r.p) + esc(r.p.name) + (s.mode == 'survival' ? bottles(r.p.effects || {}) : '') + "</td>" +
            "<td class='num'>" + round + "</td>" +
            "<td class='num'>" + last + "</td></tr>";
    }).join('');
    var plain = html.replace(/ (hit|heal)'/g, "'");
    if (knock || plain != revealRows) {
        $('#reveal-rows').html(html);
        revealRows = plain;
    }
    if (knock) {
        counting.knocked = true;
    }

    if (s.next_in !== undefined) {
        nextAt = Date.now() + s.next_in * 1000;
    } else if (s.phase_left !== undefined) {
        nextAt = Date.now() + s.phase_left * 1000;
    }
    nextButton();
}

// your points of the round, counted up after the pins have landed, with a
// tick now and then; the poll rewrites the line every second, the count
// writes over it until it is done
var DROP = 350;            // ms between two pins landing
var COUNT = 900;           // ms to count the points
var SCALE = [5, 9, 12, 17, 21, 24];   // the pins' notes: up the scale, as note blocks
var GOOD = 4000, BAD = 1500;          // above: a happy note; at or below: a low one
var counting = null;
var revealRows = '';       // the table as last written, without the knocks

function count() {
    var c = counting;
    if (!c || c.done || view != c.key) {
        return;
    }
    var t = (Date.now() - c.from) / COUNT, el = document.getElementById('reveal-count');
    if (t >= 1) {
        c.done = true;
        // the line and the table as they end: "Bullseye!" stamps, health takes the knock
        reveal();
        if (c.verdict == 'perfect') {
            replay(document.getElementById('reveal-mine'), 'stamp');
        }
        if (c.verdict) {
            Sfx.play(c.verdict);
        }
        if (c.earned) {
            // the emeralds, picked up as in Minecraft
            setTimeout(function () { Sfx.play('pickup'); }, 300);
        }
        return;
    }
    if (el) {
        el.textContent = points(Math.round(c.score * Math.max(0, t)));
    }
    if (t > 0 && c.score && Date.now() - (c.tick || 0) > 140) {
        c.tick = Date.now();
        Sfx.play('tick', 0.8 + t * 0.7, 0.5);
    }
    requestAnimationFrame(count);
}

// is the round on display the last one?
function lastRound() {
    return s.round >= s.rounds || (s.mode != 'classic' && standingNow().length <= 1);
}

function nextButton() {
    var b = $('#next-button'), label = lastRound() ? 'See Results' : s.mode == 'survival' ? 'Shop' : 'Next Round';
    if (!s.live) {
        b.prop('disabled', false).text(lastRound() ? label : 'Next Location');
        return;
    }
    var left = nextAt === null ? 0 : Math.max(0, Math.ceil((nextAt - Date.now()) / 1000));
    if (s.host) {
        b.prop('disabled', false).text(label + ' (' + left + ')');
    } else {
        b.prop('disabled', true).text(label + ' in ' + left + ' s');
    }
}

$('#next-button').on('click', function () {
    if (!s) {
        return;
    }
    if (s.live) {
        $(this).prop('disabled', true);
        send('start');
    } else if (s.round >= s.rounds) {
        finished = true;
        results();
    } else {
        cur = s.round + 1;
        poll();
    }
});

// ---------- end of the game ----------

function results() {
    var fresh = view != 'results';
    if (view != 'results') {
        view = 'results';
        show('results');
        if (viewer) {
            viewer.destroy();
            viewer = null;
        }
    }
    var medals = ['#d4af37', '#c0c0c0', '#cd7f32'];
    var rows, value, same;
    if (s.mode == 'classic') {
        rows = s.players.filter(function (p) { return p.played > 0; }).sort(function (a, b) { return b.total - a.total; });
        value = function (p) {
            var missing = p.played < s.rounds ? " <small>(" + p.played + '/' + s.rounds + " rounds)</small>" : '';
            return [missing, p.total.toLocaleString('en-US')];
        };
        same = function (a, b) { return a.total == b.total; };
    } else {
        // still standing first, then the latest to fall
        rows = contestants().sort(function (a, b) {
            return (a.out != null) - (b.out != null) || b.left - a.left || (b.out || 0) - (a.out || 0) || b.total - a.total;
        });
        value = function (p) {
            return ['', p.out != null ? 'Out in round ' + p.out : standing(p)];
        };
        same = function (a, b) { return a.out == b.out && a.left == b.left && a.total == b.total; };
    }
    if (fresh) {
        podium(rows);
    }
    var rank = 0;
    var html = rows.map(function (p, i) {
        if (i == 0 || !same(p, rows[i - 1])) {
            rank = i + 1;
        }
        var place = rank <= 3 ? "<i class='material-icons' style='color:" + medals[rank - 1] + "'>emoji_events</i>" : rank;
        var v = value(p);
        return "<tr class='leaderboard-row" + (p.you ? ' you' : '') + (i < hidden ? ' podium-wait' : '') + (i == plankNow ? ' plank-in' : '') + "'>" +
            "<td>" + place + "</td><td class='room-name'>" + dot(p) + esc(p.name) + v[0] + "</td><td>" + v[1] + "</td></tr>";
    }).join('');
    var plain = html.replace(" plank-in'", "'");
    if (plankNow >= 0 || plain != resultRows) {
        $('#results-rows').html(html);
        resultRows = plain;
    }

    var title = 'Results';
    if (hidden) {
        title = 'Results';
    } else if (rows.length > 1 && same(rows[0], rows[1])) {
        title = 'Draw!';
    } else if (rows.length > 1) {
        title = rows[0].you ? 'You Win!' : rows[0].name + ' Wins!';
    }
    $('#results-title').text(title);
    if (finale) {
        finale = false;
        if (s.live && rows.length > 1 && rows.some(function (p) { return p.you; })) {
            Sfx.play(rows[0].you && title != 'Draw!' ? 'win' : 'lose');
        }
        if (s.live && rows.length > 1) {
            // the sign swings with the winner's name, the light crosses their line once it has landed
            replay(document.getElementById('results-title'));
            if (title != 'Draw!') {
                setTimeout(function () {
                    shine(document.querySelector('#results-rows tr'), document.getElementById('results'));
                }, 420);
            }
        }
        gain();
    }
    $('#results-score').text({classic: 'Score', duel: 'HP', royale: 'Lives', survival: 'Hearts'}[s.mode]);
    $('#again-button').prop('hidden', !(s.live && s.host));
    var host = s.players.filter(function (p) { return p.host; })[0];
    $('#results-hint').text(s.live && !s.host && host ? host.name + ' can start a new game.' : '');
}

// the podium: at the end of a live game the top three show up one by one,
// third place first, each on a higher note; then the winner's fanfare (or
// the villager's "hmm"), then the XP
var PODIUM = 800;          // ms between two places
var hidden = 0;            // top places still hidden
var plankNow = -1;         // the place sliding in right now
var resultRows = '';       // the table as last written, without the plank
var finale = false;        // the podium is complete: time for the last sounds

function podium(rows) {
    hidden = s.live && rows.length > 1 ? Math.min(3, rows.length) : 0;
    if (!hidden) {
        finale = true;
        return;
    }
    var step = function () {
        if (view != 'results') {
            return;
        }
        hidden--;
        Sfx.play('note', noteBlock([24, 17, 12][hidden]));
        finale = !hidden;
        plankNow = hidden;
        results();
        plankNow = -1;
        if (hidden) {
            setTimeout(step, PODIUM);
        }
    };
    setTimeout(step, PODIUM);
}

// the XP this game brought (accounts only), and the wins in a row
function gain() {
    var slot = document.getElementById('xp-slot');
    $.ajax({url: 'api/room/' + code + '/xp', dataType: 'json', timeout: 8000}).done(function (x) {
        if (x.success) {
            var notes = x.bonus ? ['Win bonus: +' + x.bonus + ' XP'] : [];
            if (x.streak >= 2) {
                notes.push("<b><i class='material-icons xp-fire'>local_fire_department</i>" + x.streak + ' wins in a row!</b>');
            }
            xpGain(slot, x.xp, x.gained, notes);
        } else if (x.guest) {
            // logging in from here makes this game, and the guest's other ones, the account's
            var back = encodeURIComponent('room?code=' + code);
            slot.innerHTML = "<p class='xp-note'><a href='login?next=" + back + "'>Log in</a> or <a href='register?next=" + back + "'>make an account</a> " +
                "to save this game and earn XP.</p>";
        }
    });
}

$('#again-button').on('click', function () {
    var b = $(this).prop('disabled', true);
    send('again')
        .done(function (r) {
            if (r.success) {
                location.href = 'room?code=' + r.code;
            } else {
                b.prop('disabled', false);
            }
        })
        .fail(function () { b.prop('disabled', false); });
});

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
            extension: 'jpg', tileResolution: 512, maxLevel: 4, cubeResolution: 4096}}
        : {type: 'equirectangular', panorama: url};
    for (var k in options) config[k] = options[k];
    return config;
}

// ---------- survival ----------
// Survival with friends (app.py, "Survival with friends"): the hearts, the
// zone, the clock and the potions of the solo game (potions.js), emeralds
// for each guess, and between two rounds the Potion Merchant. The server
// says the phase: throw (the potions bought fly), prep (the picture loads
// under a cover, everyone sees what hit them and may drink milk), guess,
// reveal (the random potions are thrown), shop.

var SHOP_ITEMS = ['mining_fatigue', 'swiftness', 'wither', 'nausea', 'blindness', 'darkness', 'regeneration', 'milk'];
var SELF = ['regeneration', 'milk'];      // bought for oneself, never thrown
var FUSE = 3;              // seconds of hissing before the creeper explodes
var DRINK_MS = 1600;       // milk, drunk as in Minecraft (survival.js has the same)
var GULPS = [400, 600, 800, 1000, 1200, 1400, 1600];
var startsAt = null;       // when the round starts, local clock (throw, prep)
var shopAt = null;         // when the shop closes, local clock
var madeFor = null;        // the picture and the effects the panorama and the map were made for
var covered = false;       // the cover was up on this page: its lifting is the start
var started = null;        // the round whose clock and effects have started
var startedAt = 0;         // when it started, local clock
var darkTimer = null, witherShown = null, fused = false, exploded = false, drinking = false;
var announced = null;      // the round whose throws were announced
var coverHtml = null, shopPick = null, shopSlots = '', targetsHtml = '', shopSays = null;

function hardcore() {
    return s.difficulty == 'hardcore';
}

// hearts left, from half-hearts: "8.5" and a heart
function lifeLeft(half) {
    return amount(half) + ' ' + heartIcon(hardcore());
}

function myEffects() {
    var p = me();
    return (p && p.effects) || {};
}

// the potions of a set, in the bottles' order
function effectList(fx) {
    return BOTTLES.filter(function (k) { return fx[k]; });
}

function bottles(fx) {
    return effectList(fx).map(function (k) {
        return "<span class='room-bottle' title='" + POTIONS[k][0] + roman(fx[k]) + "'>" + potionIcon(k) + "</span>";
    }).join('');
}

function itemIcon(k) {
    return k == 'milk' ? "<i class='bucket-icon'></i>" : potionIcon(k);
}

// as Minecraft names them: thrown, a splash potion
function itemName(k) {
    return k == 'milk' ? 'Milk Bucket' : (SELF.indexOf(k) >= 0 ? 'Potion of ' : 'Splash Potion of ') + POTIONS[k][0];
}

function guessSurvival() {
    var key = 'guess' + s.round, fx = myEffects(), you = me(), round = s.phase == 'guess';
    if (view != key) {
        if (view == 'lobby') {
            Sfx.play('start');
        }
        view = key;
        show('guess-screen');
        marker = null;
        madeFor = null;
        coverHtml = null;
        covered = false;
        submitted = s.answered;
        heard = null;
        deadline = null;
        fused = exploded = drinking = false;
        witherShown = null;
        clearTimeout(darkTimer);
        $('#room-dark').prop('hidden', true);
        $('#guess-button').prop('disabled', false).removeClass('room-warn').text('Guess!');
    }
    // the panorama and the map, made for the effects (milk may still take them away before the round)
    var made = s.url + ' ' + JSON.stringify(s.playing ? fx : {});
    if (made != madeFor) {
        madeFor = made;
        survivalViews(s.playing ? fx : {});
    }
    // the potions bought fly first, for everyone to see
    if (s.phase == 'throw' && announced != s.round) {
        announced = s.round;
        announce();
    }
    if (!round) {
        covered = true;
        startsAt = Date.now() + s.starts_in * 1000;
        cover(fx);
    } else if (started != s.round) {
        started = s.round;
        if (covered) {
            Sfx.play('round');
        }
        startRound(fx);
    }
    $('#room-cover').prop('hidden', round);
    $('#guess-screen').toggleClass('covered', !round);

    if (round) {
        // a sound each time another player guesses (not for those already in when the round appeared)
        var now = s.players.filter(function (p) { return p.guessed && !p.you; }).map(function (p) { return p.name; });
        if (heard && now.some(function (n) { return heard.indexOf(n) < 0; })) {
            Sfx.play('other');
        }
        heard = now;
        if (s.time_left !== undefined) {
            var d = Date.now() + s.time_left * 1000;
            if (deadline === null || Math.abs(d - deadline) > 700) {
                deadline = d;
            }
        }
    }
    if (s.answered) {
        submitted = true;
    }
    if (!s.playing) {
        $('#guess-button').prop('disabled', true).text(you && you.seat ? "You're out" : 'Spectating');
    } else if (submitted && !exploded) {
        $('#guess-button').prop('disabled', true).text('Waiting for the others...');
    }

    // your hearts where Minecraft keeps them; the round's potions on the sign
    var hearts = document.getElementById('room-hearts');
    $(hearts).prop('hidden', !s.playing);
    if (s.playing) {
        drawHearts(hearts, witherShown === null ? you.left : witherShown, s.max, hardcore());
    }
    $('#hud-round').text('Round ' + s.round);
    $('#hud-mult').html(s.playing ? effectList(fx).map(function (k) {
        return "<b class='room-effect'>" + potionIcon(k) + POTIONS[k][0] + roman(fx[k]) + '</b>';
    }).join(' ') : '');
    $('#hud-score').text(s.playing ? '' : 'Watching');
    $('#hud-call').text(round && s.first && !submitted && s.playing ? s.first + ' has guessed, hurry up!' : '');
    $('#hud-players').html(standingNow().map(function (p) {
        return "<span class='room-hud-player'>" + dot(p) + esc(p.name) + ' ' + lifeLeft(p.left) + bottles(p.effects || {}) +
            (round ? "<i class='material-icons'>" + (p.guessed ? 'check_circle' : 'more_horiz') + "</i>" : '') + "</span>";
    }).join(''));
}

// the map and the panorama of a round, with what the potions do to them
function survivalViews(fx) {
    if (map) {
        map.remove();
    }
    map = makeMap('map', -2);
    blockCursor(map);
    map.on('click', function (e) {
        if (submitted || !s.playing || s.phase != 'guess') {
            return;
        }
        if (marker) {
            map.removeLayer(marker);
        }
        var b = blockAt(e.latlng);
        marker = L.marker(blockSpot(b.x, b.z), {icon: pin(color(me()))}).addTo(map);
        drop(marker);
        Sfx.play('pin');
        $('#guess-button').removeClass('room-warn').text('Guess!');
    });
    if (fx.mining_fatigue) {
        // Mining Fatigue: no zoom at all, the map stays as it opens
        map.setMinZoom(map.getZoom()).setMaxZoom(map.getZoom());
        ['scrollWheelZoom', 'doubleClickZoom', 'touchZoom', 'boxZoom', 'keyboard'].forEach(function (h) { map[h].disable(); });
        map.zoomControl.remove();
    }
    if (viewer) {
        viewer.destroy();
    }
    var options = {autoLoad: true};
    if (fx.nausea) {
        // Nausea: the view turns by itself, faster at each level, and cannot be held
        options = {autoLoad: true, autoRotate: NAUSEA_SPIN * fx.nausea, draggable: false, mouseZoom: false, keyboardZoom: false,
                   disableKeyboardCtrl: true, showControls: false};
    }
    viewer = pannellum.viewer('room-panorama', panoramaConfig(s.url, options));
}

// the round starts: what counts from its start (a reload included): Darkness, Wither
function startRound(fx) {
    var elapsed = s.elapsed || 0;
    startedAt = Date.now() - elapsed * 1000;
    witherShown = null;
    clearTimeout(darkTimer);
    if (s.playing && fx.darkness) {
        var round = s.round;
        darkTimer = setTimeout(function () {
            if (view == 'guess' + round) {
                $('#room-dark').prop('hidden', false);
            }
        }, Math.max(0, DARK_AFTER / fx.darkness - elapsed) * 1000);
    }
}

// Wither: the hearts the server will take, shown as they go
function wither() {
    var fx = myEffects(), you = me();
    if (!s.playing || !fx.wither || submitted) {
        return;
    }
    var hp = Math.max(0, you.left - Math.floor((Date.now() - startedAt) / 1000 * fx.wither / WITHER_EVERY));
    if (hp != witherShown) {
        var el = document.getElementById('room-hearts');
        if (witherShown !== null) {
            drawHearts(el, hp, s.max, hardcore());
            replay(el, 'hurt');
            Sfx.play('hurt', 1, .6);
        }
        witherShown = hp;
    }
}

// before the round the picture loads under a cover, which says what hit
// you; the milk is drunk here
function cover(fx) {
    $('#cover-title').text('Round ' + s.round);
    if (drinking) {
        return;   // the bucket is still going down
    }
    var you = me(), list = effectList(fx), html = '';
    if (s.playing && you.milked) {
        html = "<div class='cover-effect'><i class='bucket-icon empty'></i><div><b>Milk!</b><span>No potion this round.</span></div></div>";
    } else if (s.playing && list.length) {
        html = list.map(function (k) {
            return "<div class='cover-effect'>" + potionIcon(k) + "<div><b class='" + (k == 'regeneration' ? 'good' : 'bad') + "'>" +
                POTIONS[k][0] + roman(fx[k]) + '</b><span>' + potionText(k, hardcore(), fx[k]) + '</span></div></div>';
        }).join('');
    } else if (s.playing) {
        html = "<p class='cover-none'>No potion on you.</p>";
    }
    if (html != coverHtml) {
        $('#cover-effects').html(html);
        coverHtml = html;
    }
    var milk = s.playing && list.length && !you.milked && s.me && s.me.milk > 0;
    $('#room-milk').prop('hidden', !milk).prop('disabled', false)
        .html("<i class='bucket-icon'></i>Drink Milk<small>" + (s.me ? s.me.milk : 0) + ' left</small>');
}

// the bucket goes up and gulps (as alone); the cover changes once it is empty
$('#room-milk').on('click', function () {
    var b = $(this).prop('disabled', true), round = s.round;
    drinking = true;
    b.find('.bucket-icon').addClass('drinking');
    GULPS.forEach(function (t) {
        setTimeout(function () {
            if (s.round == round) {
                Sfx.play('drink', .9 + Math.random() * .1);
            }
        }, t);
    });
    var sent = send('milk', {round: round});
    setTimeout(function () {
        sent.always(function () {
            drinking = false;
            coverHtml = null;
            if (view == 'guess' + round && s.phase != 'guess') {
                cover(myEffects());
            }
        });
    }, DRINK_MS);
});

// the potions bought, for everyone: a toast each (the same throw twice: ×2);
// whoever they hit sees them fly
function announce() {
    var seen = {}, list = [], you = me();
    (s.throws || []).forEach(function (t) {
        var k = t.by + '>' + t.item + '>' + t.to;
        if (!seen[k]) {
            seen[k] = {t: t, n: 0};
            list.push(seen[k]);
        }
        seen[k].n++;
    });
    if (!list.length) {
        return;
    }
    Sfx.play('toast');
    list.forEach(function (x) {
        toast(esc(x.t.by) + ' → ' + POTIONS[x.t.item][0] + (x.n > 1 ? ' ×' + x.n : '') + ' → ' + esc(x.t.to),
              "<span class='toast-item'>" + potionIcon(x.t.item) + '</span>');
    });
    if (s.playing && you && list.some(function (x) { return x.t.to == you.name; }) && !REDUCED) {
        throwAnimation(function () {});
    }
}

function clocksSurvival() {
    if (view.indexOf('guess') == 0) {
        if (s.phase != 'guess') {
            $('#room-countdown').prop('hidden', true);
            var wait = Math.max(0, Math.ceil((startsAt - Date.now()) / 1000));
            $('#cover-left').text(wait ? 'Starts in ' + wait + ' s' : 'Go!');
            return;
        }
        if (deadline === null) {
            $('#room-countdown').prop('hidden', true);
            return;
        }
        var left = Math.max(0, (deadline - Date.now()) / 1000), guessing = !submitted && s.playing;
        $('#room-countdown').prop('hidden', false).html("<i class='material-icons'>timer</i>" + clock(left))
            .toggleClass('urgent', left <= 10);
        wither();
        // the creeper hisses for the last seconds; then the pin goes by itself, or it explodes
        if (guessing && left <= FUSE && !fused) {
            fused = true;
            Sfx.play('fuse');
        }
        if (guessing && left <= 0.2) {
            if (marker) {
                submit(true);
            } else if (!exploded) {
                exploded = submitted = true;
                explode();
                $('#guess-button').prop('disabled', true).text('Boom!');
            }
        }
    } else if (view.indexOf('shop') == 0) {
        var shut = Math.max(0, Math.ceil((shopAt - Date.now()) / 1000));
        $('#shop-clock').html("<i class='material-icons'>timer</i>" + shut + ' s').toggleClass('urgent', shut <= 5);
    } else if (view.indexOf('reveal') == 0) {
        nextButton();
    }
}

// the reveal: your zone around the answer (green, no damage; yellow, damage;
// red, death with the hearts you had), and where the Nausea pins were aimed
function zones(answer, spots) {
    var you = me(), r = you && you.result;
    if (r) {
        L.circle(answer, {radius: r.kill || r.far, color: '#c9a227', weight: 2, fillColor: '#ffd75e', fillOpacity: .14, interactive: false}).addTo(revealMap);
        if (r.kill) {
            L.circle(answer, {radius: r.kill, color: '#b3302a', weight: 3, dashArray: '10 6', fill: false, interactive: false}).addTo(revealMap);
        }
        L.circle(answer, {radius: r.safe, color: '#2f7a22', weight: 2, fillColor: '#88cc42', fillOpacity: .22, interactive: false}).addTo(revealMap);
        spots.push(L.latLng(answer.lat + r.safe, answer.lng + r.safe), L.latLng(answer.lat - r.safe, answer.lng - r.safe));
    }
    s.players.forEach(function (p) {
        var g = p.result;
        if (g && g.aim_x !== null && g.aim_x !== undefined) {
            var aimed = blockSpot(g.aim_x, g.aim_z);
            L.circleMarker(aimed, {radius: 6, color: '#3f2724', weight: 2, fillColor: '#ffffff', fillOpacity: .8, interactive: false}).addTo(revealMap);
            if (g.x !== null) {
                L.polyline([aimed, blockSpot(g.x, g.z)], {color: '#3f2724', weight: 2, dashArray: '2 5', interactive: false}).addTo(revealMap);
            }
        }
    });
}

// your line of the reveal: what the round cost, what it brought
function survivalLine(you, line, bad, good) {
    var r = you.result || {}, lost = (r.damage || 0) + (r.wither || 0), heart = heartIcon(hardcore());
    if (you.out == s.round) {
        line += bad + "you're out!</span>";
    } else if (lost) {
        line += bad + '−' + amount(lost) + ' ' + heart + (r.heal ? ' +' + amount(r.heal) + ' ' + heart : '') + '</span>';
    } else {
        line += good + (r.heal ? '+' + amount(r.heal) + ' ' + heart : 'safe') + '</span>';
    }
    if (s.me && s.me.earned) {
        line += " <span class='room-earn'>+" + s.me.earned + emeraldIcon() + '</span>';
    }
    return line;
}

// what the round cost a player, for the table
function roundCost(p) {
    var r = p.result;
    if (!r) {
        return '-';
    }
    var lost = r.damage + r.wither;
    return lost ? "<span class='room-loss'>−" + amount(lost) + ' ' + heartIcon(hardcore()) + '</span>' : "<span class='room-gain'>Safe</span>";
}

// a random potion thrown at you with the reveal, as alone: it flies (when
// coming from the round, not on a reload), then its card stays in the panel
function randomPotion(thrown) {
    var fx = myEffects(), k = effectList(fx)[0], key = view, card = $('#reveal-potion').prop('hidden', true);
    if (!k || !s.playing) {
        return;
    }
    var shown = function () {
        if (view == key) {
            card.html(potionIcon(k) + '<div><b>' + POTIONS[k][0] + '!</b><span>' + potionText(k, hardcore()) + '</span></div>').prop('hidden', false);
        }
    };
    if (thrown && !REDUCED) {
        setTimeout(function () { throwAnimation(shown); }, 900);
    } else {
        shown();
    }
}

// ---------- the Potion Merchant ----------
// Between two rounds: an inventory of potions (Minecraft's slots, its item
// tooltips, Wynncraft's ✔ and ✖), paid in emeralds, thrown at a player; the
// merchant speaks like Minecraft's wandering trader. What others buy stays
// secret until the shop shuts (then the throws).

function shop() {
    var key = 'shop' + s.round, you = me();
    if (view != key) {
        view = key;
        show('shop-screen');
        shopPick = null;
        shopSlots = targetsHtml = '';
        Sfx.play('trader');
    }
    shopAt = Date.now() + s.phase_left * 1000;
    var mine = s.me, wares = s.wares || {}, alive = you && you.seat && you.out == null;
    $('#shop-purse').html(mine ? emeraldIcon() + '<b>' + mine.emeralds + '</b>' : '').prop('hidden', !mine);
    var says = shopSays && Date.now() < shopSays.until ? shopSays.text
        : !mine ? 'You are watching.' : !alive ? "You're out, but your emeralds still work." : '';
    $('#shop-note').prop('hidden', !says).text(says).toggleClass('bad', !!(shopSays && Date.now() < shopSays.until));
    var items = !mine ? [] : SHOP_ITEMS.filter(function (k) { return k in wares || (k == 'milk' && alive && mine.milk_left <= 0); });
    var slots = items.map(function (k) {
        var price = wares[k], sold = price === undefined, dear = !sold && mine.emeralds < price;
        return "<button type='button' class='shop-slot" + (k == shopPick ? ' picked' : '') + (dear ? ' dear' : '') + (sold ? ' sold' : '') +
            "' data-item='" + k + "' aria-label='" + itemName(k) + "'>" + itemIcon(k) +
            "<span class='shop-price'>" + (sold ? '' : price + emeraldIcon()) + "</span></button>";
    }).join('');
    if (slots != shopSlots) {
        $('#shop-slots').html(slots);
        shopSlots = slots;
    }
    tip(shopPick);
    targets(shopPick);
    $('#shop-bought').html(!s.bought || !s.bought.length ? '' : 'You bought: ' + s.bought.map(function (b) {
        return "<span class='shop-had'>" + itemIcon(b.item) + (SELF.indexOf(b.item) < 0 ? '→ ' + esc(b.to) : '') + '</span>';
    }).join(' '));
    var ready = you && you.ready;
    $('#ready-button').prop('hidden', !mine).prop('disabled', !!ready).text(ready ? 'Waiting for the others...' : 'Ready');
    $('#shop-ready').html(contestants().filter(function (p) { return p.here; }).map(function (p) {
        return "<span class='room-hud-player'>" + dot(p) + esc(p.name) + "<i class='material-icons'>" + (p.ready ? 'check_circle' : 'more_horiz') + "</i></span>";
    }).join(''));
}

// the item's tooltip, drawn as Minecraft draws them: its name, its effect
// (red: bad for whoever it hits, blue: good), what it does, and the price,
// marked ✔ or ✖ as Wynncraft marks what you can or cannot use
function tip(k) {
    var box = $('#shop-tip');
    if (!k || !s.me) {
        box.prop('hidden', true);
        return;
    }
    var price = (s.wares || {})[k], ok = price !== undefined && s.me.emeralds >= price;
    var html = "<b class='tip-name'>" + itemName(k) + '</b>';
    if (k == 'milk') {
        html += "<span class='tip-text'>Drink it before a round: no potion hits you that round. " +
            s.me.milk + ' in hand, ' + s.me.milk_left + ' left to buy.</span>';
    } else {
        html += "<span class='tip-effect " + (k == 'regeneration' ? 'good' : 'bad') + "'>" + POTIONS[k][0] + '</span>' +
            "<span class='tip-text'>" + potionText(k, hardcore()) + '</span>';
    }
    html += price === undefined ? "<span class='tip-price no'>✖ Out of stock</span>"
        : "<span class='tip-price " + (ok ? 'ok' : 'no') + "'>" + (ok ? '✔' : '✖') + ' Price: ' + price + emeraldIcon() + '</span>';
    box.html(html).prop('hidden', false);
}

// who a potion can go to: the players still standing, or yourself
function targets(k) {
    var box = $('#shop-targets'), html;
    if (!s.me) {
        html = '';
    } else if (!k) {
        var prices = Object.keys(s.wares || {}).map(function (w) { return s.wares[w]; });
        html = "<p class='shop-hint'>" + (prices.length && s.me.emeralds >= Math.min.apply(null, prices) ? 'Pick a potion.' : 'Not enough emeralds for anything.') + '</p>';
    } else if (SELF.indexOf(k) >= 0) {
        html = "<p class='shop-hint'>For you.</p><button type='button' class='btn wide shop-buy' data-buy='" + k + "'>" +
            (k == 'milk' ? 'Buy it' : 'Drink it') + '</button>';
    } else {
        html = "<p class='shop-hint'>Throw it at:</p>" + standingNow().filter(function (p) { return !p.you; }).map(function (p) {
            return "<button type='button' class='shop-target' data-buy='" + k + "' data-target='" + p.uid + "'>" + dot(p) +
                "<span class='shop-name'>" + esc(p.name) + '</span>' + bottles(p.effects || {}) + "<span class='shop-life'>" + lifeLeft(p.left) + '</span></button>';
        }).join('');
    }
    if (html != targetsHtml) {
        box.html(html);
        targetsHtml = html;
    }
    box.find('button').prop('disabled', !!(me() && me().ready));
}

$('#shop-slots').on('click', '.shop-slot', function () {
    shopPick = $(this).data('item');
    Sfx.play('click');
    shop();
}).on('mouseenter', '.shop-slot', function () {
    tip($(this).data('item'));
}).on('mouseleave', function () {
    tip(shopPick);
});

$('#shop-targets').on('click', '[data-buy]', function () {
    buy($(this).data('buy'), $(this).data('target'));
});

// paid at once if the emeralds are there: the merchant says yes; if not, no
function buy(item, target) {
    var price = (s.wares || {})[item];
    if (price === undefined || s.me.emeralds < price) {
        refuse(price === undefined ? 'Out of stock' : 'Not enough emeralds');
        return;
    }
    send('buy', {round: s.round, item: item, target: target || ''}).done(function (r) {
        if (r.success) {
            Sfx.play('sold');
            s.me.emeralds = r.emeralds;
            $('#shop-purse b').text(r.emeralds);
            replay(document.querySelector('.shop-slot[data-item="' + item + '"]'), 'bought');
        } else {
            refuse(r.error);
        }
    }).fail(function () {
        refuse('Connection problem, try again');
    });
}

function refuse(text) {
    Sfx.play('refused');
    replay(document.getElementById('shop-purse'), 'refused');
    shopSays = {text: text || 'Not enough emeralds', until: Date.now() + 2500};
    shop();
}

$('#ready-button').on('click', function () {
    $(this).prop('disabled', true);
    Sfx.play('click');
    send('ready', {round: s.round});
});
