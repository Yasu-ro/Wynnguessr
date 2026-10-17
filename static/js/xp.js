// Levels, for the end screens of a game alone (game.js) and of a room
// (room.js). Level L takes 50·L·(L−1) XP in all, each level 100 XP more than
// the one before: the same formula as level_of() in app.py.

function levelOf(xp) {
    return Math.floor((5 + Math.sqrt(25 + 2 * xp)) / 10);
}

function levelXp(level) {
    return 50 * level * (level - 1);
}

// the bar, Minecraft style: the level in the middle, filled with the way to the next one
function showXp(box, xp, level) {
    level = level || levelOf(xp);
    box.querySelector('.xp-level').textContent = level;
    box.querySelector('.xp-fill').style.width = Math.min(100, (xp - levelXp(level)) / (levelXp(level + 1) - levelXp(level)) * 100) + '%';
}

// what a game brought: "+185 XP", then the bar fills up from the old total,
// with a pop and a chime at each new level. notes: lines under it (a win, a streak)
function xpGain(slot, total, gained, notes) {
    var from = total - gained;
    slot.innerHTML = "<div class='xp-panel'><p class='xp-gain'>+<span>0</span> XP</p>" +
        "<div class='xp'><div class='xp-bar'><span class='xp-fill'></span></div><b class='xp-level'></b></div>" +
        "<p class='xp-up' hidden></p>" + (notes || []).map(function (n) { return "<p class='xp-note'>" + n + "</p>"; }).join('') + "</div>";
    var panel = slot.firstChild, count = panel.querySelector('.xp-gain span');
    var up = panel.querySelector('.xp-up'), badge = panel.querySelector('.xp-level');
    var levelUp = function (level) {
        up.hidden = false;
        up.textContent = 'Level ' + level + '!';
        badge.textContent = level;
        badge.classList.remove('pop');
        void badge.offsetWidth;  // restart the animation
        badge.classList.add('pop');
    };
    showXp(panel, from);
    if (gained <= 0 || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        showXp(panel, total);
        menu(total);
        count.textContent = gained.toLocaleString('en-US');
        if (levelOf(total) > levelOf(from)) {
            up.hidden = false;
            up.textContent = 'Level ' + levelOf(total) + '!';
        }
        return;
    }
    // the way up, cut at each new level: the bar fills, the level pops, the bar starts again
    var stops = [];
    for (var l = levelOf(from) + 1; levelXp(l) <= total; l++) {
        stops.push(levelXp(l));
    }
    stops.push(total);
    var time = Math.min(2600, 700 + gained * 6);  // ms of filling, pauses aside
    var i = 0, start = from, level = levelOf(from), t0 = null, tick = 0;
    var frame = function (now) {
        if (t0 === null) {
            t0 = now;
        }
        var end = stops[i], last = i == stops.length - 1;
        var k = end > start ? Math.min(1, (now - t0) / ((end - start) / gained * time)) : 1;
        var xp = start + (end - start) * (last ? 1 - Math.pow(1 - k, 3) : k);  // the last stretch slows down
        showXp(panel, xp, level);
        count.textContent = Math.round(xp - from).toLocaleString('en-US');
        if (now - tick > 100 && k < 1) {
            tick = now;
            xpSound('orb');
        }
        if (k < 1) {
            requestAnimationFrame(frame);
        } else if (last) {
            menu(total);
        } else {
            // full: one level up, then the bar starts again from empty
            level++;
            levelUp(level);
            xpSound('level', level);
            i++;
            start = end;
            setTimeout(function () {
                t0 = null;
                showXp(panel, start, level);
                requestAnimationFrame(frame);
            }, 450);
        }
    };
    setTimeout(function () { requestAnimationFrame(frame); }, 500);
}

// the level in the menu catches up with the bar
function menu(xp) {
    var level = levelOf(xp), badge = document.querySelector('.pill-level'), line = document.querySelector('.pill-xp');
    if (badge && line) {
        badge.textContent = level;
        line.style.width = (xp - levelXp(level)) / (levelXp(level + 1) - levelXp(level)) * 100 + '%';
    }
}

// a little bell at a random pitch for each bit of XP, like an orb picked up
// in Minecraft; a short rising chime for a new level, longer every five
// levels. Muted with the room's sound button.
var xpAudio = null;
function xpSound(kind, level) {
    try {
        if (localStorage.getItem('wynnguessr-muted') == '1') {
            return;
        }
        xpAudio = xpAudio || new (window.AudioContext || window.webkitAudioContext)();
        if (xpAudio.state == 'suspended') {
            xpAudio.resume();
        }
    } catch (e) {
        return;
    }
    var t = xpAudio.currentTime;
    var note = function (freq, at, length, volume, type) {
        var osc = xpAudio.createOscillator(), gain = xpAudio.createGain();
        osc.type = type || 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, t + at);
        gain.gain.exponentialRampToValueAtTime(volume, t + at + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + at + length);
        osc.connect(gain).connect(xpAudio.destination);
        osc.start(t + at);
        osc.stop(t + at + length + 0.05);
    };
    if (kind == 'orb') {
        var f = 1400 * (0.55 + Math.random() * 0.7);
        note(f, 0, 0.12, 0.05);
        note(f * 2.4, 0, 0.07, 0.015);
    } else {
        (level % 5 == 0 ? [523, 659, 784, 1047, 1319] : [523, 659, 784]).forEach(function (f, n) {
            note(f, n * 0.09, 0.4, 0.1, 'triangle');
        });
    }
}
