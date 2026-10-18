// The moderation page (app.py, "Moderation"): the team and its ranks, the
// log. The server decides what each one may do; this page only offers it.
$(function () {
    var team = null, armed = null, armedAt = 0;
    var ARMED = 3000;   // ms the "Sure?" of a removal waits for the second click

    function esc(text) {
        return $('<div>').text(text == null ? '' : text).html();
    }
    function tag(rank, name) {
        return "<span class='rank-tag rank-" + rank + "'>" + esc(name) + '</span>';
    }
    function when(t) {
        return t ? new Date(t * 1000).toLocaleString('en-GB', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '';
    }

    // ---------- tabs ----------
    $('#mod-tabs').on('change', function () {
        var tab = $('[name=mod-tab]:checked').val();
        $('.mod-pane').prop('hidden', true);
        $('#pane-' + tab).prop('hidden', false);
        if (tab == 'log' && !$('#log-rows').children().length) {
            log();
        }
    });

    // ---------- the team ----------
    function staff() {
        $.getJSON('api/mod/staff').done(function (r) {
            team = r;
            $('#staff-rows').html(r.staff.map(function (p) {
                var tools = '';
                if (p.mine) {
                    tools = "<select class='field small' data-id='" + esc(p.name) + "' aria-label='Rank'>" +
                        Object.keys(r.give).sort().reverse().map(function (k) {
                            return "<option value='" + k + "'" + (k == p.rank ? ' selected' : '') + '>' + esc(r.give[k]) + '</option>';
                        }).join('') + "<option value='0'>No rank</option></select>" +
                        "<button type='button' class='chip small" + (armed == p.name ? ' armed' : '') + "' data-save='" + esc(p.name) + "'>" +
                        (armed == p.name ? 'Sure?' : 'Save') + '</button>';
                }
                return "<tr class='leaderboard-row'><td><a class='board-name' href='player?id=" + p.id + "'>" + esc(p.name) + '</a></td>' +
                    '<td>' + tag(p.rank, p.tag) + "</td><td class='board-more'>" + (p.by ? esc(p.by) + ' · ' + when(p.at) : '') + '</td>' +
                    "<td class='mod-tools'><div>" + tools + '</div></td></tr>';
            }).join(''));
            $('#give-ranks').html(Object.keys(r.give).sort().map(function (k, i) {
                return "<input type='radio' name='rank' id='give-" + k + "' value='" + k + "'" + (i == 0 ? ' checked' : '') + '>' +
                    "<label class='chip' for='give-" + k + "'>" + esc(r.give[k]) + '</label>';
            }).join(''));
        });
    }

    function change(name, rank, reason) {
        return $.post('api/mod/rank', {name: name, rank: rank, reason: reason || ''}).always(staff);
    }

    $('#staff-rows').on('click', '[data-save]', function () {
        var name = $(this).data('save'), rank = $(this).siblings('select').val();
        // taking a rank away asks twice
        if (rank == '0' && !(armed == name && Date.now() - armedAt < ARMED)) {
            armed = name;
            armedAt = Date.now();
            staff();
            setTimeout(function () { if (armed == name) { armed = null; staff(); } }, ARMED + 50);
            return;
        }
        armed = null;
        change(name, rank);
    });

    $('#give-form').on('submit', function (e) {
        e.preventDefault();
        var f = $(this);
        change(f.find('[name=name]').val(), f.find('[name=rank]:checked').val(), f.find('[name=reason]').val()).done(function (r) {
            $('#give-note').prop('hidden', false).toggleClass('bad', !r.success).text(r.success ? 'Done!' : r.error);
            if (r.success) {
                f[0].reset();
            }
        }).fail(function (x) {
            $('#give-note').prop('hidden', false).addClass('bad').text((x.responseJSON && x.responseJSON.error) || 'Refused');
        });
    });

    // ---------- the log ----------
    var oldest = null;
    var WORDS = {rank: 'rank'};
    function log(more) {
        $.getJSON('api/mod/log', more && oldest ? {before: oldest} : {}).done(function (r) {
            var html = r.log.map(function (e) {
                // the reason under what was done, on every screen: it is the point of a log
                var what = '<b>' + esc(e.target || '(gone)') + '</b> ' + esc(e.details || WORDS[e.action] || e.action) +
                    (e.reason ? "<small class='mod-why'>" + esc(e.reason) + '</small>' : '');
                return "<tr class='leaderboard-row'><td class='mod-when'>" + when(e.at) + '</td><td>' + esc(e.by) + '</td><td>' + what + '</td></tr>';
            }).join('');
            $('#log-rows')[more ? 'append' : 'html'](html);
            if (r.log.length) {
                oldest = r.log[r.log.length - 1].id;
            }
            $('#log-empty').prop('hidden', !!$('#log-rows').children().length);
            $('#log-more').prop('hidden', r.log.length < 50);
        });
    }
    $('#log-more').on('click', function () { log(true); });

    staff();
});
