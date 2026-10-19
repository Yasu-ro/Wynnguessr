// The contact page (app.py, "Contact"): the topic shapes the form, a
// screenshot comes by button, paste or drop, the message goes without
// leaving the page, and the sender's messages show below with the team's
// answers (reading them ends the notice on the other pages).
$(function () {
    var user = $('#reply-here').length > 0;   // logged in, as an account or a guest
    var TOPICS = {   // what each topic asks for
        bug: {text: 'What happened? What were you doing?', context: true},
        location: {about: 'Where? Coordinates or a place', text: "What's wrong with it?", context: true},
        player: {about: 'Their name', need: 'Who is it?', text: 'What did they do?', find: true},
        account: {about: user ? null : 'Your account name', need: 'Which account?', text: "What's the problem?"},
        sanction: {about: user ? null : 'Your account name', need: 'Which account?', text: 'Why should we lift it?'},
        idea: {text: 'Your idea'},
        partner: {text: 'Who you are, and what you have in mind', email: true},
        other: {text: 'Your message'}
    };
    var STATUS = {sent: 'Sent', read: 'Read', answered: 'Answered', closed: 'Closed'};
    var MAX_SHOT = 8 * 1024 * 1024;
    var shot = null, finding = null, asked = 0;

    function esc(text) {
        return $('<div>').text(text == null ? '' : text).html().replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function when(t) {
        return new Date(t * 1000).toLocaleString('en-GB', {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'});
    }
    function store(key, value) {
        // per browser only, and never needed: private windows refuse it
        try {
            if (value === undefined) {
                return JSON.parse(localStorage.getItem(key) || 'null');
            }
            localStorage.setItem(key, JSON.stringify(value));
        } catch (e) {
            return null;
        }
    }
    function topic() {
        return $('[name=topic]:checked').val();
    }
    function reply() {
        return $('[name=reply]:checked').val();
    }

    // ---------- the two ways around the form ----------
    $('#copy-email').on('click', function () {
        var b = $(this), text = b.data('copy');
        function copied() {
            b.find('.material-icons').text('check');
            b.find('span').text('Copied!');
            clearTimeout(b.data('timer'));
            b.data('timer', setTimeout(function () {
                b.find('.material-icons').text('content_copy');
                b.find('span').text('Copy the address');
            }, 1600));
        }
        function byHand() {
            var field = $('<input>').val(text).appendTo('body').select();
            document.execCommand('copy');
            field.remove();
            copied();
        }
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(text).then(copied, byHand);
        } else {
            byHand();
        }
    });

    // ---------- the form takes the shape of its topic ----------
    function shape() {
        var key = topic(), t = TOPICS[key];
        if (!t) {
            return;
        }
        $('#contact-rest').prop('hidden', false);
        $('.contact-tip').each(function () {
            $(this).prop('hidden', $(this).data('for') != key);
        });
        // a field the topic does not ask for is not sent
        $('#contact-about').prop('hidden', !t.about);
        $('#about').prop('disabled', !t.about).attr({placeholder: t.about || '', 'aria-label': t.about || ''});
        $('#text').attr('placeholder', t.text);
        // a partnership is answered by email
        $('#contact-reply .chips > input').each(function () {
            var off = t.email && this.value != 'email';
            $(this).prop('hidden', off).next('label').prop('hidden', off);
        });
        if (t.email) {
            $('#reply-email').prop('checked', true);
        }
        $('#contact-context').prop('hidden', !t.context).text(t.context ? 'Sent along: ' + context().shown : '');
        replyShape();
        find();
    }
    $('#contact-form').on('change', '[name=topic]', function () {
        shape();
        wrong();
        saveDraft();
    });

    function replyShape() {
        var r = reply();
        $('#email').prop('hidden', r != 'email');
        $('#discord').prop('hidden', r != 'discord');
        $('[data-reply]').each(function () {
            $(this).prop('hidden', $(this).data('reply').split(' ').indexOf(r) < 0);
        });
    }
    $('#contact-form').on('change', '[name=reply]', function () {
        replyShape();
        wrong();
        if (reply() == 'email' || reply() == 'discord') {
            $('#' + reply()).focus();
        }
    });

    // what a bug report carries with it, shown before it goes
    function context() {
        var ua = navigator.userAgent, m;
        var browser = (m = /Edg\/(\d+)/.exec(ua)) ? 'Edge ' + m[1] : (m = /OPR\/(\d+)/.exec(ua)) ? 'Opera ' + m[1]
            : (m = /(?:Firefox|FxiOS)\/(\d+)/.exec(ua)) ? 'Firefox ' + m[1] : (m = /(?:Chrome|CriOS)\/(\d+)/.exec(ua)) ? 'Chrome ' + m[1]
            : (m = /Version\/(\d+).*Safari/.exec(ua)) ? 'Safari ' + m[1] : 'a browser';
        var os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS'
            : /Mac OS X/.test(ua) ? 'macOS' : /CrOS/.test(ua) ? 'ChromeOS' : /Linux/.test(ua) ? 'Linux' : '';
        var screen = window.innerWidth + '×' + window.innerHeight;
        // the page it came from, if it was one of ours
        var from = document.referrer.indexOf(location.origin + '/') == 0 ? document.referrer.slice(location.origin.length) : '';
        if (/\/contact([?#]|$)/.test(from)) {
            from = '';
        }
        browser += os ? ' on ' + os : '';
        return {page: from, screen: screen, browser: browser, shown: [browser, screen, from ? 'from ' + from : ''].filter(Boolean).join(' · ')};
    }

    // ---------- the player a report is about ----------
    function find() {
        var name = $.trim($('#about').val());
        clearTimeout(finding);
        if (!TOPICS[topic()].find || name.length < 2) {
            $('#contact-found').prop('hidden', true);
            return;
        }
        finding = setTimeout(function () {
            var n = ++asked;
            $.getJSON('api/contact/player', {name: name}).done(function (r) {
                if (n != asked) {
                    return;   // an older name, answered late
                }
                var box = $('#contact-found').prop('hidden', false).toggleClass('missing', !r.found);
                box.find('img').prop('hidden', !r.found).attr('src', r.picture || '');
                box.find('span').text(r.found ? r.name : 'No player with this name');
            });
        }, 300);
    }
    $('#about').on('input', find);

    // ---------- the message ----------
    $('#text').on('input', function () {
        // it grows with what is written, up to a point
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight + 6, 460) + 'px';
        var left = 2000 - this.value.length;
        $('#contact-count').prop('hidden', left > 300).text(left + ' characters left');
    });

    // ---------- a screenshot: the button, a paste, or a drop ----------
    function takeShot(file) {
        if (!file || !/^image\/(png|jpeg|webp|gif)$/.test(file.type)) {
            return say('This file is not a picture', 'file');
        }
        if (file.size > MAX_SHOT) {
            return say('This picture is too big: 8 MB at most', 'file');
        }
        dropShot();
        shot = file;
        $('#contact-preview').prop('hidden', false).find('img').attr('src', URL.createObjectURL(file));
        wrong();
    }
    function dropShot() {
        var img = $('#contact-preview img');
        if (img.attr('src')) {
            URL.revokeObjectURL(img.attr('src'));
        }
        shot = null;
        img.removeAttr('src');
        $('#contact-preview').prop('hidden', true);
    }
    $('#shot').on('change', function () {
        takeShot(this.files[0]);
        this.value = '';
    });
    $('#shot-remove').on('click', dropShot);
    $(document).on('paste', function (e) {
        var data = e.originalEvent.clipboardData || {}, files = [].slice.call(data.files || []);
        if ($('#contact-rest').prop('hidden')) {
            return;
        }
        // a picture copied: a file of the clipboard (or one of its items, for some browsers)
        [].slice.call(data.items || []).forEach(function (item) {
            if (item.kind == 'file') {
                files.push(item.getAsFile());
            }
        });
        for (var i = 0; i < files.length; i++) {
            if (files[i] && files[i].type.indexOf('image/') == 0) {
                e.preventDefault();
                return takeShot(files[i]);
            }
        }
    });
    $('#contact-form').on('dragover', function (e) {
        if (!$('#contact-rest').prop('hidden')) {
            e.preventDefault();
            $(this).addClass('dropping');
        }
    }).on('dragleave drop', function (e) {
        if (!e.relatedTarget || !$.contains(this, e.relatedTarget)) {
            $(this).removeClass('dropping');
        }
    }).on('drop', function (e) {
        var files = e.originalEvent.dataTransfer && e.originalEvent.dataTransfer.files;
        if (files && files.length && !$('#contact-rest').prop('hidden')) {
            e.preventDefault();
            takeShot(files[0]);
        }
    });

    // ---------- what went wrong, next to where ----------
    function say(text, field) {
        wrong();
        $('#contact-note').prop('hidden', false).text(text);
        var el = {topic: '.contact-topics', reply: '#contact-reply .chips', file: '#contact-shot'}[field] || (field && '#' + field);
        if (el) {
            $(el).addClass('wrong');
            if (field == 'topic' || field == 'reply' || field == 'file') {
                $(el)[0].scrollIntoView({block: 'center'});
            } else {
                $(el).focus();
            }
        }
    }
    function wrong() {
        $('#contact-form .wrong').removeClass('wrong');
        $('#contact-note').prop('hidden', true);
    }
    $('#contact-form').on('input', '.field', function () {
        $(this).removeClass('wrong');
    });

    // ---------- sending ----------
    $('#contact-form').on('submit', function (e) {
        e.preventDefault();
        var key = topic(), t = TOPICS[key], r = reply(), about = $.trim($('#about').val());
        var email = $.trim($('#email').val()), discord = $.trim($('#discord').val());
        // the server's own checks, at once
        if (!t) {
            return say('Pick what it is about', 'topic');
        }
        if (t.about && t.need && !about) {
            return say(t.need, 'about');
        }
        if ($.trim($('#text').val()).length < 10) {
            return say('Tell us a little more', 'text');
        }
        if (!r) {
            return say('Where should we answer?', 'reply');
        }
        if (r == 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
            return say(email ? 'This email does not look right' : 'Your email?', 'email');
        }
        if (r == 'discord' && !/^[\w.#]{2,40}$/.test(discord)) {
            return say(discord ? 'This Discord name does not look right' : 'Your Discord name?', 'discord');
        }
        var data = new FormData(this), c = context();
        data.append('page', c.page);
        data.append('screen', c.screen);
        data.append('browser', c.browser);
        if (shot) {
            data.append('file', shot, shot.name || 'screenshot.png');
        }
        var send = $('#contact-send').prop('disabled', true).text('Sending…');
        $.ajax({url: 'api/contact', type: 'POST', data: data, processData: false, contentType: false, dataType: 'json'}).done(function (res) {
            if (!res.success) {
                return say(res.error || 'Refused', res.field);
            }
            store('contact-reply', {email: email, discord: discord});
            sent(r, email, discord);
        }).fail(function () {
            say('It did not go through: try again in a moment');
        }).always(function () {
            send.prop('disabled', false).text('Send');
        });
    });

    function sent(r, email, discord) {
        $('#contact-where').text({here: "We'll answer here, below.", email: "We'll answer at " + email + '.',
                                  discord: "We'll write to you on Discord: " + discord + '.', none: 'Thank you!'}[r]);
        $('#contact-form').prop('hidden', true);
        $('#contact-sent').prop('hidden', false);
        // the stamp hits once
        var stamp = $('#contact-stamp').removeClass('stamp');
        stamp[0].offsetWidth;
        stamp.addClass('stamp');
        $('#contact-sent')[0].scrollIntoView({block: 'center'});
        $('#text').val('').css('height', '');
        $('#about').val('');
        $('#contact-count, #contact-found').prop('hidden', true);
        dropShot();
        store('contact-draft', {});
        loadMine();
    }
    $('#contact-again').on('click', function () {
        $('#contact-sent').prop('hidden', true);
        $('#contact-form').prop('hidden', false);
        $('[name=topic]').prop('checked', false);
        $('#contact-rest').prop('hidden', true);
        $('.contact-topics input:first').focus();
    });

    // ---------- a draft survives a reload ----------
    var saving = null;
    function saveDraft() {
        clearTimeout(saving);
        saving = setTimeout(function () {
            store('contact-draft', {topic: topic(), about: $('#about').val(), text: $('#text').val()});
        }, 400);
    }
    $('#contact-form').on('input', '#about, #text', saveDraft);

    var draft = store('contact-draft') || {}, known = store('contact-reply') || {};
    if (!topic() && TOPICS[draft.topic]) {
        $('#topic-' + draft.topic).prop('checked', true);
    }
    if (!$('#about').val() && draft.about) {
        $('#about').val(draft.about);
    }
    if (draft.text) {
        $('#text').val(draft.text).trigger('input');
    }
    $('#email').val(known.email || '');
    $('#discord').val(known.discord || '');
    replyShape();
    shape();

    // ---------- the sender's messages ----------
    var scrolled = false;
    function mine(m) {
        var replies = m.replies.map(function (r) {
            return "<p class='contact-line" + (r.team ? ' team' : '') + "'><b>" + (r.team ? 'Team' : 'You') + '</b>' +
                "<span>" + esc(r.text) + '</span><small>' + when(r.at) + '</small></p>';
        }).join('');
        return "<article class='contact-msg' data-id='" + m.id + "'>" +
            "<p class='contact-msg-head'><i class='material-icons'>" + esc(m.icon) + '</i><b>' + esc(m.label) + '</b>' +
            (m.about ? '<span>' + esc(m.about) + '</span>' : '') + '<small>' + when(m.at) + '</small>' +
            "<span class='contact-status status-" + m.status + (m.new ? ' stamp' : '') + "'>" + STATUS[m.status] + '</span></p>' +
            "<p class='contact-msg-text'>" + esc(m.text) + '</p>' +
            (m.file ? "<a class='contact-thumb' href='" + esc(m.file) + "' target='_blank' rel='noopener'><img src='" + esc(m.file) + "' alt='Your screenshot'></a>" : '') +
            (replies ? "<div class='contact-thread'>" + replies + '</div>' : '') +
            "<button type='button' class='chip small' data-write>Write back</button>" +
            "<form class='contact-write' hidden><textarea class='field' rows='2' maxlength='2000' aria-label='Write back'></textarea>" +
            "<button class='btn wood' type='submit'>Send</button></form></article>";
    }
    function loadMine() {
        if (!user) {
            return;
        }
        $.getJSON('api/contact/mine').done(function (r) {
            $('#messages').prop('hidden', !r.messages.length);
            $('#mine').html(r.messages.map(mine).join(''));
            if (location.hash == '#messages' && !scrolled && r.messages.length) {
                scrolled = true;
                $('#messages')[0].scrollIntoView();
            }
        });
    }
    $('#mine').on('click', '[data-write]', function () {
        $(this).prop('hidden', true).next('form').prop('hidden', false).find('textarea').focus();
    }).on('submit', '.contact-write', function (e) {
        e.preventDefault();
        var form = $(this), text = $.trim(form.find('textarea').val());
        if (!text) {
            return form.find('textarea').focus();
        }
        form.find('button').prop('disabled', true);
        $.post('api/contact/' + form.closest('.contact-msg').data('id') + '/reply', {text: text}).done(function (r) {
            if (r.success) {
                loadMine();
            } else {
                form.find('button').prop('disabled', false);
                form.find('textarea').attr('placeholder', r.error || 'Refused').val('');
            }
        });
    });
    loadMine();
});
