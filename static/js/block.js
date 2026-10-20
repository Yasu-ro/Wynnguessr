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

// The compass of the panoramas, Skyrim's way (Yasuro): a band at the top
// where N, E, S, W and small marks slide by as the view turns. Every
// location comes from the mod, which takes its pictures facing north: yaw 0
// is north, 90 east. Pannellum says nothing when the view turns, so each
// frame reads the yaw, and only moves the marks when it changed. In a room
// it goes right under the round's sign (after): on top, the sign hid it
var COMPASS_SPAN = 90;    // degrees seen on each side of the middle

function compassBar(viewer, after) {
    var box = after ? after.parentNode : viewer.getContainer(), bar = document.createElement('div'), marks = '';
    if (box.compass) box.compass.remove();   // the band of the last location
    for (var d = 0; d < 360; d += 15) {
        var letter = {0: 'N', 90: 'E', 180: 'S', 270: 'W'}[d];
        marks += letter ? "<b class='compass-mark" + (d ? '' : ' north') + "' data-deg='" + d + "'>" + letter + '</b>'
                        : "<i class='compass-tick" + (d % 45 ? '' : ' big') + "' data-deg='" + d + "'></i>";
    }
    bar.className = 'compass-bar';
    bar.innerHTML = marks;
    if (after) after.after(bar); else box.appendChild(bar);
    box.compass = bar;
    var items = [].slice.call(bar.children), last = null;
    (function frame() {
        if (box.compass != bar) return;
        var yaw;
        try {
            yaw = viewer.getYaw();
        } catch (e) {
            return;   // destroyed
        }
        if (yaw !== last) {
            last = yaw;
            items.forEach(function (el) {
                var delta = ((el.dataset.deg - yaw) % 360 + 540) % 360 - 180;
                el.style.visibility = Math.abs(delta) > COMPASS_SPAN ? 'hidden' : '';
                el.style.left = (50 + 50 * delta / COMPASS_SPAN) + '%';
            });
        }
        requestAnimationFrame(frame);
    })();
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
    touchOpens(m);    // every guess map has both
}

// On a phone, the small map grows at the first touch (style.css: its
// :hover), and that touch also dropped the pin, somewhere the grown map no
// longer showed: a quick Guess! went there (Yasuro's party test, 2026-10-20).
// Now a touch on the closed map only opens it; the next touches aim. The
// map is closed again once a touch lands elsewhere (its :hover goes).
var TOUCH_GAP = 800;      // ms: a touch with no click after it (a drag, a pinch) counts for nothing
function touchOpens(m) {
    var box = m.getContainer().closest('.map-container');
    if (!box) {
        return;
    }
    if (!box.touchState) {
        // the box outlives the maps of a room (one per round): its watch, once
        box.touchState = {open: false, skip: 0};
        box.addEventListener('pointerdown', function (e) {
            var st = box.touchState, onMap = !!e.target.closest('.leaflet-container');
            st.skip = e.pointerType != 'mouse' && !st.open && onMap ? Date.now() : 0;
            st.open = true;
        }, true);
        document.addEventListener('pointerdown', function (e) {
            if (!box.contains(e.target)) {
                box.touchState.open = false;
            }
        }, true);
    }
    m.getContainer().addEventListener('click', function (e) {
        var st = box.touchState;
        if (st.skip && Date.now() - st.skip < TOUCH_GAP) {
            e.stopImmediatePropagation();    // before Leaflet hears it (it listens here too): no pin
        }
        st.skip = 0;
    }, true);
}
