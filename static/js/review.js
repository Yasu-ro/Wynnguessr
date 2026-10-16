// Review of the locations: a dot per location (blue = planned, red = new
// capture, green = kept), a click opens it; keep it with a difficulty, or
// delete it. A click on the map plans a spot for the mod's tour. Captures
// from the mod appear by themselves, and a grey veil covers the chunks the
// downloaded world does not have.
var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
var COLORS = {planned: '#1e88e5', new: '#e53935', kept: '#378537'};
var CHUNKS_X = 288, CHUNKS_Z = 384;   // the map in chunks, from chunk (-160, -384)

var map = L.map('review-map', {crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, preferCanvas: true});
L.imageOverlay('static/map-2026.webp', bounds, {attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'}).addTo(map);
map.fitBounds(bounds);

var dots = {};      // location id -> circle marker
var places = {};    // location id -> location
var current = null; // location shown in the panel
var viewer = null;
var choice = {};    // province and difficulty picked in the panel
var have = null;    // chunks of the downloaded world: Uint8Array, 1 = there
var veil = null, veilData = '';
var rings = [];     // one circle per group of holes, visible at any zoom

function style(loc) {
    var on = current && current.id == loc.id;
    return {radius: on ? 9 : 6, color: on ? 'white' : 'black', weight: on ? 3 : 1,
            fillColor: COLORS[loc.review], fillOpacity: 1, bubblingMouseEvents: false};
}

function counts() {
    var n = {planned: 0, new: 0, kept: 0};
    Object.values(places).forEach(function (l) { if (l.review in n) n[l.review]++; });
    for (var k in n) document.getElementById('count-' + k).textContent = n[k];
}

function load() {
    fetch('api/review').then(function (r) { return r.json(); }).then(function (list) {
        var seen = {};
        list.forEach(function (loc) {
            seen[loc.id] = true;
            places[loc.id] = loc;
            if (!dots[loc.id]) {
                dots[loc.id] = L.circleMarker([-loc.Z, loc.X], style(loc)).addTo(map)
                    .on('click', function () { open(places[loc.id]); });
            } else {
                dots[loc.id].setStyle(style(loc));
            }
        });
        for (var id in dots) {
            if (!seen[id]) { map.removeLayer(dots[id]); delete dots[id]; delete places[id]; }
        }
        counts();
    });
    fetch('api/review/coverage').then(function (r) { return r.text(); }).then(function (text) {
        if (text != veilData) { veilData = text; drawVeil(JSON.parse(text)); }
    });
}

function drawVeil(regions) {
    if (veil) { map.removeLayer(veil); veil = null; }
    rings.forEach(function (r) { map.removeLayer(r); });
    rings = [];
    if (!regions) { have = null; return; }
    have = new Uint8Array(CHUNKS_X * CHUNKS_Z);
    for (var key in regions) {
        var rx = +key.split(',')[0], rz = +key.split(',')[1];
        var bits = atob(regions[key]);
        for (var i = 0; i < 1024; i++) {
            if (!(bits.charCodeAt(i >> 3) & (1 << (i & 7)))) continue;
            var cx = rx * 32 + (i & 31) + 160, cz = rz * 32 + (i >> 5) + 384;
            if (cx >= 0 && cx < CHUNKS_X && cz >= 0 && cz < CHUNKS_Z) have[cz * CHUNKS_X + cx] = 1;
        }
    }
    // holes: missing chunks walled in by downloaded ones, i.e. not reachable
    // from the edge of the map through other missing chunks
    var outside = new Uint8Array(have.length), todo = [];
    for (var x = 0; x < CHUNKS_X; x++) todo.push(x, (CHUNKS_Z - 1) * CHUNKS_X + x);
    for (var z = 0; z < CHUNKS_Z; z++) todo.push(z * CHUNKS_X, z * CHUNKS_X + CHUNKS_X - 1);
    while (todo.length) {
        var c = todo.pop();
        if (have[c] || outside[c]) continue;
        outside[c] = 1;
        var cx = c % CHUNKS_X;
        if (cx > 0) todo.push(c - 1);
        if (cx < CHUNKS_X - 1) todo.push(c + 1);
        if (c >= CHUNKS_X) todo.push(c - CHUNKS_X);
        if (c < have.length - CHUNKS_X) todo.push(c + CHUNKS_X);
    }
    var canvas = document.createElement('canvas');
    canvas.width = CHUNKS_X; canvas.height = CHUNKS_Z;
    var ctx = canvas.getContext('2d'), img = ctx.createImageData(CHUNKS_X, CHUNKS_Z);
    for (var j = 0; j < have.length; j++) {
        if (have[j]) continue;
        if (outside[j]) {
            img.data[j * 4 + 3] = 140;   // black at 55%: not downloaded
        } else {
            img.data[j * 4] = 255; img.data[j * 4 + 2] = 255; img.data[j * 4 + 3] = 230;   // magenta: a hole
        }
    }
    ctx.putImageData(img, 0, 0);
    // a hole is a chunk or two: too small to see from far, so circle each group
    var seen = new Uint8Array(have.length);
    for (var h = 0; h < have.length; h++) {
        if (have[h] || outside[h] || seen[h]) continue;
        var group = [h], sx = 0, sz = 0, n = 0;
        seen[h] = 1;
        while (group.length) {
            var g = group.pop(), gx = g % CHUNKS_X;
            sx += gx; sz += (g - gx) / CHUNKS_X; n++;
            [gx > 0 ? g - 1 : -1, gx < CHUNKS_X - 1 ? g + 1 : -1, g - CHUNKS_X, g + CHUNKS_X].forEach(function (q) {
                if (q >= 0 && q < have.length && !have[q] && !outside[q] && !seen[q]) { seen[q] = 1; group.push(q); }
            });
        }
        var bx = (sx / n - 160 + 0.5) * 16, bz = (sz / n - 384 + 0.5) * 16;
        rings.push(L.circleMarker([-bz, bx], {radius: 12, color: '#ff00ff', weight: 3, fill: false, interactive: false}).addTo(map));
    }
    veil = L.imageOverlay(canvas.toDataURL(), bounds, {className: 'review-veil'}).addTo(map);
}

// a spot can only be planned where the world is downloaded: elsewhere the
// game would make up plain Minecraft terrain
function plannable(x, z) {
    var cx = Math.floor(x / 16) + 160, cz = Math.floor(z / 16) + 384;
    if (cx < 0 || cx >= CHUNKS_X || cz < 0 || cz >= CHUNKS_Z) return false;
    return !have || have[cz * CHUNKS_X + cx] == 1;
}

map.on('click', function (e) {
    var x = Math.round(e.latlng.lng), z = Math.round(-e.latlng.lat);
    if (!plannable(x, z)) return;
    fetch('api/review/plan', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({x: x, z: z})}).then(load);
});

function pick(kind, value) {
    choice[kind] = value;
    document.querySelectorAll('[data-' + kind + ']').forEach(function (b) {
        b.classList.toggle('picked', b.dataset[kind] == value);
    });
    document.getElementById('review-keep').disabled = !choice.difficulty;
}

function open(loc) {
    var before = current;
    current = loc;
    if (before && places[before.id]) dots[before.id].setStyle(style(places[before.id]));
    dots[loc.id].setStyle(style(loc)).bringToFront();
    var panel = document.getElementById('review-panel');
    panel.hidden = false;
    panel.dataset.review = loc.review;
    map.invalidateSize();
    document.getElementById('review-coords').textContent = 'X ' + Math.round(loc.X) + '   Z ' + Math.round(loc.Z);
    pick('province', loc.province);
    pick('difficulty', loc.difficulty);
    if (viewer) { viewer.destroy(); viewer = null; }
    if (loc.review != 'planned') {
        viewer = pannellum.viewer('review-panorama', {type: 'equirectangular', panorama: loc.url, autoLoad: true});
    }
}

function send(action) {
    var loc = current;
    fetch('api/review/' + loc.id, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: action, province: choice.province, difficulty: choice.difficulty})})
        .then(function (r) { return r.json(); }).then(function (res) {
            if (!res.success) return;
            if (action == 'delete') {
                document.getElementById('review-panel').hidden = true;
                map.invalidateSize();
                if (viewer) { viewer.destroy(); viewer = null; }
                current = null;
            }
            load();
        });
}

document.querySelectorAll('[data-province]').forEach(function (b) {
    b.onclick = function () { pick('province', b.dataset.province); };
});
document.querySelectorAll('[data-difficulty]').forEach(function (b) {
    b.onclick = function () { pick('difficulty', b.dataset.difficulty); };
});
document.getElementById('review-keep').onclick = function () { send('keep'); };
document.getElementById('review-delete').onclick = function () {
    if (confirm('Delete this location?')) send('delete');
};

load();
setInterval(load, 10000);
