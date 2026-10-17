// What moves in a game (solo and rooms), on top of the drawings of style.css
// ("Motion"). Only on an event of the game, never on a redraw: rooms redraw
// every second, so the callers ask for a motion when the state changes.

var REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// Toasts, as in Minecraft: a small board slides in from the corner, says one
// thing, and goes. For what happens out of sight: someone joined, the host
// changed, a new level. group: a toast of the same group still on screen is
// updated instead ("Anna and 2 more joined"), so a big lobby filling up makes
// one toast, not ten.
var TOAST_TIME = 3500;   // ms on screen
var TOAST_MAX = 3;       // on screen at once; the oldest goes first

function toast(text, icon, group) {
    var box = document.getElementById('toasts');
    if (!box) {
        box = document.createElement('div');
        box.id = 'toasts';
        box.className = 'toasts';
        document.body.appendChild(box);
    }
    var old = group && box.querySelector('[data-group="' + group + '"]:not(.out)');
    if (old) {
        old.querySelector('span').innerHTML = text;
        clearTimeout(old.timer);
        old.timer = setTimeout(function () { toastOut(old); }, TOAST_TIME);
        return old;
    }
    var shown = box.querySelectorAll('.toast:not(.out)');
    if (shown.length >= TOAST_MAX) {
        toastOut(shown[0]);
    }
    var el = document.createElement('div');
    el.className = 'toast';
    if (group) {
        el.setAttribute('data-group', group);
    }
    el.innerHTML = (icon || '') + '<span>' + text + '</span>';
    box.appendChild(el);
    el.timer = setTimeout(function () { toastOut(el); }, TOAST_TIME);
    return el;
}

function toastOut(el) {
    clearTimeout(el.timer);
    el.classList.add('out');
    setTimeout(function () { el.remove(); }, 220);
}

function toastIcon(name) {
    return "<i class='material-icons'>" + name + "</i>";
}

// plays a CSS animation of an element again from the start: a stamp, a sign
// that swings once more
function replay(el, name) {
    if (!el) {
        return;
    }
    if (name) {
        el.classList.remove(name);
        void el.offsetWidth;
        el.classList.add(name);
    } else {
        el.style.animation = 'none';
        void el.offsetWidth;
        el.style.animation = '';
    }
}

// a pin put on a map falls into place (land: from higher, for the reveals)
function drop(marker, land) {
    var el = marker.getElement && marker.getElement();
    if (el) {
        el.classList.add(land ? 'pin-land' : 'pin-drop');
    }
}

// a line drawn from a to b, quick at first, slowing down at the end
function drawLine(line, a, b, ms) {
    var start = Date.now();
    var step = function () {
        var t = REDUCED ? 1 : Math.min(1, (Date.now() - start) / ms), e = 1 - Math.pow(1 - t, 3);
        line.setLatLngs([a, L.latLng(a.lat + (b.lat - a.lat) * e, a.lng + (b.lng - a.lng) * e)]);
        if (t < 1) {
            requestAnimationFrame(step);
        }
    };
    step();
}

// the light crosses an element once (the winner's line): drawn in a frame
// laid over it, inside box, the positioned block around it
function shine(el, box) {
    if (!el || REDUCED) {
        return;
    }
    var r = el.getBoundingClientRect(), p = box.getBoundingClientRect();
    var frame = document.createElement('div');
    frame.className = 'shine-box';
    frame.style.cssText = 'left:' + (r.left - p.left) + 'px;top:' + (r.top - p.top) + 'px;width:' + r.width + 'px;height:' + r.height + 'px';
    frame.innerHTML = "<i class='row-shine'></i>";
    box.appendChild(frame);
    setTimeout(function () { frame.remove(); }, 1400);
}
