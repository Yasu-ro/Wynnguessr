// The Multiplayer page: who waits in each world and how many play, asked
// again every few seconds while the page is in sight. The order of the cards
// is the server's at loading: they do not jump around while someone reads.
$(function () {
    var EVERY = 5000;

    function count(slot, waiting, playing) {
        // "3 waiting · 8 in game", the waiting in green: someone to play with now
        var parts = [];
        if (waiting) {
            parts.push("<span class='live'>" + waiting + ' waiting</span>');
        }
        if (playing) {
            parts.push(playing + ' in game');
        }
        slot.find('.world-count').html(parts.length ? parts.join(' · ') : 'No one yet');
    }

    function heads(slot, urls) {
        var box = slot.find('.pcard-heads');
        var now = box.find('img').map(function () { return $(this).attr('src'); }).get().join();
        if (now != urls.join()) {
            box.empty();
            urls.forEach(function (u) {
                box.append($('<img alt="" width="24" height="24">').attr('src', u));
            });
        }
    }

    function refresh() {
        if (document.hidden) {
            return;
        }
        $.getJSON('api/multiplayer').done(function (r) {
            $.each(r.worlds, function (key, w) {
                var slot = $('[data-world="' + key + '"]');
                count(slot, w.waiting, w.playing);
                heads(slot, w.heads);
            });
        });
    }
    setInterval(refresh, EVERY);
    document.addEventListener('visibilitychange', refresh);
});
