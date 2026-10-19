// The report form (app.py, "Moderation: the chat"): a reason, a few words, or
// both, for a message or a whole player. post(fields) sends it and answers
// {success, error}; the same keys as REPORT_WHY in app.py.
var REPORT_WHY = [['rude', 'Rude or hateful'], ['name', 'Bad name or picture'], ['cheat', 'Cheating'], ['spam', 'Spam'], ['other', 'Something else']];

function reportForm(title, post) {
    var box = document.getElementById('report-form');
    if (!box) {
        box = document.createElement('dialog');
        box.id = 'report-form';
        box.className = 'report-form';
        box.innerHTML = "<form method='dialog'><h2></h2><div class='chips'>" + REPORT_WHY.map(function (w) {
                return "<input type='radio' name='why' id='why-" + w[0] + "' value='" + w[0] + "'><label class='chip small' for='why-" + w[0] + "'>" + w[1] + '</label>';
            }).join('') + '</div>' +
            "<textarea class='field' name='note' maxlength='200' rows='3' placeholder='Tell us more' aria-label='Tell us more'></textarea>" +
            "<p class='note bad' hidden></p>" +
            "<div class='report-buttons'><button type='button' class='btn wood' data-cancel>Cancel</button><button type='submit' class='btn red'>Report</button></div></form>";
        document.body.appendChild(box);
        var form = box.querySelector('form'), send = form.querySelector('[type=submit]');
        // something to go on: a reason, or a few words
        form.addEventListener('input', function () {
            send.disabled = !form.why.value && !form.note.value.trim();
        });
        box.querySelector('[data-cancel]').addEventListener('click', function () { box.close(); });
        // a click on the dark around it closes it too
        box.addEventListener('click', function (e) {
            if (e.target == box) box.close();
        });
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var error = form.querySelector('.note');
            send.disabled = true;
            box.post({why: form.why.value, note: form.note.value}).then(function (r) {
                if (r.success) {
                    form.querySelector('h2').textContent = 'Reported. Thank you!';
                    form.querySelector('.chips').hidden = form.note.hidden = form.querySelector('.report-buttons').hidden = true;
                    setTimeout(function () { box.close(); }, 1500);
                } else {
                    error.textContent = r.error || 'This is gone';
                    error.hidden = false;
                    send.disabled = false;
                }
            }, function () {
                error.textContent = 'Could not send: try again';
                error.hidden = false;
                send.disabled = false;
            });
        });
    }
    var form = box.querySelector('form');
    form.reset();
    form.querySelector('h2').textContent = title;
    form.querySelector('.chips').hidden = form.note.hidden = form.querySelector('.report-buttons').hidden = false;
    form.querySelector('.note').hidden = true;
    form.querySelector('[type=submit]').disabled = true;
    box.post = post;
    box.showModal();
}
