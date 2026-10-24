// About and Mods: tabs, each with its own address (about#team, mods#modpack;
// the one checked in the page needs none), and the (!) that tell more, on
// hover or on a tap
(function () {
    var tabs = document.querySelectorAll('[name=about-tab]');
    var first = document.querySelector('[name=about-tab]:checked').value;
    var film = document.querySelector('.mod-film video');
    var still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function show(tab) {
        tabs.forEach(function (t) {
            t.checked = t.value === tab;
            document.getElementById('pane-' + t.value).hidden = t.value !== tab;
        });
        // the film loads only when its tab is opened; it never moves by
        // itself for those who asked for less motion
        if (film) {
            if (film.closest('.about-pane').hidden) film.pause();
            else if (still) film.controls = true;
            else film.play().catch(function () { film.controls = true; });
        }
    }
    function fromAddress() {
        var tab = location.hash.slice(1);
        show(document.getElementById('tab-' + tab) ? tab : first);
    }
    tabs.forEach(function (t) {
        t.addEventListener('change', function () {
            history.replaceState(null, '', t.value === first ? location.pathname + location.search : '#' + t.value);
            show(t.value);
        });
    });
    window.addEventListener('hashchange', fromAddress);
    fromAddress();

    // a note never leaves the screen: pushed back in from the edge
    function place(info) {
        var tip = info.querySelector('.info-tip');
        tip.style.setProperty('--shift', '0px');
        var r = tip.getBoundingClientRect(), edge = 10;
        var shift = r.left < edge ? edge - r.left : r.right > innerWidth - edge ? innerWidth - edge - r.right : 0;
        tip.style.setProperty('--shift', shift + 'px');
    }
    function close(except) {
        document.querySelectorAll('.info.open').forEach(function (i) {
            if (i === except) return;
            i.classList.remove('open');
            i.querySelector('.info-btn').setAttribute('aria-expanded', 'false');
        });
    }
    document.querySelectorAll('.info').forEach(function (info) {
        var btn = info.querySelector('.info-btn');
        info.addEventListener('mouseenter', function () { place(info); });
        btn.addEventListener('click', function () {
            var open = !info.classList.contains('open');
            close(info);
            info.classList.toggle('open', open);
            btn.setAttribute('aria-expanded', open);
            if (open) place(info);
        });
    });
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.info')) close();
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') close();
    });
})();
