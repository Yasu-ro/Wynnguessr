// The moderation page (app.py, "Moderation"): the team and its ranks, the
// log, the messages of the contact page. The server decides what each one
// may do; this page only offers it.
$(function () {
    var team = null, armed = null, armedAt = 0;
    var ARMED = 3000;   // ms the "Sure?" of a removal waits for the second click

    // quotes too: a name may end up inside an attribute (data-name='...')
    function esc(text) {
        return $('<div>').text(text == null ? '' : text).html().replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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
        if (tab == 'photos') {
            photos();
        }
        if (tab == 'reports') {
            reports();
        }
        if (tab == 'players' && !listed) {
            players();
        }
        if (tab == 'messages') {
            inbox();
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

    // ---------- photos ----------
    // each picture a player sent: yes, it becomes theirs; no, it goes, and
    // they read why on their page
    function photos() {
        $.getJSON('api/mod/pictures').done(function (r) {
            $('#photo-list').html(r.pictures.map(function (p) {
                return "<div class='mod-photo' data-id='" + p.id + "'><img src='" + esc(p.url) + "' alt='' width='128' height='128'>" +
                    "<a class='board-name' href='player?id=" + p.id + "'>" + esc(p.name) + '</a><small>' + when(p.at) + '</small>' +
                    "<input class='field small' placeholder='Why (if no)' aria-label='Why' maxlength='200'>" +
                    "<div><button type='button' class='btn' data-photo='approve'>Yes</button>" +
                    "<button type='button' class='btn red' data-photo='reject'>No</button></div></div>";
            }).join(''));
            $('#photo-empty').prop('hidden', r.pictures.length > 0);
        });
    }
    $('#photo-list').on('click', '[data-photo]', function () {
        var card = $(this).closest('.mod-photo');
        card.find('button').prop('disabled', true);
        $.post('api/mod/picture', {id: card.data('id'), 'do': $(this).data('photo'), reason: card.find('input').val()}).always(photos);
    });

    // ---------- reports ----------
    // a reported message among the ones around it (what was typed, before
    // the filter): hide it for everyone, or close the report
    function reports() {
        $.getJSON('api/mod/reports').done(function (r) {
            $('#report-list').html(r.reports.map(function (x) {
                var by = x.by.length > 3 ? x.by.slice(0, 3).join(', ') + ' and ' + (x.by.length - 3) + ' more' : x.by.join(', ');
                return "<div class='mod-report' data-id='" + x.id + "'><p class='mod-report-head'>" +
                    "<span><a class='board-name' href='#' data-player='" + x.author.id + "'>" + esc(x.author.name) + '</a>' +
                    (x.author.guest ? ' <small>(guest)</small>' : '') + '</span>' +
                    '<small>Room ' + esc(x.room) + ' · ' + when(x.at) + '</small></p>' +
                    "<div class='mod-chat'>" + x.around.map(function (m) {
                        return '<p' + (m.id == x.id ? " class='reported'" : m.hidden ? " class='gone'" : '') + '><b>' + esc(m.name) + '</b><span>' + esc(m.text) + '</span></p>';
                    }).join('') + '</div>' +
                    "<p class='mod-report-by'>Reported by " + esc(by) + '</p>' +
                    "<input class='field small' placeholder='Why (kept in the log)' aria-label='Why' maxlength='200'>" +
                    "<div><button type='button' class='btn red' data-report='hide'>Hide It</button>" +
                    "<button type='button' class='btn wood' data-report='dismiss'>Dismiss</button></div></div>";
            }).join(''));
            $('#report-empty').prop('hidden', r.reports.length > 0);
        });
    }
    $('#report-list').on('click', '[data-report]', function () {
        var card = $(this).closest('.mod-report'), what = $(this).data('report');
        card.find('button').prop('disabled', true);
        $.post(what == 'hide' ? 'api/mod/hide' : 'api/mod/report', {id: card.data('id'), 'do': what, reason: card.find('input').val()}).always(reports);
    });

    // ---------- players ----------
    // find a player, see how things stand and what happened, and act: mute,
    // ban (asks twice), rename. The server says what this rank may do.
    var LENGTHS = {600: '10 min', 3600: '1 hour', 86400: '1 day', 604800: '7 days', 2419200: '28 days', 0: 'Forever'};
    var shown = null, banArmed = 0;

    // the list: every player, filtered by kind and by name, 50 at a time;
    // a row opens the player's card, which goes back to the list
    var listed = 0, asked = 0, typing = null;
    function players(more) {
        var n = ++asked;
        $.getJSON('api/mod/players', {q: $('#player-find [name=q]').val(), kind: $('[name=kind]:checked').val(), start: more ? listed : 0}).done(function (r) {
            if (n != asked) {
                return;   // an older search, answered late
            }
            var rows = r.players.map(function (p) {
                var status = [p.guest ? 'Guest' : '', p.muted ? 'Muted' : '', p.banned ? 'Banned' : '',
                              p.reported ? 'Reported ' + p.reported + '×' : ''].filter(Boolean);
                return "<tr class='leaderboard-row'><td><div class='mod-who'><img src='" + esc(p.picture) + "' alt='' width='24' height='24'>" + esc(p.name) +
                    (p.tag ? " <span class='name-tag " + esc(p.tag.color) + "'>" + esc(p.tag.label) + '</span>' : '') + '</div></td>' +
                    "<td class='mod-flags'>" + esc(status.join(' · ')) + '</td>' +
                    "<td class='mod-tools'><div><button type='button' class='chip small' data-player='" + p.id + "'>Open</button></div></td></tr>";
            }).join('');
            $('#player-rows')[more ? 'append' : 'html'](rows);
            listed = (more ? listed : 0) + r.players.length;
            $('#player-empty').prop('hidden', listed > 0);
            $('#player-more').prop('hidden', !r.more);
        });
    }
    $('#player-find').on('submit', function (e) {
        e.preventDefault();
    }).on('input', function () {
        clearTimeout(typing);
        typing = setTimeout(function () { players(); }, 250);
    });
    $('#player-kinds').on('change', function () { players(); });
    $('#player-more').on('click', function () { players(true); });
    $('#player-rows').on('click', '[data-player]', function () {
        player($(this).data('player'));
    });
    $('#player-card').on('click', '[data-back]', function () {
        $('#player-card').prop('hidden', true);
        $('#player-list').prop('hidden', false);
        players();
    });
    // a name on a report, or ?player= (the Moderate button of a profile), opens its player here
    function openPlayer(id) {
        $('#tab-players').prop('checked', true).trigger('change');
        player(id);
    }
    $('#report-list').on('click', '[data-player]', function (e) {
        e.preventDefault();
        openPlayer($(this).data('player'));
    });

    function lengths(name, list) {
        return "<div class='chips'>" + list.map(function (l, i) {
            return "<input type='radio' name='" + name + "' id='" + name + '-' + l + "' value='" + l + "'" + (i == 0 ? ' checked' : '') + '>' +
                "<label class='chip small' for='" + name + '-' + l + "'>" + LENGTHS[l] + '</label>';
        }).join('') + '</div>';
    }

    function player(id) {
        $.getJSON('api/mod/player', {id: id}).done(function (p) {
            if (!p.success) {
                return;
            }
            shown = p.id;
            var status = [p.banned ? 'Banned ' + p.banned : '', p.muted ? 'Muted for ' + p.muted : ''].filter(Boolean);
            var acts = '';
            if (p.may.mute) {
                acts += "<div class='mod-act'><h3>Mute <small>no chat</small></h3>" + (p.muted
                    ? "<button type='button' class='btn wood' data-act='unmute'>Unmute</button>"
                    : lengths('mute-length', p.mutes) + "<button type='button' class='btn' data-act='mute'>Mute</button>") + '</div>';
            }
            if (p.may.ban) {
                acts += "<div class='mod-act'><h3>Ban <small>no playing, logged out everywhere</small></h3>" + (p.banned
                    ? "<button type='button' class='btn wood' data-act='unban'>Unban</button>"
                    : lengths('ban-length', p.bans) + "<button type='button' class='btn red' data-act='ban'>Ban</button>") + '</div>';
            }
            if (p.ranks) {
                acts += "<div class='mod-act'><h3>Rank</h3><div class='mod-rename'><select class='field' name='rank' aria-label='Rank'>" +
                    Object.keys(p.ranks).sort().reverse().map(function (k) {
                        return "<option value='" + k + "'" + (k == p.rank ? ' selected' : '') + '>' + esc(p.ranks[k]) + '</option>';
                    }).join('') + "<option value='0'" + (p.rank ? '' : ' selected') + ">No rank</option></select>" +
                    "<button type='button' class='btn' data-act='rank'>Save</button></div></div>";
            }
            if (p.may.rename) {
                acts += "<div class='mod-act'><h3>Rename</h3><div class='mod-rename'><input class='field' name='name' value='" + esc(p.name) +
                    "' aria-label='New name' maxlength='20'><button type='button' class='btn' data-act='rename'>Rename</button></div></div>";
            }
            if (acts) {
                acts = "<input class='field' name='reason' placeholder='Why (kept in the log; a banned player reads it)' aria-label='Why' maxlength='200'>" + acts +
                    "<p class='note' id='player-note' hidden></p>";
            } else {
                acts = "<p class='hint'>This player is not below you: you can only look.</p>";
            }
            $('#player-list').prop('hidden', true);
            $('#player-card').prop('hidden', false).html("<a class='back' href='#' data-back><i class='material-icons'>arrow_back</i>All players</a>" +
                "<section class='panel mod-player'><h2>" + esc(p.name) + '</h2>' +
                "<p class='mod-player-who'>" + (p.picture ? "<img class='avatar small' src='" + esc(p.picture) + "' alt=''>" : '') +
                (p.tag ? "<span class='name-tag " + esc(p.tag.color) + "'>" + esc(p.tag.label) + '</span>' : '') +
                (p.guest ? '<small>Guest</small>' : "<a class='board-name' href='player?id=" + p.id + "'>Profile</a>") +
                '<small>Reported ' + (p.reported == 1 ? 'once' : p.reported + ' times') + '</small></p>' +
                (status.length ? "<p class='mod-status'>" + esc(status.join(' · ')) + '</p>' : '') + acts +
                '<h3>History</h3>' + (p.log.length ? "<ul class='mod-history'>" + p.log.map(function (e) {
                    return '<li><small>' + when(e.at) + ' · ' + esc(e.by) + '</small> ' + esc(e.details) +
                        (e.reason ? "<small class='mod-why'>" + esc(e.reason) + '</small>' : '') + '</li>';
                }).join('') + '</ul>' : "<p class='hint'>Nothing yet.</p>") +
                '<h3>Last Messages</h3>' + (p.said.length ? "<div class='mod-chat'>" + p.said.map(function (m) {
                    return '<p' + (m.hidden ? " class='gone'" : '') + '><small>' + esc(m.room) + ' · ' + when(m.at) + '</small> ' + esc(m.text) + '</p>';
                }).join('') + '</div>' : "<p class='hint'>Nothing yet.</p>") + '</section>');
        });
    }

    $('#player-card').on('click', '[data-act]', function () {
        var card = $(this).closest('.mod-player'), what = $(this).data('act'), button = $(this);
        // a ban asks twice
        if (what == 'ban' && Date.now() - banArmed > ARMED) {
            banArmed = Date.now();
            button.text('Sure?');
            setTimeout(function () { if (Date.now() - banArmed >= ARMED) button.text('Ban'); }, ARMED + 50);
            return;
        }
        banArmed = 0;
        if (what == 'rank') {
            // by id: a guest may have had the same name before the account
            $.post('api/mod/rank', {id: shown, rank: card.find('[name=rank]').val(), reason: card.find('[name=reason]').val()})
                .done(function (r) { r.success ? player(shown) : $('#player-note').prop('hidden', false).addClass('bad').text(r.error); })
                .fail(function (x) { $('#player-note').prop('hidden', false).addClass('bad').text((x.responseJSON && x.responseJSON.error) || 'Refused'); });
            return;
        }
        $.post('api/mod/sanction', {id: shown, 'do': what, reason: card.find('[name=reason]').val(), name: card.find('[name=name]').val(),
                                    length: card.find('[name=' + what + '-length]:checked').val()}).done(function (r) {
            if (r.success) {
                player(shown);
            } else {
                $('#player-note').prop('hidden', false).addClass('bad').text(r.error || 'Refused');
            }
        }).fail(function (x) {
            $('#player-note').prop('hidden', false).addClass('bad').text((x.responseJSON && x.responseJSON.error) || 'Refused');
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

    // ---------- messages (the contact page) ----------
    // by state, topic, words; a message opens in place, which tells its
    // sender "Read". Answered here, the sender reads it on the site; by
    // email or on Discord, it is written from there, then closed here
    var inboxListed = 0, inboxAsked = 0, inboxTyping = null, opened = {}, dropArmed = null, dropAt = 0;
    var CONTACT_STATUS = {new: 'New', open: 'Open', answered: 'Answered', done: 'Done'};

    function copy(text, button) {
        function copied() {
            var old = button.text();
            button.text('Copied!');
            setTimeout(function () { button.text(old); }, 1400);
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(copied);
        } else {
            var field = $('<input>').val(text).appendTo('body').select();
            document.execCommand('copy');
            field.remove();
            copied();
        }
    }

    function inbox(more) {
        var n = ++inboxAsked;
        $.getJSON('api/mod/contact', {state: $('[name=inbox-state]:checked').val(), topic: $('#inbox-topic').val(),
                                      sort: $('[name=inbox-sort]:checked').val(), q: $('#inbox-find [name=q]').val(),
                                      start: more ? inboxListed : 0}).done(function (r) {
            if (n != inboxAsked) {
                return;   // an older search, answered late
            }
            var all = 0;
            $.each(r.counts, function (k, v) { all += v; });
            $('[data-count]').each(function () {
                var k = $(this).data('count'), v = k == 'all' ? all : r.counts[k] || 0;
                $(this).text(v || '');
            });
            $('#messages-count').text(r.counts.new || 0).prop('hidden', !r.counts.new);
            var chosen = $('#inbox-topic').val();
            $('#inbox-topic').html("<option value=''>Every topic</option>" + Object.keys(r.labels).map(function (k) {
                return "<option value='" + k + "'" + (k == chosen ? ' selected' : '') + '>' + esc(r.labels[k]) +
                    (r.topics[k] ? ' (' + r.topics[k] + ')' : '') + '</option>';
            }).join(''));
            var cards = r.messages.map(function (m) { return message(m, r); }).join('');
            $('#inbox-list')[more ? 'append' : 'html'](cards);
            inboxListed = (more ? inboxListed : 0) + r.messages.length;
            $('#inbox-empty').prop('hidden', inboxListed > 0);
            $('#inbox-more').prop('hidden', !r.more);
        });
    }

    function message(m, r) {
        var last = m.replies.length && m.replies[m.replies.length - 1];
        var status = m.state == 'open' && last && last.team ? 'answered' : m.state;
        // who wrote (their card a click away), and when, if they wrote again since
        var who = (m.from ? 'From ' + "<a class='board-name' href='#' data-player='" + m.from.id + "'>" + esc(m.from.name) + '</a>' +
            (m.from.tag ? " <span class='name-tag " + esc(m.from.tag.color) + "'>" + esc(m.from.tag.label) + '</span>' : '') +
            (m.from.guest ? ' <small>(guest)</small>' : '') : 'Not logged in') + (m.last != m.at ? ' · sent ' + when(m.at) : '');
        var about = '';
        if (m.about) {
            var word = {player: 'About', account: 'Account', sanction: 'Account', location: 'Where'}[m.topic] || 'About';
            about = "<p class='mod-msg-about'>" + word + ': ' + (m.about_id ? "<a class='board-name' href='#' data-player='" + m.about_id + "'>" +
                esc(m.about) + '</a>' : '<b>' + esc(m.about) + '</b>' + (m.topic == 'player' ? ' <small>(no player with this name)</small>' : '')) + '</p>';
        }
        var answer;
        if (m.reply == 'email') {
            var mail = 'mailto:' + m.email + '?subject=' + encodeURIComponent('Re: ' + r.labels[m.topic] + ' (WynnGuessr)') +
                '&body=' + encodeURIComponent('\n\n> ' + m.text.slice(0, 600).split('\n').join('\n> '));
            answer = 'Answer by email: <b>' + esc(m.email) + "</b> <button type='button' class='chip small' data-copy='" + esc(m.email) + "'>Copy</button>" +
                " <a class='chip small' href='" + esc(mail) + "'>Write</a>";
        } else if (m.reply == 'discord') {
            answer = 'Answer on Discord: <b>' + esc(m.discord) + "</b> <button type='button' class='chip small' data-copy='" + esc(m.discord) + "'>Copy</button>";
        } else {
            answer = m.reply == 'here' ? 'Answer here: they read it on the site.' : 'No answer needed.';
        }
        var c = m.context;
        var thread = m.replies.map(function (x) {
            return "<p class='contact-line" + (x.team ? ' team' : '') + "'><b>" + esc(x.team ? x.by || 'Team' : m.from ? m.from.name : 'Them') + '</b>' +
                '<span>' + esc(x.text) + '</span><small>' + when(x.at) + '</small></p>';
        }).join('');
        var here = m.from && m.reply != 'none';
        return "<article class='mod-msg" + (opened[m.id] ? ' open' : '') + "' data-id='" + m.id + "' data-state='" + m.state + "'>" +
            "<button type='button' class='mod-msg-head' aria-expanded='" + !!opened[m.id] + "'><i class='material-icons'>" + esc(r.icons[m.topic]) + '</i>' +
            '<b>' + esc(r.labels[m.topic]) + "</b><span class='mod-msg-from'>" + (m.from ? esc(m.from.name) : 'not logged in') + '</span>' +
            '<small>' + when(m.last) + "</small><span class='contact-status status-" + status + "'>" + CONTACT_STATUS[status] + '</span></button>' +
            "<p class='mod-msg-text'>" + esc(m.text) + '</p>' +
            "<div class='mod-msg-more'><p class='mod-msg-who'>" + who + '</p>' + about +
            (m.file ? "<a class='contact-thumb' href='" + esc(m.file) + "' target='_blank' rel='noopener'><img src='" + esc(m.file) + "' alt='Screenshot'></a>" : '') +
            (c ? "<p class='contact-small'>Sent along: " + esc([c.browser, c.screen, c.page ? 'from ' + c.page : '', 'site v' + c.version].filter(Boolean).join(' · ')) + '</p>' : '') +
            "<p class='mod-msg-answer'>" + answer + '</p>' +
            (thread ? "<div class='contact-thread'>" + thread + '</div>' : '') +
            "<textarea class='field' rows='3' maxlength='2000' aria-label='Your answer' placeholder='" +
            (here ? 'Your answer: they read it on the site' : 'What you answered, for the team') + "'></textarea>" +
            "<div class='mod-msg-tools'><button type='button' class='btn' data-do='answer'>" + (here ? 'Answer' : 'Save') + '</button>' +
            "<button type='button' class='btn wood' data-do='answer' data-close='1'>" + (here ? 'Answer & Close' : 'Save & Close') + '</button>' +
            (m.state == 'done' ? "<button type='button' class='chip small' data-do='reopen'>Open again</button>"
                               : "<button type='button' class='chip small' data-do='done'>Close</button>") +
            "<button type='button' class='chip small" + (dropArmed == m.id ? ' armed' : '') + "' data-do='delete'>" + (dropArmed == m.id ? 'Sure?' : 'Delete') + '</button>' +
            '</div></div></article>';
    }

    $('#inbox-states, #inbox-sort, #inbox-topic').on('change', function () { inbox(); });
    $('#inbox-find').on('submit', function (e) {
        e.preventDefault();
    }).on('input', function () {
        clearTimeout(inboxTyping);
        inboxTyping = setTimeout(function () { inbox(); }, 250);
    });
    $('#inbox-more').on('click', function () { inbox(true); });

    $('#inbox-list').on('click', '.mod-msg-head', function () {
        var card = $(this).closest('.mod-msg'), id = card.data('id');
        opened[id] = !opened[id];
        card.toggleClass('open', opened[id]);
        $(this).attr('aria-expanded', opened[id]);
        // read for the first time: its sender sees "Read" (it stays in this list until the next search)
        if (opened[id] && card.data('state') == 'new') {
            card.data('state', 'open');
            $.post('api/mod/contact', {id: id, 'do': 'open'}).done(function () {
                card.find('.mod-msg-head .contact-status').attr('class', 'contact-status status-open').text('Open');
                var left = Math.max(0, (+$('#messages-count').text() || 0) - 1);
                $('#messages-count').text(left).prop('hidden', !left);
                $('[data-count=new]').text(left || '');
                $('[data-count=open]').text((+$('[data-count=open]').text() || 0) + 1);
            });
        }
    }).on('click', '[data-copy]', function () {
        copy($(this).data('copy'), $(this));
    }).on('click', '[data-player]', function (e) {
        e.preventDefault();
        openPlayer($(this).data('player'));
    }).on('click', '[data-do]', function () {
        var b = $(this), card = b.closest('.mod-msg'), id = card.data('id'), what = b.data('do');
        var text = $.trim(card.find('textarea').val());
        if (what == 'answer' && !text) {
            return card.find('textarea').focus();
        }
        // a message goes for good: twice
        if (what == 'delete' && !(dropArmed == id && Date.now() - dropAt < ARMED)) {
            dropArmed = id;
            dropAt = Date.now();
            b.addClass('armed').text('Sure?');
            setTimeout(function () { if (dropArmed == id) { dropArmed = null; b.removeClass('armed').text('Delete'); } }, ARMED + 50);
            return;
        }
        dropArmed = null;
        card.find('button').prop('disabled', true);
        $.post('api/mod/contact', {id: id, 'do': what, text: text, close: b.data('close') || ''}).always(function () { inbox(); });
    });

    // ---------- the log ----------
    var oldest = null;
    var WORDS = {rank: 'rank'};
    function log(more) {
        $.getJSON('api/mod/log', more && oldest ? {before: oldest} : {}).done(function (r) {
            var html = r.log.map(function (e) {
                // the reason under what was done, on every screen: it is the point of a log
                var what = (e.tid ? '<b>' + esc(e.target || '(gone)') + '</b> ' : '') + esc(e.details || WORDS[e.action] || e.action) +
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
    if ($('#pane-photos').length) {
        photos();
    }
    if ($('#pane-reports').length) {
        reports();
    }
    if ($('#pane-messages').length && !$('#pane-messages').prop('hidden')) {
        inbox();
    }
    var asked_for = /[?&]player=(\d+)/.exec(location.search);
    if (asked_for && $('#pane-players').length) {
        openPlayer(+asked_for[1]);
    }
});
