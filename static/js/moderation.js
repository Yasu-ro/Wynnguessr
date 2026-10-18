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
        if (tab == 'tags') {
            tags();
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

    // ---------- tags ----------
    var takeArmed = null, takeAt = 0, colorsDrawn = false;
    function tags() {
        $.getJSON('api/mod/tags').done(function (r) {
            $('#tag-list').html(r.tags.map(function (t) {
                return "<div class='mod-tag" + (t.retired ? ' retired' : '') + "'><span class='name-tag tag-" + esc(t.color) + "'>" + esc(t.label) + '</span>' +
                    "<span class='mod-holders'>" + (t.holders.length ? t.holders.map(function (h) {
                        var key = t.id + ':' + h.name, sure = takeArmed == key && Date.now() - takeAt < ARMED;
                        return "<span class='mod-holder'>" + esc(h.name) + (t.retired ? '' : "<button type='button' class='chip small" + (sure ? ' armed' : '') +
                            "' data-take='" + t.id + "' data-name='" + esc(h.name) + "' title='Take it'>" + (sure ? 'Sure?' : '×') + '</button>') + '</span>';
                    }).join('') : "<i class='mod-nobody'>nobody</i>") + '</span>' +
                    (r.make ? "<button type='button' class='chip small' data-retire='" + t.id + "'>" + (t.retired ? 'Put back' : 'Put away') + '</button>' : '') + '</div>';
            }).join(''));
            $('#tag-empty').prop('hidden', r.tags.length > 0);
            $('#tag-select').html(r.tags.filter(function (t) { return !t.retired; }).map(function (t) {
                return "<option value='" + t.id + "'>" + esc(t.label) + '</option>';
            }).join(''));
            $('#tag-give').prop('hidden', !r.tags.some(function (t) { return !t.retired; }));
            if (!colorsDrawn) {
                colorsDrawn = true;
                $('#tag-colors').html(r.colors.map(function (c, i) {
                    return "<input type='radio' name='color' id='color-" + c + "' value='" + c + "'" + (i == 0 ? ' checked' : '') + '>' +
                        "<label class='chip' for='color-" + c + "'><span class='name-tag tag-" + c + "'>" + c + '</span></label>';
                }).join(''));
                preview();
            }
        });
    }
    function preview() {
        var f = $('#tag-make');
        $('#tag-preview').attr('class', 'name-tag tag-' + f.find('[name=color]:checked').val()).text(f.find('[name=label]').val() || 'Beta Tester');
    }
    $('#tag-make').on('input change', preview);
    function tagSend(data, note) {
        return $.post('api/mod/tag', data).done(function (r) {
            if (note) {
                $(note).prop('hidden', false).toggleClass('bad', !r.success).text(r.success ? 'Done!' : r.error);
            }
        }).fail(function (x) {
            if (note) {
                $(note).prop('hidden', false).addClass('bad').text((x.responseJSON && x.responseJSON.error) || 'Refused');
            }
        }).always(tags);
    }
    $('#tag-make').on('submit', function (e) {
        e.preventDefault();
        var f = $(this);
        tagSend({'do': 'make', label: f.find('[name=label]').val(), color: f.find('[name=color]:checked').val()}, '#tag-make-note')
            .done(function (r) { if (r.success) { f.find('[name=label]').val(''); preview(); } });
    });
    $('#tag-give').on('submit', function (e) {
        e.preventDefault();
        var f = $(this);
        tagSend({'do': 'give', tag: f.find('[name=tag]').val(), name: f.find('[name=name]').val(), reason: f.find('[name=reason]').val()}, '#tag-give-note')
            .done(function (r) { if (r.success) { f.find('[name=name], [name=reason]').val(''); } });
    });
    $('#tag-list').on('click', '[data-take]', function () {
        var key = $(this).data('take') + ':' + $(this).data('name');
        if (takeArmed == key && Date.now() - takeAt < ARMED) {
            takeArmed = null;
            tagSend({'do': 'take', tag: $(this).data('take'), name: $(this).data('name')});
        } else {
            takeArmed = key;
            takeAt = Date.now();
            tags();
            setTimeout(function () { if (takeArmed == key) { takeArmed = null; tags(); } }, ARMED + 50);
        }
    }).on('click', '[data-retire]', function () {
        tagSend({'do': 'retire', tag: $(this).data('retire')});
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
