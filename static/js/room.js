// Multiplayer room. The server runs the game (rounds, timers, scores); this
// page asks it for the state every second and redraws a screen only when the
// screen changes.
var code = $('#room').attr('data-code');
var COLORS = ['#e6194b', '#4363d8', '#ffe119', '#911eb4', '#f58231', '#42d4f4', '#f032e6', '#9a6324'];
var ANSWER = '#3cb44b';
var bounds = [[159, -2383], [6573, 1651]]; // Map bounds
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

$(document).ready(function () {
    setNav();
    poll();
    setInterval(clocks, 200);
});
$(window).on('resize', setNav);

// ---------- server ----------

function poll() {
    clearTimeout(pollTimer);
    if (polling) {
        pollAgain = true;
        return;
    }
    polling = true;
    $.ajax({url: 'api/room/' + code + (cur ? '?round=' + cur : ''), dataType: 'json', timeout: 8000})
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

function send(action, data) {
    var req = $.ajax({url: 'api/room/' + code + '/' + action, type: 'POST', data: data, dataType: 'json', timeout: 8000});
    req.always(poll);
    return req;
}

function render(data) {
    if (!data.success) {
        // logged out, or the room is gone: the page itself will say which
        location.reload();
        return;
    }
    s = data;
    if (s.next && s.live && s.state == 'finished') {
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
    } else if (s.reveal) {
        reveal();
    } else {
        guess();
    }
}

// ---------- helpers ----------

function setNav() {
    document.documentElement.style.setProperty('--nav', $('.navbar').outerHeight() + 'px');
}

function show(id) {
    ['lobby', 'guess-screen', 'reveal-screen', 'results'].forEach(function (x) {
        $('#' + x).prop('hidden', x != id);
    });
    var playing = id == 'guess-screen' || id == 'reveal-screen';
    $('body').toggleClass('room-playing', playing);
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
    L.imageOverlay('static/Wynncraft Map.png', bounds, {attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'}).addTo(m);
    m.setView([3000, -500], zoom);
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

// ---------- modes ----------
// duel: health points; royale: lives. Both come from the server (left, out,
// delta) for the contestants (seat) after the last finished round.

var MODE_NAMES = {classic: 'Classic', duel: 'Duel', royale: 'Battle Royale'};
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
    return s.mode == 'duel' ? health(p) + p.left.toLocaleString('en-US') : hearts(p.left);
}

// what the last round did to them
function change(p) {
    if (!p.delta) {
        return '';
    }
    if (s.mode == 'duel') {
        return " <span class='room-loss'>" + p.delta.toLocaleString('en-US') + "</span>";
    }
    return p.delta < 0 ? " <span class='room-loss'>-1</span>" : " <span class='room-gain'>+1</span>";
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
        return "<div class='room-player" + (p.here ? '' : ' away') + "'>" + dot(p) + esc(p.name) +
            (p.host ? "<i class='material-icons' title='Host'>star</i>" : '') + "</div>";
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
    var key = 'guess' + s.round;
    var watching = s.live && !s.playing;
    if (view != key) {
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
        map.on('click', function (e) {
            if (submitted || (s.live && !s.playing)) {
                return;
            }
            if (marker) {
                map.removeLayer(marker);
            }
            marker = L.marker(e.latlng, {icon: pin(color(me()))}).addTo(map);
            $('#guess-button').removeClass('room-warn').text('Guess!');
        });

        if (viewer) {
            viewer.destroy();
        }
        var locked = s.settings.look;
        viewer = pannellum.viewer('room-panorama', {
            "type": "equirectangular",
            "panorama": s.url,
            "autoLoad": true,
            "draggable": !locked,
            "mouseZoom": !locked,
            "keyboardZoom": !locked,
            "disableKeyboardCtrl": locked,
            "showControls": !locked
        });
        $('#guess-button').prop('disabled', false).removeClass('room-warn').text('Guess!');
    }
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
    $('#hud-players').html(!s.live ? '' : inRound.map(function (p) {
        return "<span class='room-hud-player'>" + dot(p) + esc(p.name) +
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
    var key = view, data = {round: s.round};
    if (marker) {
        data.x = marker.getLatLng().lng;
        data.z = -marker.getLatLng().lat;
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
    if (view.indexOf('guess') == 0) {
        if (deadline === null) {
            $('#hud-time').empty();
        } else {
            var left = Math.max(0, (deadline - Date.now()) / 1000);
            $('#hud-time').html("<i class='material-icons'>timer</i>" + clock(left)).toggleClass('urgent', left <= 10);
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
    var key = 'reveal' + s.round;
    if (view != key) {
        view = key;
        show('reveal-screen');
        nextAt = null;
        if (revealMap) {
            revealMap.remove();
        }
        revealMap = makeMap('reveal-map', -1);
        var answer = [-s.reveal.Z, s.reveal.X];
        var group = [L.marker(answer, {icon: pin(ANSWER, true), zIndexOffset: 1000}).addTo(revealMap)];
        s.reveal.guesses.forEach(function (g) {
            var p = player(g.name);
            if (g.x === null || !p) {
                return;
            }
            var pos = [-g.z, g.x];
            L.polyline([answer, pos], {color: color(p), weight: 3, dashArray: '8 6'}).addTo(revealMap);
            group.push(L.marker(pos, {icon: pin(color(p))}).addTo(revealMap)
                .bindTooltip(esc(g.name), {permanent: true, direction: 'top', className: 'room-tip'}));
        });
        revealMap.fitBounds(L.featureGroup(group).getBounds(), {padding: [60, 60], maxZoom: 1});
    }

    var you = me();
    var mine = s.reveal.guesses.filter(function (g) { return g.name == you.name; })[0];
    var guessed = mine && mine.x !== null;
    var line = guessed ? '+' + points(mine.score) : 'No guess this round';
    if (guessed && mine.score >= BULLSEYE) {
        line = 'Bullseye! ' + line;
    }
    var bad = "<span class='room-loss'> · ", good = "<span class='room-gain'> · ";
    if (s.mode != 'classic' && you.seat && (you.out == null || you.out == s.round)) {
        if (you.out == s.round) {
            line += bad + "you're out!</span>";
        } else if (s.mode == 'duel') {
            line += you.delta ? bad + you.delta.toLocaleString('en-US') + ' HP</span>' : good + 'no damage</span>';
        } else if (you.delta) {
            line += you.delta < 0 ? bad + 'you lose a life</span>' : good + 'a life back!</span>';
        }
    }
    $('#reveal-title').text(s.mode == 'classic' ? 'Round ' + s.round + '/' + s.rounds
        : 'Round ' + s.round + (s.mode == 'duel' && s.multiplier > 1 ? ' · damage ×' + s.multiplier : ''));
    $('#reveal-mine').html(line).toggleClass('none', !guessed).toggleClass('room-bullseye', guessed && mine.score >= BULLSEYE);
    $('#reveal-total').text({classic: 'Total', duel: 'HP', royale: 'Lives'}[s.mode]);

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
    $('#reveal-rows').html(rows.map(function (r) {
        var gone = r.p.out != null && r.p.out < s.round, last;
        if (s.mode == 'classic') {
            last = r.total.toLocaleString('en-US');
        } else if (gone) {
            last = 'Out';
        } else if (r.p.out == s.round) {
            last = (s.mode == 'royale' ? hearts(0) + ' ' : '') + "<span class='room-loss'>Out!</span>";
        } else if (s.mode == 'duel') {
            last = '<div>' + r.p.left.toLocaleString('en-US') + change(r.p) + '</div>' + health(r.p);
        } else {
            last = hearts(r.p.left) + change(r.p);
        }
        return "<tr class='" + (r.p.you ? 'you' : '') + (gone ? ' room-out' : '') + "'><td>" + dot(r.p) + esc(r.p.name) + "</td>" +
            "<td class='num'>" + (r.score >= 0 ? '+' + r.score.toLocaleString('en-US') : '-') + "</td>" +
            "<td class='num'>" + last + "</td></tr>";
    }).join(''));

    if (s.next_in !== undefined) {
        nextAt = Date.now() + s.next_in * 1000;
    }
    nextButton();
}

// is the round on display the last one?
function lastRound() {
    return s.round >= s.rounds || (s.mode != 'classic' && standingNow().length <= 1);
}

function nextButton() {
    var b = $('#next-button'), label = lastRound() ? 'See Results' : 'Next Round';
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
    var rank = 0;
    $('#results-rows').html(rows.map(function (p, i) {
        if (i == 0 || !same(p, rows[i - 1])) {
            rank = i + 1;
        }
        var place = rank <= 3 ? "<i class='material-icons' style='color:" + medals[rank - 1] + "'>emoji_events</i>" : rank;
        var v = value(p);
        return "<tr class='leaderboard-row" + (p.you ? ' you' : '') + "'><td>" + place + "</td>" +
            "<td class='room-name'>" + dot(p) + esc(p.name) + v[0] + "</td>" +
            "<td>" + v[1] + "</td></tr>";
    }).join(''));

    var title = 'Results';
    if (rows.length > 1 && same(rows[0], rows[1])) {
        title = 'Draw!';
    } else if (rows.length > 1) {
        title = rows[0].you ? 'You Win!' : rows[0].name + ' Wins!';
    }
    $('#results-title').text(title);
    $('#results-score').text({classic: 'Score', duel: 'HP', royale: 'Lives'}[s.mode]);
    $('#results-replay').prop('hidden', s.mode != 'classic');
    $('#again-button').prop('hidden', !(s.live && s.host));
    var host = s.players.filter(function (p) { return p.host; })[0];
    $('#results-hint').text(s.live && !s.host && host ? 'If ' + host.name + ' starts a new game, you will follow automatically.' : '');
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
