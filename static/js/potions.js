// The potions of Survival, alone (survival.js) and with friends (room.js):
// what they are called and do, their bottles (static/potions.png, drawn by
// tools/potions.py), the hearts, the emeralds, and the throw.

// name: what it is called, what it does; the bottles in static/potions.png in BOTTLES' order
var POTIONS = {
    swiftness: ['Swiftness', '20 seconds to find it, but a bigger safe zone.'],
    mining_fatigue: ['Mining Fatigue', 'No zooming on the map.'],
    wither: ['Wither', 'You lose 0.5 {heart} every 5 seconds until you guess.'],
    regeneration: ['Regeneration', 'Guess inside the safe zone to get 2 {heart} back.'],
    nausea: ['Nausea', 'The view turns by itself, and your pin lands a little off.'],
    darkness: ['Darkness', 'You see the picture for 10 seconds, then it goes dark.'],
    blindness: ['Blindness', 'Thick fog: you only see what is close.']
};
var BOTTLES = ['swiftness', 'mining_fatigue', 'wither', 'regeneration', 'nausea', 'darkness', 'blindness'];
var DARK_AFTER = 10;    // Darkness: seconds of picture before the dark (Yasuro: 5 was too short); level II: half
var NAUSEA_SPIN = -40;  // Nausea: degrees per second the view turns by itself (a turn in 9 s; Yasuro: -9 was far too slow)
var WITHER_EVERY = 5;   // Wither: seconds for half a heart; level II: half

function potionIcon(name) {
    return "<i class='potion-icon' style='--i:" + BOTTLES.indexOf(name) + "'></i>";
}

// a potion's level as Minecraft writes it: Wither, Wither II, Wither III...
function roman(level) {
    return level > 1 ? ' ' + (['II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'][level - 2] || level) : '';
}

// what it does, at its level (with friends potions stack: Wither II is twice
// as strong), with the hearts drawn in the text
function potionText(name, hardcore, level) {
    var k = level || 1, text = POTIONS[name][1];
    if (k > 1) {
        text = {
            swiftness: Math.max(10, 25 - 5 * k) + ' seconds to find it, but a bigger safe zone.',
            wither: 'You lose 0.5 {heart} every ' + +(WITHER_EVERY / k).toFixed(1) + ' seconds until you guess.',
            regeneration: 'Guess inside the safe zone to get ' + 2 * k + ' {heart} back.',
            nausea: 'The view turns ' + k + ' times faster, and your pin lands further off.',
            darkness: 'You see the picture for ' + +(DARK_AFTER / k).toFixed(1) + ' seconds, then it goes dark.'
        }[name] || text;
    }
    return text.replace(/\{heart\}/g, heartIcon(hardcore));
}

// a heart drawn in the text, and an amount of half-hearts: 13 -> "6.5"
function heartIcon(hardcore) {
    return "<i class='heart inline" + (hardcore ? ' hc' : '') + "'></i>";
}
function amount(half) {
    return String(half / 2);
}

// the hearts, as in Minecraft: max is counted in half-hearts
function drawHearts(el, hp, max, hardcore) {
    var html = '', hard = hardcore ? ' hc' : '';
    for (var i = 0; i < max / 2; i++) {
        var left = hp - 2 * i;
        html += "<i class='heart " + (left >= 2 ? 'full' : left == 1 ? 'half' : 'empty') + hard + "'></i>";
    }
    el.innerHTML = html;
}

// Wynncraft's money (tools/potions.py draws it)
function emeraldIcon() {
    return "<i class='emerald'></i>";
}

// the creeper: a flash, the screen shakes, the bang
function explode() {
    Sfx.play('boom');
    var flash = document.createElement('div');
    flash.className = 'boom';
    document.body.appendChild(flash);
    replay(document.getElementById('guess-screen'), 'shake');
    setTimeout(function () { flash.remove(); }, 900);
}

// The throw: static/potion-throw.gif, Yasuro's (97 frames): someone runs in
// and throws the bottle, which bursts over the screen; its sounds on its
// frames. Loaded once; a new address for it each time plays it from its first frame
var THROW_MS = 3070;    // its length
var THROWN_MS = 1690;   // the bottle leaves the hand (frame 51): the throw
var SPLASH_MS = 1950;   // it bursts (frame 60): the glass
var THROW_GIF = document.getElementById('potion-throw').dataset.throw;   // its address, versioned (asset())
var throwGif = null;
fetch(THROW_GIF).then(function (r) { return r.blob(); }).then(function (b) { throwGif = b; }).catch(function () {});

// plays the throw over the whole screen, then done(); without the picture, done() at once
function throwAnimation(done) {
    var url = throwGif ? URL.createObjectURL(throwGif) : THROW_GIF + '&' + Date.now();
    // the sounds count from when the picture is there, not from when it is asked for
    $('#potion-gif').off('load error').one('load', function () {
        setTimeout(function () { Sfx.play('throw'); }, THROWN_MS);
        setTimeout(function () { Sfx.play('splash'); }, SPLASH_MS);
        setTimeout(function () {
            $('#potion-throw').prop('hidden', true);
            if (throwGif) {
                URL.revokeObjectURL(url);
            }
            done();
        }, THROW_MS);
    }).one('error', function () {
        $('#potion-throw').prop('hidden', true);
        done();
    }).attr('src', url);
    $('#potion-throw').prop('hidden', false);
}
