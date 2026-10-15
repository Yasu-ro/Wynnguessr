var code = $('#room-variables').attr('code');
var timeLimit = Number($('#room-variables').attr('timeLimit'));
var look = $('#room-variables').attr('look') === 'True';
var bounds = [[159, -2383], [6573, 1651]]; // Map bounds
var view = '';           // what is currently drawn, to redraw only on change
var cur = 0;             // round shown to a player who is not playing live
var finished = false;    // a non-live player clicked "See results"
var marker = null;
var submitted = false;
var timer = null;
var greenIcon = new L.Icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});

$(document).ready(poll);

// The room state is polled every second; each screen is drawn once per round
function poll() {
    $.getJSON('/api/room/' + code + (cur ? '?round=' + cur : ''))
        .done(render)
        .always(function () { setTimeout(poll, 1000); });
}

function render(s) {
    if (!s.success) {
        location.href = '/';
        return;
    }
    if (!s.live && !cur) {
        cur = s.round;
    }
    var me = s.players.find(p => p.you);
    $('#totalScore').text('Score: ' + me.total);
    $('#round-number').text('Round: ' + s.round + '/' + s.rounds);

    if (s.live && s.state == 'waiting') {
        lobby(s);
    } else if (s.live ? s.state == 'finished' : finished) {
        results(s);
    } else if (!s.guesses) {
        guess(s);
    } else {
        reveal(s);
    }
}

function show(id) {
    ['room-screen', 'guess-screen', 'score-screen'].forEach(function (s) {
        document.getElementById(s).style.display = (s == id) ? '' : 'none';
    });
}

function makeMap(id, zoom) {
    var m = L.map(id, {
        crs: L.CRS.Simple,
        minZoom: -3,
        maxZoom: 5,
        attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'
    });
    L.imageOverlay('static/Wynncraft Map.png', bounds).addTo(m);
    m.setView([3000, -500], zoom);
    return m;
}

function esc(text) {
    return $('<div>').text(text).html();
}

function playerList(s) {
    return s.players.map(function (p) {
        var line = esc(p.username) + ' — ' + p.total;
        if (p.played < s.rounds) {
            line += ' (' + p.played + '/' + s.rounds + ')';
        }
        return '<li>' + line + '</li>';
    }).join('');
}

// Waiting room: invite link, who is in, start button for the host
function lobby(s) {
    if (view != 'lobby') {
        view = 'lobby';
        show('room-screen');
        $('#room-screen').html(
            "<h2>Room</h2>" +
            "<p>Invite link:</p>" +
            "<input id='invite' class='room-invite' readonly>" +
            "<ul id='room-players' class='room-players'></ul>" +
            "<button id='room-button' class='next-button room-button'></button>");
        $('#invite').val(location.href).click(function () { this.select(); });
        $('#room-button').click(function () { $.post('/api/room/' + code + '/start'); });
    }
    $('#room-players').html(s.players.map(p => '<li>' + esc(p.username) + '</li>').join(''));
    $('#room-button').text(s.host ? 'Start' : 'Waiting for the host to start...').prop('disabled', !s.host);
}

function guess(s) {
    if (view == 'guess' + s.round) {
        if (submitted) {
            $('#guess-button').text('Waiting for other players...');
        }
        return;
    }
    view = 'guess' + s.round;
    show('guess-screen');
    marker = null;
    submitted = s.answered;
    $('#guess-screen').html(
        "<div id='game-panorama'></div>" +
        "<div class='map-container' id='map-container'>" +
            "<div class='map' id='map'></div>" +
            "<button id='guess-button' class='guess-button'>Guess!</button></div>");

    var map = makeMap('map', -2);
    map.on('click', function (e) {
        if (submitted) {
            return;
        }
        if (marker) {
            map.removeLayer(marker);
        }
        marker = L.marker(e.latlng).addTo(map);
    });
    $('#guess-button').click(function () {
        if (!marker) {
            $(this).text('Select a location first!').css('background-color', 'red');
            return;
        }
        submit(s.round);
    });

    pannellum.viewer('game-panorama', {
        "type": "equirectangular",
        "panorama": s.url,
        "autoLoad": true,
        "draggable": !look,
        "mouseZoom": !look,
        "keyboardZoom": !look,
        "disableKeyboardCtrl": look,
        "showControls": !look
    });

    // live: the server's clock decides; otherwise the countdown starts now
    clearInterval(timer);
    var left = s.live ? s.time_left : timeLimit;
    if (left !== undefined && left > 0) {
        var deadline = Date.now() + left * 1000;
        timer = setInterval(function () {
            var remaining = (deadline - Date.now()) / 1000;
            $('#time-left').text('Time: ' + Math.max(0, remaining).toFixed(1));
            if (remaining <= (s.live ? 0.5 : 0)) {
                clearInterval(timer);
                submit(s.round);
            }
        }, 100);
    }
    if (submitted) {
        $('#guess-button').text('Waiting for other players...');
    }
}

function submit(round) {
    if (submitted) {
        return;
    }
    submitted = true;
    clearInterval(timer);
    var data = {'round': round};
    if (marker) {
        data.x = marker.getLatLng().lng;
        data.z = -marker.getLatLng().lat;
    }
    $('#guess-button').text('Waiting for other players...').css('background-color', '');
    $.post('/api/room/' + code + '/guess', data);
}

// End of a round: the answer and everyone's guess
function reveal(s) {
    if (view != 'reveal' + s.round) {
        view = 'reveal' + s.round;
        clearInterval(timer);
        show('score-screen');
        $('#score-screen').html(
            "<div class='score-map' id='scoreMap'></div>" +
            "<div id='score-container'>" +
            "<p id='round-scores' class='score-info room-scores'></p>" +
            "<button id='next-button' class='next-button'></button></div>");

        var scoreMap = makeMap('scoreMap', -1);
        var answer = [-s.answer.Z, s.answer.X];
        var group = [L.marker(answer, { icon: greenIcon }).addTo(scoreMap)];
        s.guesses.forEach(function (g) {
            if (g.x === null) {
                return;
            }
            var pos = [-g.z, g.x];
            group.push(L.marker(pos).addTo(scoreMap)
                .bindTooltip(esc(g.username) + ': ' + g.score, { permanent: true, direction: 'top', offset: [-15, -30] }));
            L.polyline([answer, pos], { color: 'red' }).addTo(scoreMap);
        });
        scoreMap.fitBounds(L.featureGroup(group).getBounds(), { padding: [50, 50] });

        var last = s.round >= s.rounds;
        $('#next-button').click(function () {
            if (s.live) {
                $.post('/api/room/' + code + '/start');
            } else if (last) {
                finished = true;
                results(s);
            } else {
                cur = s.round + 1;
            }
        });
        if (!s.live || s.host) {
            $('#next-button').text(last ? 'See results' : 'Next location');
        } else {
            $('#next-button').text('Waiting for the host...').prop('disabled', true);
        }
    }
    // late players' guesses keep coming in
    $('#round-scores').html(s.guesses.map(g => esc(g.username) + ': ' + g.score).join(' &nbsp;·&nbsp; '));
}

function results(s) {
    if (view != 'results') {
        view = 'results';
        clearInterval(timer);
        show('room-screen');
        $('#room-screen').html(
            "<h2>Results</h2>" +
            "<ol id='room-players' class='room-players'></ol>" +
            "<p>Invite link (others can still play these locations):</p>" +
            "<input id='invite' class='room-invite' readonly>" +
            "<a href='/mode'><button class='next-button room-button'>Play again</button></a>");
        $('#invite').val(location.href).click(function () { this.select(); });
    }
    $('#room-players').html(playerList(s));
}
