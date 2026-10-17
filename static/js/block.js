// Guessing a block. The panoramas are saved at the coordinates of the block the
// player stood on, and the map has one pixel per block: a guess is the block
// clicked, shown by its centre. Zoomed in, a frame shows the block under the
// pointer, so that the exact block (5,000 points) can be aimed at.

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
