// Guessing a block. The panoramas are saved at the coordinates of the block the
// player stood on, and the map has one pixel per block: a guess is the block
// clicked, shown by its centre. Zoomed in, a frame shows the block under the
// pointer, so that the exact block (5,000 points) can be aimed at.

// the map itself, one pixel per block, cut in tiles (tools/map_tiles.py): a
// page loads only what it shows, not the whole 8.7 MB image
var MAP_BOUNDS = [[0, -2560], [6144, 2048]];
function mapTiles(m) {
    // the map grows under the mouse (style.css): told so, it loads the tiles of
    // its new size (the whole image used to be there anyway). pan: false keeps
    // it anchored at the top left, as it always grew
    if (window.ResizeObserver) {
        new ResizeObserver(function () { m.invalidateSize({pan: false}); }).observe(m.getContainer());
    }
    // the map's credit only (not Leaflet's flag and link), in another tab:
    // a click on it never leaves the game
    if (m.attributionControl) {
        m.attributionControl.setPrefix(false);
    }
    return L.tileLayer('static/map-2026/{z}/{x}_{y}.webp', {
        tileSize: 256, minZoom: -3, maxZoom: 5, minNativeZoom: -3, maxNativeZoom: 0, bounds: MAP_BOUNDS, noWrap: true,
        attribution: '<a href="https://wynntils.com/" target="_blank" rel="noopener">Wynntils Map</a>'
    }).addTo(m);
}

// The compass of the panoramas: N, E, S, W on the horizon (Yasuro: for the
// players who need it). Every location comes from the mod, which takes its
// pictures facing north: the cube's front is north, its right east. New
// objects for each panorama: Pannellum writes into them
function compass() {
    return [['N', 0], ['E', 90], ['S', 180], ['W', -90]].map(function (d) {
        return {pitch: 0, yaw: d[1], cssClass: 'compass-mark' + (d[0] == 'N' ? ' north' : ''),
                createTooltipFunc: function (div) { div.textContent = d[0]; }};
    });
}

// the block under a point of the map
function blockAt(latlng) {
    return {x: Math.floor(latlng.lng), z: Math.floor(-latlng.lat)};
}

// where a block is drawn on the map: its centre
function blockSpot(x, z) {
    return L.latLng(-z - 0.5, x + 0.5);
}

function blockCursor(m) {
    var frame = L.rectangle([[0, 0], [1, 1]], {color: '#000', weight: 2, opacity: .85, fill: false, interactive: false});
    var hide = function () {
        frame.remove();
    };
    m.on('mousemove', function (e) {
        if (m.getZoom() < 2) {
            return hide();
        }
        var b = blockAt(e.latlng);
        frame.setBounds([[-b.z - 1, b.x], [-b.z, b.x + 1]]);
        if (!m.hasLayer(frame)) {
            frame.addTo(m);
        }
    });
    m.on('mouseout zoomstart', hide);
}
