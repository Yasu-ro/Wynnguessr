# WynnGuessr — wynndle.com

GeoGuessr dans le monde de Wynncraft (Flask + Leaflet + Pannellum). Projet de
**Ched3**, forké, hébergé et beaucoup modifié pour Yasuro et ses amis.

Lire d'abord `/home/yasuro/CLAUDE.md` (machine, règles de travail). Ce fichier
garde ce qu'on ne redécouvre pas en lisant le code : décisions, pièges, méthode.

---

## Dépôt et règles

- `origin` = fork `Yasu-ro/Wynnguessr` (public), `upstream` = `Ched3/Wynnguessr`.
  **Toute modification est commitée et poussée sur le fork**, dans le même
  mouvement (demande de Yasuro : « pour garder les choses fair »). Identité git
  locale au dépôt : `Yasu-ro` + adresse noreply GitHub.
- **Jamais commités** (`.gitignore`) : `database.db` (comptes des joueurs ;
  il reste suivi, donc toujours « modifié » : normal), `secret_key` (clé des
  sessions, la supprimer déconnecte tout le monde), `wynncraft_oauth.json`
  (identifiants OAuth Wynncraft, 0600).
- **Langues** : interface en **anglais**, textes **minimes**, compréhensibles
  par un enfant, rien d'inutile. Code et commentaires en anglais comme le code
  d'origine ; messages de commit en français.
- **Minimalisme** : Yasuro refuse les fonctionnalités non demandées. Proposer,
  ne pas empiler.

## Faire tourner

- Service utilisateur `wynnguessr` : gunicorn (venv `.venv`, 1 worker, 8 threads)
  sur `127.0.0.1:8790`, journal d'accès activé (`journalctl --user -u wynnguessr`).
  gunicorn est en 26.x : la 20.1 du dépôt d'origine plante sous Python 3.13.
- Après modif de `app.py` ou d'un template : `systemctl --user restart wynnguessr`.
  Les fichiers statiques n'en ont pas besoin.
- **Piège payé deux fois** : `pkill -f "...gunicorn..."` tue aussi le shell qui
  lance la commande (la ligne contient le motif). Tuer par PID via `ss -ltnp`.
- Exposition :
  - `https://wynndle.com` : tunnel Cloudflare, service `cloudflared`
    (`~/.cloudflared/config.yml`, voir le CLAUDE.md racine). Adresse principale.
  - `https://yasuro.tailae2613.ts.net/wynnguessr/` : Funnel, ancienne adresse,
    **avec la barre finale**.
- **Tous les liens sont relatifs** (`mode`, `api/...`, `static/...`, redirections
  `'./'`, `'../room?code='`) : le site doit marcher à la racine *et* sous
  `/wynnguessr/`. Ne jamais écrire de lien absolu `/...`.
- **Fichiers statiques versionnés** : `asset('js/room.js')` ajoute `?v=<mtime>`.
  Cloudflare impose 4 h de cache navigateur (il écrase le `no-cache` de Flask) :
  sans ça, les joueurs gardent l'ancien script (bug « on ne voit pas les PV »).
- Pas de flash blanc : chaque `<head>` pose `background-color: #6b5236` d'emblée.

## Base de données (SQLite, `database.db`)

Une connexion **par requête** (`connect()`) ; l'origine partageait un curseur
entre threads. Les salons ouvrent `BEGIN IMMEDIATE` (`room_tx()`) : deux requêtes
ne font jamais avancer un salon en même temps.

Colonnes ajoutées à la base d'origine (migrations au démarrage, `ALTER TABLE`
si absente) : `users.guest`, `users.mc_uuid`, `users.mc_name`, `scores.mode`,
`scores.room`. Tables à nous : `rooms`, `room_players` (`live`, `last_seen`,
`recorded`, `seat`), `room_guesses` (`at`, `time`), `room_chat`.

Avant toute migration à la main : copier `database.db` dans le scratchpad.

## Comptes

- Compte classique (mot de passe), **invité** (pseudo seul, `users.guest=1`,
  sans mot de passe : multijoueur uniquement, **jamais au classement**, pas de
  profil), ou **Wynncraft** (OAuth2).
- Session permanente 31 jours ; `secret_key` en fichier → un redémarrage ne
  déconnecte plus. `session['loggedin']` = vrai compte ; un invité a `user_id`
  mais pas `loggedin`.
- `next_page()` : après connexion, retour à la page d'origine (lien d'invitation
  d'un salon, `mode?play=friends`…), filtré par regex contre les redirections
  ouvertes.
- Pseudos : un invité ne peut pas prendre le nom d'un compte, ni celui d'un
  joueur du même salon ; une inscription ne peut pas prendre un `mc_name` vérifié.

### Login with Wynncraft (OAuth2, scope `identify`)

- Application créée par Yasuro sur `wynncraft.com/account/dashboard?section=applications`,
  privée (secret côté serveur), redirect URI `https://wynndle.com/auth/wynncraft/callback`.
  Sans `wynncraft_oauth.json`, le bouton n'apparaît pas.
- Flux : `/auth/wynncraft` (state en session) → Wynncraft → `/callback` →
  `POST /v3/oauth/token` → `GET /v3/oauth/me` → profil `primary`.
  Joueur identifié par **UUID** ; `mc_name` rafraîchi à chaque connexion.
  Connecté → liaison du compte ; sinon création/connexion du compte Minecraft.
- **Pièges payés** :
  - leur générateur d'URL produit `redirect_uri=[object Object]` : l'URL
    d'autorisation est construite par nous (`authorize_url` du JSON) ;
  - `WOAUTH10 Redirect URL is invalid` = redirect URI non enregistrée chez eux ;
  - Cloudflare devant leur API refuse le User-Agent de Python (**erreur 1010**) :
    `wynn_api()` envoie `WynnGuessr (+https://wynndle.com)` ;
  - les erreurs de ces routes redirigent vers `apology` (deux dossiers de
    profondeur : une page rendue sur place perdait son CSS).
- API publique utile (sans clé) : `api.wynncraft.com/v3/player/<nom>` (guilde,
  rang…), 50 req/min. Profil public : `wynncraft.com/stats/player/<nom>`.
  Yasuro a refusé d'afficher guildes et autres infos : seulement coche + lien.

## Modes de jeu

Classic par défaut (le jeu d'origine). Solo : Classic, **Survival**. Salons :
Classic, **Duel**, **Battle Royale**. Constantes en tête de la section salons.

- **Survival** (solo, `game.js`) : rester à < 500 blocs (`SURVIVAL`) ; score =
  série. **Enregistré dès la fin de partie** (`saveIfOver`), pas au clic sur
  « See Results » (les joueurs quittaient avant → rien au classement). Série 0
  non enregistrée.
- **Duel** : 6 000 PV ; chaque manche on perd `(meilleur score − le sien) ×
  multiplicateur` (×1 manches 1-2, puis +0,5 par manche).
- **Battle Royale** : 3 vies ; le pire de la manche perd une vie (égalité = rien) ;
  un bullseye (≥ 4 950 pts) ne perd **jamais** de vie et en rend une (règle
  ajoutée après une vraie partie : 4 976 contre 4 979 coûtait une vie).
- Duel/BR : joueurs présents au lancement = `seat=1` ; éliminés et retardataires
  regardent. Au moins 2 joueurs. Jusqu'à 25 manches. **PV et vies ne sont
  stockés nulle part** : `standings()` rejoue les guess à chaque fois.
- Seules les parties Classic (solo et salon) vont au classement ; les comptes
  invités jamais.

## Salons (multijoueur)

- Code 6 caractères sans 0/O/1/I/L, insensible à la casse ; lien `room?code=`.
- Machine à états paresseuse : **chaque requête de salon appelle `tick()`**, pas
  de thread. `waiting` → `playing` (manche ouverte, puis `round_end` posé) →
  révélation `REVEAL`=10 s → manche suivante → `finished`.
- Une manche se ferme quand tous les joueurs présents (`last_seen` < `AWAY`=10 s)
  ont répondu, ou au délai : chrono éventuel, raccourci à `LAST_CALL`=15 s après
  le premier guess. `GRACE`=1 s de tolérance réseau.
- Hôte absent `HOST_AWAY`=30 s dans la salle d'attente → la main passe.
- Rejoindre avant la fin = jouer en direct (même en cours) ; un salon Classic
  terminé se rejoue en différé, même classement.
- « Play Again » : nouveau salon (`next_code`), tout le monde suit.
- Scores calculés **côté serveur** (`guess_score`, même formule que `game.js`).
- Couleur d'un joueur = son rang d'arrivée (`COLORS` dans `room.js`).
- Chat : `room_chat`, 200 caractères, 0,7 s entre deux messages, livré par le
  poll (`chat=<dernier id>`). Un seul widget déplacé selon l'écran : sous les
  joueurs (attente), en haut à gauche sur le panorama (replié par défaut sur
  téléphone, **sous la carte** sinon il cache « Guess! »), dans le panneau de
  droite en révélation (jamais sur la carte : il cachait la réponse), sous les
  résultats.
- Temps restant : boîte **statique sous le bandeau**, sans animation, rouge à
  10 s (Yasuro a refusé le gros chiffre au centre et les pulsations).
- Sons générés en WebAudio (aucun fichier) : un joueur valide ; 10, 5, 3, 2, 1 s.
  Bouton muet mémorisé (localStorage). Volume jamais validé à l'oreille.
- `beforeunload` : confirmation pour quitter pendant une manche/révélation
  (salon) ou une partie solo ; pas pour les redirections du jeu lui-même.

## Pages et direction artistique

**Tout doit respecter la DA, partout** (Yasuro y tient beaucoup) :
beige `#baaa80`, bordure brune `#857361`, brun foncé `#402523`, boutons verts
`#83C73C` à bordure noire, cases blanches à bordure noire, choix coché
`#378537`. **Aucun panneau sombre** (le bleu nuit `#141323` de l'origine a été
remplacé partout). Polices Ubuntu + Architects Daughter (menu), reliefs en
`box-shadow` inset, titres `h1.sign` sur panneau suspendu (les cordes font
200 px et passent sous la barre de menu), page courante en jaune dans le menu.
Inspiré de wynncraft.com **sans rien en reprendre** (ni image ni logo).

- `mode` : choix **Solo / With Friends** d'abord (`?play=solo|friends`), puis
  réglages (`settings.html` + `modes.html`, partagés avec la salle d'attente).
- `profile` : stats multijoueur (parties, victoires) + historique façon
  Valorant (`history()` ; une partie de salon est dans `scores` avec `room`,
  pour ne pas la compter deux fois). Volontairement différent du classement.
- `leaderboard` : onglets Classic/Survival, filtres, meilleure partie par
  joueur ; un pseudo lié Wynncraft = lien souligné vert + coche + icône.
- Pied de page hors jeu : Made by Ched3 · Hosted & modified by Yasuro ·
  Wynncraft · Fan-made, not official.

## Tester

- Navigateur headless : Playwright + Chromium installés dans le **scratchpad**
  (éphémère : `python3 -m venv <scratch>/pw && pip install playwright &&
  PLAYWRIGHT_BROWSERS_PATH=<scratch>/browsers playwright install chromium`).
  Tester en local (`127.0.0.1:8790`) **et** via `https://wynndle.com`.
- Comptes de test préfixés `zz_` ; **toujours les supprimer après** avec leurs
  salons, scores, messages (sans toucher un salon où joue un vrai joueur).
- Pour placer une réponse précise : poster sur `api/room/<code>/guess` avec les
  coordonnées lues dans la base (± un décalage) ; en solo, viser via
  `images[round-1]` et `map.latLngToContainerPoint`.
- Cookie de session de test : `app.session_interface.get_signing_serializer(app).dumps({...})`.
- Ne pas cliquer le coin haut-gauche de la carte : c'est le bouton de zoom.
- Les vrais joueurs (Yasuro, Ragus, kemmi, 13tiak, Yulofox, Roguefort…) jouent
  réellement : regarder la base avant de supposer un bug.

## En suspens

- Survival de Yasuro absente du classement après correction : le test réel
  passe ; journal d'accès activé pour voir sa prochaine partie.
- Flash blanc entre pages : corrigé sans vérification visuelle.
- `www.wynndle.com` non configuré ; « Always Use HTTPS » à activer côté Cloudflare.
