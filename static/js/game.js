var provinces = $('#game-variables').attr('provinces');
var look = $('#game-variables').attr('look');
var timeLimit = $('#game-variables').attr('timeLimit');
var LOCATIONS = $('#game-variables').attr('locations');
var round = 0;
var maxRounds = $('#game-variables').attr('rounds');
var score = 0;
var totalScore = 0;
var mode = $('#game-variables').attr('mode');
var account = $('#game-variables').attr('account') == '1';
var xpResult = null;     // what the saved game brought: {xp, gained}, or {pending} kept for a login; 'pending' on its way
var SURVIVAL = 500; // survival: how close a guess must land to keep going, in blocks
var streak = 0;
var images = [];
var markers = [];
var polylines = [];
var map;
var timer = null;
var scoreMap;
var totalTime = 0;
var greenIcon = new L.Icon({
    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
});

// leaving before the end of the game asks first
var gameOver = false;
window.addEventListener('beforeunload', function (e) {
    if (!gameOver) {
        e.preventDefault();
        e.returnValue = '';
    }
});

// Document ready function
$(document).ready(function() {
    fetchLocations().then(() => {
        showNextLocation();
    });
});

// Fetch location data from the server
function fetchLocations() {
    return fetch('api/locations')
    .then(response => response.json())
    .then(data => {
        LOCATIONS = data;
    });
}

// Handle map click event to set a marker
function onMapClick(e) {
    if (markers[round - 1] != undefined) {
        map.removeLayer(markers[round - 1]);
    }
    markers[round - 1] = L.marker(e.latlng).addTo(map);
}

// Display the score screen
function showScoreScreen() {
    if(timeLimit > 0){
        clearInterval(timer);
    }
    showContent('score-screen');
    document.getElementById('score-screen').innerHTML =
        "<div class = 'score-map' id='scoreMap'></div>" + 
        "<div id = 'score-container'>" +
        "<p id='score' class='score-info'></p>" + 
        "<div class = 'progress-bar'>" +
        "<div class = 'progress' id = 'progress'></div></div>" + 
        "<p id='distance' class='score-info'></p>" +
        "<button id='next-button' class='next-button'>Next Location</button></div>";
    document.getElementById('guess-screen').innerHTML = "";

    scoreMap = L.map('scoreMap', {
        crs: L.CRS.Simple,
        minZoom: -3,
        maxZoom: 5,
        attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'
    }).setView([0, 0], 0);
    var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
    L.imageOverlay('static/map-2026.webp', bounds).addTo(scoreMap);
    crisp(scoreMap);
    scoreMap.setView([3072, -256], -1);
    scoreMap.on('click', onMapClick);

    var xActual = images[round - 1]['X'];
    var zActual = images[round - 1]['Z'];
    if(markers[round - 1] == undefined){
        document.getElementById('score').innerHTML = "No location selected!";
        document.getElementById('progress').style.width = "0%";
        document.getElementById('distance').innerHTML = mode == 'survival' ? "Game over!" : "Distance: 0 blocks away!";
        saveIfOver(false);
        document.getElementById('next-button').onclick = function(){
            nextStep(false);
        };
        if (mode == 'survival') {
            document.getElementById('next-button').innerHTML = "See Results";
        }
        L.marker([-zActual, xActual], { icon: greenIcon }).addTo(scoreMap);
        scoreMap.fitBounds([[[-zActual, xActual], [-zActual, xActual]]]);
        return;
    }
    var xGuess = markers[round - 1].getLatLng().lng;
    var zGuess = -markers[round - 1].getLatLng().lat;

    var distance = Math.sqrt(Math.pow(xActual - xGuess, 2) + Math.pow(zActual - zGuess, 2)).toFixed(2);
    score = Math.round(5200/(1 + .002* Math.E ** (.0042*distance + 3)) + .822);
    if (score < 0) {
        score = 0;
    }
    totalScore += score;

    document.getElementById('distance').innerHTML = "Distance: " + distance + " blocks away!";
    document.getElementById('progress').style.width = (score / 5000) * 100 + "%";
    document.getElementById('totalScore').innerHTML = "Score: " + totalScore;
    document.getElementById('score').innerHTML = score + " points!";

    var survived = distance <= SURVIVAL;
    if (mode == 'survival') {
        if (survived) {
            streak++;
        }
        document.getElementById('totalScore').innerHTML = "Streak: " + streak;
        document.getElementById('score').innerHTML = survived
            ? "Within " + SURVIVAL + " blocks: streak " + streak + "!"
            : "More than " + SURVIVAL + " blocks away: game over!";
        if (!survived) {
            document.getElementById('next-button').innerHTML = "See Results";
        }
    }
    saveIfOver(survived);
    document.getElementById('next-button').onclick = function(){
        nextStep(survived);
    };
    L.marker([-zActual, xActual], { icon: greenIcon }).addTo(scoreMap);
    
    L.marker([-zGuess, xGuess]).addTo(scoreMap);
    
    //draws line between guess and actual location
    polylines[round - 1] = L.polyline([[-zActual, xActual], [-zGuess, xGuess]], { color: 'red' }).addTo(scoreMap);
    scoreMap.fitBounds(polylines[round - 1].getBounds());
}

function showNextLocation() {
    showContent('guess-screen');
    round++;
    $('#time-left').html("Time: " + timeLimit);
    document.getElementById('guess-screen').innerHTML = 
    "<div id='game-panorama'></div>" +
    "<div class='map-container' id='map-container'>" +
        "<div class='map' id='map'></div>" +
        "<button id='guess-button' class='guess-button' type='submit'>Guess!</button></div>";
    
    map = L.map('map', {
        crs: L.CRS.Simple,
        minZoom: -3,
        maxZoom: 5,
        renderer: L.canvas({ padding: 10 }), 
        attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'
    }).setView([0, 0], 0);

    var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
    L.imageOverlay('static/map-2026.webp', bounds).addTo(map);
    crisp(map);
    map.setView([3072, -256], -2);
    map.on('click', onMapClick);

    // Selects a random location from the list of locations and removes it to prevent duplicates
    var rand = Math.floor(Math.random() * LOCATIONS.length);
    images[round - 1] = LOCATIONS[rand];
    LOCATIONS.splice(rand, 1);

    // Sets up guess button functionality
    document.getElementById('guess-button').onclick = function () {
        if (markers[round - 1] === undefined) {
            document.getElementById('guess-button').innerHTML = "Select a location first!";
            document.getElementById('guess-button').style.backgroundColor = "red";
            return;
        }
        clearInterval(timer);
        showScoreScreen();
    };

    /*var vrView = new VRView.Player('#vrview', {
        image: images[round - 1]['url'],
        is_stereo: false,
        is_autopan_off: true,
    });*/

    //initailize panorama viewer
    let locked = look === 'True';
    let viewer = pannellum.viewer('game-panorama', panoramaConfig(images[round - 1]['url'], {
        "autoLoad": true,
        "draggable": !locked,
        "mouseZoom": !locked,
        "keyboardZoom": !locked,
        "disableKeyboardCtrl": locked,
        "showControls": !locked
    }));
    // multires tiles report "load" while the viewer is still being built,
    // before anyone listens: then the clock starts from here
    let clock = function(){
        let countdown = timeLimit;
        timer = setInterval(function(){
            if(countdown >= 0){
                document.getElementById('time-left').innerHTML = "Time: " + countdown;
                countdown = Math.round((countdown - .01) * 100) / 100;
                if (countdown < 0) {
                    clearInterval(timer);
                    showScoreScreen();
                }
            }
            totalTime = Math.round((totalTime + .01) * 100) / 100;

        }, 10);
    };
    if (viewer.isLoaded()) clock(); else viewer.on('load', clock);

    // Remove all markers from the map
    map.eachLayer((layer) => {
        if (layer instanceof L.Marker) {
            layer.remove();
        }
    });

    if (polylines[round - 1] !== undefined) {
        map.removeLayer(polyline);
    }
    marker = null;
    document.getElementById('round-number').innerHTML = mode == 'survival' ? "Round: " + round : "Round: " + round + "/" + maxRounds;
    if (mode == 'survival') {
        document.getElementById('totalScore').innerHTML = "Streak: " + streak;
    }
    
    
}

// after a score: the next location, or the end of the game
function isOver(survived) {
    return mode == 'survival' ? !survived || LOCATIONS.length == 0 : round >= maxRounds;
}

// the score is saved as soon as the game ends, not on the button:
// a player who leaves on the last score screen keeps their game
var saved = false;
function saveIfOver(survived) {
    if (saved || !isOver(survived)) {
        return;
    }
    saved = true;
    gameOver = true;
    var game;
    if (mode == 'survival') {
        if (streak == 0) {
            return;  // nothing found: nothing for the leaderboard
        }
        game = {'score': streak, 'look': look, 'provinces': provinces, 'totalTime': totalTime, 'mode': 'survival'};
    } else {
        game = {'score': totalScore, 'look': look, 'provinces': provinces, 'totalTime': totalTime, 'rounds': maxRounds};
    }
    xpResult = 'pending';
    $.ajax({url: 'api/score', data: game, type: 'post', dataType: 'json'})
        .done(function (r) {
            xpResult = r.success || r.pending ? r : null;
            showGain();
        })
        .fail(function (error) {
            xpResult = null;
            console.log(error);
            showGain();
        });
}

// the end screen: the XP the game brought; without an account, the game is
// kept by the server and saved to the account the player logs in to
function showGain() {
    var slot = document.getElementById('xp-slot');
    if (!slot || slot.childNodes.length || xpResult == 'pending') {
        return;
    }
    if (xpResult && xpResult.pending) {
        slot.innerHTML = "<p class='xp-note'><a href='login?next=profile'>Log in</a> or <a href='register?next=profile'>make an account</a> " +
            "to save this score and earn XP.</p>";
    } else if (!account) {
        slot.innerHTML = "<p class='xp-note'><a href='login?next=mode%3Fplay%3Dsolo'>Log in</a> to earn XP and level up.</p>";
    } else if (xpResult) {
        xpGain(slot, xpResult.xp, xpResult.gained);
    }
}

function nextStep(survived) {
    if (isOver(survived)) {
        finalScore();
    } else {
        showNextLocation();
    }
}

function showContent(contentId){
    document.getElementById('guess-screen').style.display = "none";
    document.getElementById('score-screen').style.display = "none";
    document.getElementById(contentId).style.display = contentId == 'score-screen' ? "flex" : "block";
}

function finalScore() {
    gameOver = true;
    showContent('score-screen');
    document.getElementById('score-screen').innerHTML =
        "<div class = 'score-map' id='scoreMap'></div>" + 
        "<div id = 'score-container'>" +
        "<p id='Finish Message' class='score-info'></p>" + 
        "<div class = 'progress-bar'>" +
        "<div class = 'progress' id = 'progress'></div></div>" + 
        "<p id='score' class='score-info'></p>" +
        "<div id='xp-slot' class='xp-slot'></div>" +
        "<button id='next-button' class='next-button'>Play Again!</button></div>";
    document.getElementById('guess-screen').innerHTML = "";
    showGain();

    scoreMap = L.map('scoreMap', {
        crs: L.CRS.Simple,
        minZoom: -3,
        maxZoom: 5,
        attribution: '<a href="https://wynntils.com/">Wynntils Map</a>'
        //renderer: L.canvas({ padding: 10 })
    }).setView([0, 0], 0);
    var bounds = [[0, -2560], [6144, 2048]]; // Map bounds: Wynntils main map, 1 px = 1 block
    L.imageOverlay('static/map-2026.webp', bounds).addTo(scoreMap);
    crisp(scoreMap);
    scoreMap.setView([3072, -256], -1);
    scoreMap.on('click', onMapClick);
    
    var featureGroup = [];
    for(let i = 0; i < images.length; i++){
        
        let answer = L.marker([-images[i]['Z'], images[i]['X']], { icon: greenIcon }).addTo(scoreMap);
        featureGroup.push(answer);
        if(markers[i] != undefined){
            L.marker(markers[i].getLatLng()).addTo(scoreMap);
            featureGroup.push(markers[i]);
        }
        if(polylines[i] != undefined){
            polylines[i].addTo(scoreMap);
        }
    }
    var group = new L.featureGroup(featureGroup);
    scoreMap.fitBounds(group.getBounds());
    let sec = " Seconds";
    if(totalTime == 1){
        sec = " Second";
    }
    let time = totalTime
    let hours = Math.floor(time / 3600);
    let minutes = Math.floor((time % 3600) / 60);
    let seconds = Math.floor(time % 60);
    let milliseconds = Math.round(time % 1 * 1000);
    let timeString = '';
    if(hours > 0){
        timeString += hours + 'h ';
    }
    if(minutes > 0){
        timeString += minutes + 'm ';
    }
    if(seconds > 0){
        timeString += seconds + 's ';
    }
    timeString += milliseconds + 'ms';
    document.getElementById('Finish Message').innerHTML = "Game Finished! Total Time: " + timeString;
    document.getElementById('score').innerHTML = "Final Score: " + totalScore + "/" + maxRounds * 5000;
    document.getElementById('progress').style.width = (totalScore / (maxRounds * 5000)) * 100 + "%";
    if (mode == 'survival') {
        document.getElementById('Finish Message').innerHTML = "Game Over! Total Time: " + timeString;
        document.getElementById('score').innerHTML = "Streak: " + streak + (streak == 1 ? " location" : " locations");
        document.querySelector('#score-container .progress-bar').style.display = 'none';
    }
    $('#next-button').click(function(){
        location.reload();
    });
}

// zoomed past 1 px per block, show blocks instead of a blur
function crisp(m) {
    m.on('zoomend', function () { m.getContainer().classList.toggle('crisp', m.getZoom() > 0); });
    m.getContainer().classList.toggle('crisp', m.getZoom() > 0);
}

// a location is one equirectangular image, or (URL ending with "/") a folder
// of multires tiles cut by the server (see make_tiles in app.py)
function panoramaConfig(url, options) {
    var config = url.slice(-1) == '/'
        ? {type: 'multires', multiRes: {basePath: url.slice(0, -1), path: '/%l/%s%y_%x', fallbackPath: '/fallback/%s',
            extension: 'jpg', tileResolution: 512, maxLevel: 4, cubeResolution: 4096}}
        : {type: 'equirectangular', panorama: url};
    for (var k in options) config[k] = options[k];
    return config;
}
