// The game's sounds: Minecraft's own, in static/sounds (fetched by
// tools/sounds.py, not in git). Each file is loaded once and always played
// whole; the old beeps were made of notes faded out by hand, and could be
// cut. One switch mutes them all (the volume button), kept by the browser.
// Browsers only let a page make sound after a first click or key.

// name: how many versions (one is picked at random each time). Same names
// and counts as tools/sounds.py
var SOUNDS = {pin: 3, guess: 1, other: 1, round: 3, warn: 1, tick: 1, perfect: 1, hurt: 3, out: 1,
              win: 1, lose: 3, join: 1, start: 2, orb: 1, level: 1, click: 1, note: 1, good: 1, bad: 1, bubble: 1, toast: 1, fuse: 1, boom: 4};
// how loud each one is next to the others: small sounds stay small
var LOUD = {pin: .45, guess: .5, other: .3, round: .3, warn: .45, tick: .4, perfect: .6, hurt: .55, out: .6,
            win: .5, lose: .55, join: .4, start: .35, orb: .3, level: .5, click: .35, note: .35, good: .45, bad: .45,
            bubble: .25, toast: .4, fuse: .55, boom: .6};
var SOUND_GAP = 80;   // ms: the same sound asked again sooner is skipped, so nothing piles up
var SOUND_MAX = 14;   // sounds started in one second, at most (counted by the clock: a
                      // count of sounds still playing never went down while the
                      // audio was asleep, and the page fell silent for good)

var Sfx = (function () {
    var ctx = null, master = null, buffers = {}, last = {}, recent = [], muted = false;
    var woken = false;   // a click or key happened: sound may start
    try {
        muted = localStorage.getItem('wynnguessr-muted') == '1';
    } catch (e) {}

    function load(name, n) {
        var req = new XMLHttpRequest();
        req.open('GET', 'static/sounds/' + name + n + '.mp3');
        req.responseType = 'arraybuffer';
        req.onload = function () {
            if (req.status == 200) {
                ctx.decodeAudioData(req.response, function (buffer) {
                    (buffers[name] = buffers[name] || []).push(buffer);
                }, function () {});
            }
        };
        req.send();
    }

    // made at once (silent until the first click) so the files are ready in time
    try {
        ctx = new (window.AudioContext || window.webkitAudioContext)();
        master = ctx.createGain();
        master.gain.value = muted ? 0 : 1;
        master.connect(ctx.destination);
        Object.keys(SOUNDS).forEach(function (name) {
            for (var n = 1; n <= SOUNDS[name]; n++) {
                load(name, n);
            }
        });
        var wake = function () {
            woken = true;
            if (ctx.state == 'suspended') {
                ctx.resume();
            }
        };
        document.addEventListener('pointerdown', wake, true);
        document.addEventListener('keydown', wake, true);
    } catch (e) {
        ctx = null;
    }

    // pitch: 1 as recorded, 2 an octave up; volume: on top of LOUD
    function play(name, pitch, volume) {
        var list = buffers[name], now = Date.now();
        recent = recent.filter(function (t) { return now - t < 1000; });
        if (!ctx || !woken || muted || !list || document.hidden || recent.length >= SOUND_MAX || now - (last[name] || 0) < SOUND_GAP) {
            return;
        }
        last[name] = now;
        recent.push(now);
        // a sound asked by the very click that wakes the page waits for it, it is not lost
        if (ctx.state == 'suspended') {
            ctx.resume();
        }
        var source = ctx.createBufferSource(), gain = ctx.createGain();
        source.buffer = list[Math.floor(Math.random() * list.length)];
        source.playbackRate.value = pitch || 1;
        gain.gain.value = LOUD[name] * (volume === undefined ? 1 : volume);
        source.connect(gain);
        gain.connect(master);
        source.start();
    }

    function setMuted(on) {
        muted = on;
        try {
            localStorage.setItem('wynnguessr-muted', muted ? '1' : '0');
        } catch (e) {}
        if (master) {
            master.gain.value = muted ? 0 : 1;
        }
    }

    return {play: play, muted: function () { return muted; }, setMuted: setMuted};
})();

// a note block: 0 is the lowest note, 24 two octaves higher, as in Minecraft
function noteBlock(n) {
    return Math.pow(2, (n - 12) / 12);
}

// the Minecraft click on the game's buttons and choices (the Guess button has its own sound)
$(document).on('click', 'button:not(#guess-button), .btn, .chip, .tab', function () {
    Sfx.play('click');
});

// the volume button of the page, if it has one
$(function () {
    var show = function () {
        $('#sound-button i').text(Sfx.muted() ? 'volume_off' : 'volume_up');
    };
    show();
    $('#sound-button').on('click', function () {
        Sfx.setMuted(!Sfx.muted());
        show();
    });
});
