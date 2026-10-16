// Review of the locations: a dot per location (red = new capture, orange =
// original game, green = kept), a click opens it; keep it with a difficulty,
// or delete it. New captures from the mod appear by themselves.
var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
var COLORS = {new: '#e53935', old: '#f39c12', kept: '#378537'};

var map = L.map('review-map', {crs: L.CRS.Simple, minZoom: -3, maxZoom: 3, preferCanvas: true});
L.imageOverlay('static/map-2026.webp', bounds, {attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'}).addTo(map);
map.fitBounds(bounds);

var dots = {};      // location id -> circle marker
var places = {};    // location id -> location
var current = null; // location shown in the panel
var viewer = null;
var choice = {};    // province and difficulty picked in the panel

function style(loc) {
    var on = current && current.id == loc.id;
    return {radius: on ? 9 : 6, color: on ? 'white' : 'black', weight: on ? 3 : 1,
            fillColor: COLORS[loc.review], fillOpacity: 1};
}

function counts() {
    var n = {new: 0, old: 0, kept: 0};
    Object.values(places).forEach(function (l) { n[l.review]++; });
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
}

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
    document.getElementById('review-panel').hidden = false;
    map.invalidateSize();
    document.getElementById('review-coords').textContent = 'X ' + Math.round(loc.X) + '   Z ' + Math.round(loc.Z);
    pick('province', loc.province);
    pick('difficulty', loc.difficulty);
    if (viewer) viewer.destroy();
    viewer = pannellum.viewer('review-panorama', {type: 'equirectangular', panorama: loc.url, autoLoad: true});
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
