// Leaderboard: the best game of each player with exactly the settings of the
// filters (classic, survival), or the levels, or the wins with friends
$(function () {
    var board = $('.board'), form = $('#filter-options');
    var medals = ['#d4af37', '#c0c0c0', '#cd7f32'];
    var asked = 0;

    // per tab: the columns after # and Player; the last one is left out on a phone
    var columns = {
        classic: ['Score', 'Time', 'Date'],
        survival: ['Locations', 'Points', 'Date'],
        levels: ['Level', 'XP', 'Games'],
        wins: ['Wins', 'Best streak', 'Games']
    };

    function esc(text) {
        return $('<div>').text(text).html();
    }

    function number(n) {
        return Number(n).toLocaleString('en-US');
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

    // the name opens the player's profile here; a name proven by Wynncraft
    // has a green badge that opens their Wynncraft profile
    function player(row) {
        var name = "<a class='board-name' href='player?id=" + row.id + "'><img class='board-pic" + (row.head ? ' head' : '') +
            "' src='" + esc(row.pic) + "' alt='' width='28' height='28' loading='lazy'>" + esc(row.name) + "</a>";
        if (!row.mc) {
            return name;
        }
        return name + "<a class='board-verified' href='https://wynncraft.com/stats/player/" + encodeURIComponent(row.mc) +
            "' target='_blank' rel='noopener' title='Wynncraft profile: " + esc(row.mc) + "'>" +
            "<i class='material-icons wynn-check'>verified</i><i class='material-icons'>open_in_new</i></a>";
    }

    function cells(row, mode) {
        if (mode == 'levels') {
            return ["<b class='lvl'>" + row.level + "</b>", number(row.xp), number(row.games)];
        }
        if (mode == 'wins') {
            return [number(row.wins), number(row.best), number(row.played)];
        }
        if (mode == 'survival') {
            return [number(row.score), number(row.points || 0), day(row.date)];
        }
        return [number(row.score), duration(row.time), day(row.date)];
    }

    function load() {
        var mode = form.find('[name=mode]:checked').val();
        var ladder = mode == 'levels' || mode == 'wins';
        var provinces = form.find('[name=province]:checked').map(function () { return this.value; }).get();
        form.find('.filters').prop('hidden', ladder);
        // Survival has no settings but its difficulty and the milk: one board for each
        form.find('.board-group').prop('hidden', mode == 'survival');
        $('#board-difficulty, #board-milk').prop('hidden', mode != 'survival');
        $('#board-rounds').prop('hidden', mode != 'classic');
        var ask = ++asked;
        $.ajax({url: board.data('api'), type: 'POST', dataType: 'json', data: ladder ? {mode: mode}
                : mode == 'survival' ? {mode: mode, difficulty: form.find('[name=difficulty]:checked').val(), milk: form.find('[name=milk]:checked').val()} : {
            mode: mode,
            provinces: "['" + provinces.join("', '") + "']",
            rounds: form.find('[name=rounds]:checked').val(),
            nolook: form.find('[name=nolook]:checked').val()
        }}).done(function (r) {
            // a slow answer to an older choice of filters is ignored
            if (ask == asked) {
                show(r.rows, r.me, mode);
            }
        });
    }

    function show(rows, me, mode) {
        $('#board-head').html('<th>#</th><th>Player</th>' + columns[mode].map(function (c, i) {
            return '<th' + (i == 2 ? " class='board-more'" : '') + '>' + c + '</th>';
        }).join(''));
        $('#table-body').html(rows.map(function (row, i) {
            var rank = i < 3 ? "<i class='material-icons' style='color:" + medals[i] + "'>emoji_events</i>" : i + 1;
            // who is on a winning streak with friends right now, in every tab
            var fire = row.streak >= 1 ? " <span class='board-fire' title='Wins in a row'>" +
                "<i class='material-icons xp-fire'>local_fire_department</i>" + row.streak + "</span>" : '';
            return "<tr class='leaderboard-row" + (row.id == me ? ' you' : '') + "'><td>" + rank + "</td>" +
                "<td><span class='board-who'>" + (mode != 'levels' && row.level ? "<b class='lvl name-lvl' title='Level'>" + row.level + "</b>" : '') +
                player(row) + fire + "</span></td>" + cells(row, mode).map(function (c, i) {
                    return '<td' + (i == 2 ? " class='board-more'" : '') + '>' + c + '</td>';
                }).join('') + "</tr>";
        }).join(''));
        $('.board-table').prop('hidden', rows.length == 0);
        $('#board-empty').prop('hidden', rows.length > 0);
    }

    form.on('change', load);
    load();
});
