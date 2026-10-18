// The playing cards (templates/cards.html): the one under the mouse leans
// toward it, as a card turned in the hand (Balatro). With a mouse only, and
// never when the device asks for less motion.
(function () {
    if (!matchMedia('(hover: hover) and (pointer: fine)').matches || matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    var LEAN = 16;          // degrees, the mouse at a card's edge
    var current = null;

    function rest(card) {
        card.style.removeProperty('--rx');
        card.style.removeProperty('--ry');
    }

    document.addEventListener('pointermove', function (e) {
        var slot = e.target.closest ? e.target.closest('.pcard-slot') : null;
        var card = slot && slot.querySelector('.pcard');
        if (current && current != card) {
            rest(current);
        }
        current = card;
        if (!card) {
            return;
        }
        var r = card.getBoundingClientRect();
        var x = Math.max(-.5, Math.min(.5, (e.clientX - r.left) / r.width - .5));
        var y = Math.max(-.5, Math.min(.5, (e.clientY - r.top) / r.height - .5));
        card.style.setProperty('--ry', (x * LEAN).toFixed(1) + 'deg');
        card.style.setProperty('--rx', (-y * LEAN).toFixed(1) + 'deg');
    });
    document.documentElement.addEventListener('pointerleave', function () {
        if (current) {
            rest(current);
            current = null;
        }
    });
})();
