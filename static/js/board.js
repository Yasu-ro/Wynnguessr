// Leaderboard and profile: the games played with exactly the settings of the filters
$(function () {
    var board = $('.board'), form = $('#filter-options');
    var medals = ['#d4af37', '#c0c0c0', '#cd7f32'];
    var asked = 0;

    function esc(text) {
        return $('<div>').text(text).html();
    }

    // 83.4 -> "1:23.4"
    function duration(seconds) {
        seconds = Number(seconds) || 0;
        var rest = (seconds % 60).toFixed(1);
        return Math.floor(seconds / 60) + ':' + (rest < 10 ? '0' : '') + rest;
    }

    // "2026-10-15" -> "Oct 15, 2026"
    function day(iso) {
        var d = new Date(iso + 'T00:00:00');
        return isNaN(d) ? iso : d.toLocaleDateString('en-US', {month: 'short', day: 'numeric', year: 'numeric'});
    }

    // a name proven by Wynncraft links to the player's Wynncraft profile
    function player(row) {
        if (!row.mc) {
            return esc(row.name);
        }
        return "<a class='board-verified' href='https://wynncraft.com/stats/player/" + encodeURIComponent(row.mc) +
            "' target='_blank' rel='noopener'>" + esc(row.name) + "<i class='material-icons wynn-check'>verified</i></a>";
    }

    function load() {
        var mode = form.find('[name=mode]:checked').val();
        var provinces = form.find('[name=province]:checked').map(function () { return this.value; }).get();
        $('#board-rounds').prop('hidden', mode != 'classic');
        $('#board-score').text(mode == 'survival' ? 'Streak' : 'Score');
        var ask = ++asked;
        $.ajax({url: board.data('api'), type: 'POST', dataType: 'json', data: {
            mode: mode,
            provinces: "['" + provinces.join("', '") + "']",
            rounds: form.find('[name=rounds]:checked').val(),
            nolook: form.find('[name=nolook]:checked').val()
        }}).done(function (r) {
            // a slow answer to an older choice of filters is ignored
            if (ask == asked) {
                show(r.rows, r.me);
            }
        });
    }

    function show(rows, me) {
        $('#table-body').html(rows.map(function (row, i) {
            var rank = i < 3 ? "<i class='material-icons' style='color:" + medals[i] + "'>emoji_events</i>" : i + 1;
            return "<tr class='leaderboard-row" + (row.name == me ? ' you' : '') + "'><td>" + rank + "</td>" +
                "<td class='board-player'>" + player(row) + "</td>" +
                "<td>" + Number(row.score).toLocaleString('en-US') + "</td>" +
                "<td>" + duration(row.time) + "</td>" +
                "<td class='board-date'>" + day(row.date) + "</td></tr>";
        }).join(''));
        $('.board-table').prop('hidden', rows.length == 0);
        $('#board-empty').prop('hidden', rows.length > 0);
    }

    form.on('change', load);
    load();
});
