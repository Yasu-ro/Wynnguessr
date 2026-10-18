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
  il reste suivi dans git, mais marqué `git update-index --skip-worktree` dans
  les deux worktrees. **Piège payé le 2026-10-16** : un `git commit -a` l'a
  poussé sur le fork public, retiré par force-push. Ne jamais utiliser
  `commit -a` ici, et refaire le `--skip-worktree` après un nouveau clone), `secret_key` (clé des
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
- **Piège payé le 2026-10-17** : modifier un `.js` directement dans
  `~/Wynnguessr` le met en ligne aussitôt, alors que les templates restent
  ceux du dernier chargement ; un script qui attend un nouveau `<script>` casse
  le jeu jusqu'au rechargement (~3 min de panne ce jour-là). Toujours écrire
  et tester dans la copie isolée, puis copier **tous** les fichiers et
  recharger dans la foulée.
- **Piège payé deux fois** : `pkill -f "...gunicorn..."` tue aussi le shell qui
  lance la commande (la ligne contient le motif). Tuer par PID via `ss -ltnp`.
- **Recharger sans couper** (utile quand le mod est en tournée sur la bêta) :
  `systemctl --user kill -s HUP --kill-whom=main wynnguessr-beta` — gunicorn
  démarre un worker avec le nouveau code, l'ancien finit ses requêtes. Vérifié
  le 2026-10-17 pendant une tournée : aucun envoi du mod perdu.
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
- Pas de flash blanc : `head.html` (inclus partout) pose `background-color: #1d1c19`
  (la pierre du fond) d'emblée.

## Bêta (`beta.wynndle.com`)

Demande de Yasuro : tester et déboguer avant de toucher au vrai site.

- **Worktree git** `~/Wynnguessr-beta` sur la branche **`beta`** (poussée sur
  le fork). Service `wynnguessr-beta`, port **8791**, même `.venv` que la prod.
  Exposée par le même tunnel Cloudflare (règle `beta.wynndle.com` dans
  `config.yml`).
- **Sa propre base** : copie de la base de prod du 2026-10-16 (faite avec
  `sqlite3.backup`, pas `cp`, la base étant vivante). Ce qui s'y joue n'atteint
  jamais le vrai classement. Sa propre `secret_key` (donc sessions séparées).
  Pas de `wynncraft_oauth.json` : la redirect URI enregistrée chez Wynncraft
  est celle de wynndle.com, donc pas de bouton Wynncraft en bêta.
- Travail : on modifie et on commite dans `~/Wynnguessr-beta`. Mise en prod,
  après accord de Yasuro : `git merge beta` dans `~/Wynnguessr`, puis pousser,
  puis `systemctl --user restart wynnguessr` si `app.py` ou un template a changé.
- **`database.db` est suivi par git** : ne jamais le commiter depuis la bêta,
  sinon la fusion écraserait la base de prod par celle de la bêta.

## Carte

`static/map-2026.webp` (en bêta tant que non fusionnée) : carte principale Wynntils (18 tuiles « Main » de
`Wynntils/Static-Storage/Reference/maps.json`, X −2560…2047, Z −6144…−1),
1 px = 1 bloc, webp sans perte (8,7 Mo ; le PNG faisait 30 Mo). Bornes Leaflet
`[[0, -2560], [6144, 2048]]` (lat = −Z, lng = X), écrites dans `game.js` (×3)
et `room.js`. Pour la refaire : réassembler les tuiles à
`(x1 + 2560, z1 + 6144)` et vérifier les md5 du JSON. **Changer de nom de
fichier à chaque nouvelle carte** : l'URL vient du JS, sans `asset()`, et
Cloudflare garderait 4 h l'ancienne image avec les nouvelles bornes.
Fruma (en bas à gauche) est sur la carte mais n'a encore aucun lieu ni
province.

## Tri des lieux (`/review`, bêta)

Demande de Yasuro : voir sur la carte où il a déjà pris des photos, et trier
quand il veut. Page réservée aux comptes de `REVIEWERS` (**Yasuro**, et le compte **kemmi** ajouté
le 2026-10-17 à sa demande pour l'aider à trier), qui n'existe
que là où il y a un fichier **`capture_key`** (bêta seulement, 0600, hors git :
c'est la clé à mettre dans le mod). Ailleurs, `/review` et `/api/capture`
répondent 404/403.

- Colonnes `locations.review` (`old` = jeu d'origine, `planned` = endroit
  posé sur la carte, sans photo, `new` = capture pas encore vue, `kept`,
  `deleted`) et `locations.difficulty` (**plus utilisée** :
  Yasuro a retiré Easy/Medium/Hard le 2026-10-17, « juste Keep ou Delete pour
  l'instant » ; la colonne reste, vide). Le jeu ne tire
  que `old` et `kept` (`PLAYABLE`).
- Points : bleu = `planned`, rouge = `new`, vert = `kept` ; la page se recharge
  toutes les 10 s, donc une photo prise apparaît seule.
- **2026-10-16, décision de Yasuro : on repart de zéro.** Les 24 premières
  captures ont été effacées (originaux JPEG gardés dans `~/wynndle-captures/`)
  et les **622 lieux d'origine sont passés en `deleted` dans la base de la
  bêta** (pris sur l'ancienne carte, tous à refaire). La bêta n'a donc aucun
  lieu jouable tant que rien n'est gardé. (Depuis le premier Push du
  2026-10-17, la prod a les mêmes : voir « Publication des lieux ».)
- 2026-10-17, demande de Yasuro : **un point `planned` à chacun des 622
  lieux d'origine** (province d'origine reprise), sauf hors couverture (0) et
  à moins de 30 blocs d'un point existant (66) → 556 ajoutés, par script sur
  la base de la bêta.
- Plein écran : curseur **Spin** (rotation automatique de Pannellum, 0 à
  60 °/s, reprend 2 s après un glisser) et bouton **Previous** (pile des
  photos vues, pour rattraper un Keep trop rapide ; un `kept` supprimé passe
  en `deleted`, ses tuiles restent).
- **Trous** (demande de Yasuro : « pas faciles à voir ») : un chunk manquant
  qu'on ne peut pas relier au bord de la carte par d'autres chunks manquants
  est en **magenta**, et chaque groupe est entouré d'un cercle magenta de
  taille fixe (un chunk ne fait qu'un pixel vu de loin).
- **Plein écran** (bouton « Full screen » du panneau) : la photo sur tout
  l'écran, une mini-carte zoomée sur le point (pour vérifier que les
  coordonnées tombent au bon endroit), barre DA en bas. Keep/Delete passent
  au point rouge **le plus proche** (la revue avance sur la carte) ; Next
  saute ; Échap ferme.
- **Delete sans confirmation** (demande de Yasuro : trop lent ; et après
  « ne plus demander » dans Firefox, `confirm()` renvoyait toujours faux, la
  suppression était devenue impossible). Ne pas remettre de `confirm()`.
- Clic sur la carte = point `planned` (`POST api/review/plan`), refusé dans
  une zone grise. Le mod (`Tour`) lit `GET api/capture/planned` et renvoie la
  photo avec `&planned=<id>` : la ligne garde sa place et passe en `new`.
- **Voile gris** : le mod envoie à l'ouverture du monde solo
  (`POST api/coverage`, `coverage.json` hors git) un bit par chunk, par région
  (`"rx,rz"` → base64 de 128 octets, chunk `(x&31) + (z&31)*32`, bit de poids
  faible d'abord). **Un chunk ne compte que s'il contient un bloc autre que
  de l'air** (palette des `block_states`, NBT lu dans le `.mca`). **Piège
  payé** : la 1.4.0 ne lisait que l'en-tête (offset ≠ 0) et Yasuro voyait
  « beaucoup plus de chargé que de téléchargé ». Simple World Downloader crée
  ses mondes avec un générateur **plat sans couche** (vide) : chaque chunk que
  le jeu fabrique lui-même (vol en solo hors zone, Distant Horizons) est
  sauvé, vide, avec un offset. Pourquoi refuser le gris : y téléporter le joueur ferait générer
  du terrain Minecraft ordinaire dans la copie, que la couverture compterait
  ensuite comme téléchargé.
- Keep garde tel quel ; la province est préremplie (Fruma si
  `x < -1000` et `z > -2000`, sinon celle du lieu le plus proche) et se corrige.
- Delete : une capture `new` est effacée (ligne + fichier, jamais jouée) ; tout
  autre lieu passe en `deleted` sans être effacé, car un salon terminé peut
  encore le rejouer par son id.
- **Multirésolution** (mod 1.6.0, demande de Yasuro : « les panoramas sont
  un peu flous ») : le mod envoie un **zip des 6 faces en 4096** (JPEG 95,
  ~13 Mo), `make_tiles()` les découpe en tuiles Pannellum 512 px sur 4
  niveaux + `fallback/` (~16 Mo, ~516 fichiers par lieu), dans
  `static/tiles/<nom>/` = **lien vers `/data/wynnguessr-tiles`** (hors git).
  Une URL de lieu qui finit par `/` = tuiles ; `panoramaConfig()` (game.js,
  room.js, review.js) choisit le mode, avec `CUBE`/`TILE` d'`app.py` recopiés
  en dur. Correspondance des faces vérifiée en comparant, sous 6 angles, une
  image découpée à la manière de Minecraft et l'originale : Minecraft
  0..5 = Pannellum `f r b l u d`. La netteté venait du manque de pixels (faces
  2048, rééchantillonnées en équirectangulaire), pas du webp (−1 % mesuré).
  **Piège payé (1.6.0)** : les PNG de Minecraft ont un canal alpha, que
  l'encodeur JPEG de Java refuse (« Bogus input colorspace ») ; mes faces de
  test étaient RGB, d'où un test vert et une 1.6.0 cassée en jeu. `opaque()`
  convertit avant l'encodage. **Tester avec des PNG RGBA.**
  **Piège payé** : en multires, Pannellum émet `load` pendant la construction
  du viewer, avant tout `on('load')` : le chrono de `game.js` ne démarrait
  plus. D'où `if (viewer.isLoaded()) clock()`.
  Pillow ajouté au `.venv` (partagé avec la prod) pour ce découpage.
- **Noms aléatoires** (`secrets.token_hex(10)`) pour les tuiles et les
  captures : **piège évité de justesse** (2026-10-17), les noms
  `<X>_<Z>_<horodatage>` donnaient la réponse à quiconque ouvrait les outils
  du navigateur. Les 18 premières ont été renommées. Ne jamais remettre
  d'information de lieu dans une URL d'image.
- **Préchargement en salon** : pendant la révélation, `/api/room/<code>`
  envoie `next_url` ; `room.js` (`preload`) charge l'image suivante, ou les
  tuiles des niveaux 1 à 3 (126 tuiles, le niveau 4 seulement au zoom), avec
  `crossOrigin` comme Pannellum pour que le cache serve. Vérifié en vrai salon
  (2 invités de test). Les fichiers statiques ont `max-age=14400`.
- Captures des mods < 1.6 : webp q85 dans `static/captures/`, **hors git** ;
  toujours acceptées par `/api/capture` (JPEG). Originaux JPEG de Yasuro
  dans `~/wynndle-captures/`.

**Netteté** : au-delà de 1 px par bloc (zoom > 0), toutes les cartes
Leaflet (jeu, salons, tri) passent en `image-rendering: pixelated` (classe
`crisp`) : Firefox lissait l'agrandissement. Les lignes droites visibles sur
la carte (neige/herbe nette…) sont **dans les tuiles Wynntils elles-mêmes**,
pas des jointures d'assemblage (vérifié au pixel : X −1024/Z −2058).

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
- **Rien n'est perdu en se connectant après coup** (2026-10-17, demande de
  Yasuro) : sans compte, la partie solo finie est gardée dans la session
  (`session['pending']`, vérifiée par `solo_game()`), et l'écran de fin dit
  « Log in or make an account to save this score and earn XP » (retour sur le
  profil). Un invité voit la même chose à la fin d'un salon (retour au salon).
  `adopt()`, appelé par la connexion, l'inscription et Wynncraft, enregistre
  la partie gardée et passe au compte les salons de l'invité (`room_players`,
  `room_guesses`, `room_chat`, hôte), sauf ceux où le compte joue déjà ; un
  salon Classic fini passe alors par `record()`, donc au classement.
  L'invité reste dans `users`, vide.

### Profil, pseudo, mot de passe, récupération (2026-10-17, bêta)

Demande de Yasuro (« better profile »), choix faits avec lui :
- **Photo** : par défaut la tête Minecraft du compte Wynncraft lié (skin lu
  chez Mojang, visage + calque du chapeau, recalculé une fois par jour dans
  `avatars/heads/`), sinon celle de **Steve** (texture officielle par défaut).
  On peut envoyer sa propre image : recadrée en carré, **réencodée en webp
  256 px côté serveur** (le fichier envoyé n'est jamais servi), 8 Mo max.
  Dossier `avatars/` hors git, propre à chaque site. Route `avatar?id=&v=`.
  Les comptes d'`ADMINS` (Yasuro, par id) ont un bouton « Remove picture »
  sur le profil des autres.
- **Pseudo** : changeable sur `account` ; bouton « Use my Minecraft name » si
  lié. Unique **sans tenir compte de la casse** (avant, « yasuro » pouvait
  s'inscrire à côté de « Yasuro »), jamais le `mc_name` vérifié d'un autre.
  Conséquence : **`REVIEWERS`, `PUBLISHER`, `ADMINS` sont des ids**, sinon
  quelqu'un pourrait prendre le nom libéré par Yasuro et ses droits.
- **Mot de passe** : changement avec l'ancien, sauf si la session vient de
  « Log in with Wynncraft » (`session['wynn']`) : c'est la récupération d'un
  compte lié. 8 à 64 caractères pour tout nouveau mot de passe.
  `session['stamp']` (empreinte du hash) : changer de mot de passe
  **déconnecte les autres navigateurs**.
- **Récupération** (pas d'e-mail, choix de Yasuro) : compte lié → Wynncraft ;
  sinon un **code de secours** `XXXX-XXXX-XXXX` fait sur `account`, montré
  une seule fois, seul son hash bcrypt est gardé, valable une fois
  (`recover`).
- **Classement** : le pseudo ouvre le profil du site (`player?id=`), la
  coche verte ouvre la page wynncraft.com. Les lignes sont identifiées par id.
  Chaque pseudo a sa photo devant lui (demande de Yasuro : « on voit pas les
  pfp dans le leaderboard ») ; `api/updaterank` envoie `pic` et `head`.
  Niveau, photo et pseudo sont dans un bloc flex (`.board-who`) : sur
  téléphone, ils se mettaient chacun sur leur ligne.
- **Sécurité, passée en revue le même jour** : cookie `SameSite=Lax` +
  `Secure` (avant : aucune protection CSRF, un site tiers pouvait poster au
  nom d'un joueur, y compris le Push de `/review`) ; `X-Frame-Options: DENY`
  et `nosniff` ; 10 essais ratés par compte et par adresse en 15 min (30 par
  compte toutes adresses), sur la connexion, le code et l'ancien mot de passe
  (mémoire du worker : un `HUP` remet à zéro). Laissés tels quels : CORS
  ouvert de l'origine (sans cookies, donc sans danger), `logout` en GET,
  message libre d'`apology?message=` (échappé, mais permet d'afficher un
  texte trompeur).

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
  **Défaut connu, laissé tel quel à la demande de Yasuro** (2026-10-18 : il
  refera les modes un par un) : ne pas deviner compte 0 point, donc ne coûte
  que l'écart au meilleur. Si l'autre a mal joué, c'est presque gratuit
  (ZDVNC4 et 75S9DP, manche 2 : **1 PV** perdu sans guess, l'autre avait 1
  point). Correctif testé puis retiré : sans guess (pas de ligne, ou `x`
  NULL), `5000 × multiplicateur`, quoi que fassent les autres ; aucun
  vainqueur de partie finie ne changeait. Battle Royale : sans guess = le
  pire de la manche = une vie, comme un mauvais guess (Yasuro : à garder).
- **Battle Royale** : 3 vies ; le pire de la manche perd une vie (égalité = rien) ;
  un bullseye (≥ 4 950 pts) ne perd **jamais** de vie et en rend une (règle
  ajoutée après une vraie partie : 4 976 contre 4 979 coûtait une vie).
- Duel/BR : joueurs présents au lancement = `seat=1` ; éliminés et retardataires
  regardent. Au moins 2 joueurs. Jusqu'à 25 manches. **PV et vies ne sont
  stockés nulle part** : `standings()` rejoue les guess à chaque fois.
- Seules les parties Classic (solo et salon) vont au classement ; les comptes
  invités jamais.

## Survival, refonte (2026-10-18)

Retours des joueurs : « far too lenient », « 500 blocks is huge, 100 max,
honestly 50 ». Classic (solo et salons) ne change pas : ce sont les modes
par défaut. Survival n'existe qu'en solo. Règles validées par Yasuro :

- **Cœurs** (comptés en demi-cœurs) : Normal 10, Hard 5, Hardcore 1.
- **Zone qui rétrécit**, calibrée par simulation sur 1 029 vrais guess
  (photos neuves, guess jetés > 2 000 blocs écartés) : pas de dégât sous
  `150·(1/3)^((n−1)/19)` blocs (150 → 50 à la manche 20, plancher 25),
  dégâts max au-delà de `2000·0,4^((n−1)/19)` (2 000 → 800, plancher 500),
  entre les deux `1 + ⌊19·x^1,5⌋` demi-cœurs (x = position dans la bande),
  plafonnés à 5 cœurs en manche 1 → 10 en manche 20 (un seul mauvais guess
  ne tue pas au début). Résultat simulé, bons joueurs : médiane 15 en
  Normal (1 sur 4 atteint 20), 10 en Hard, 3 en Hardcore (20 : 0,3 %).
  **Durcie le 2026-10-18** (joueurs : « within 5 blocks », 21 % des vrais
  guess tombent à moins de 5 blocs ; Yasuro : « just a tad bit harder ») :
  sans dégât sous 110 → 35 blocs à la manche 20, plancher 15 ; dégâts max
  au-delà de 1 700 → 650, plancher 400. Simulé sur 4 255 guess (salons +
  vraies parties Survival) : Normal, manche 20 atteinte 15 % → 7 % ; Hard
  3 % → 1 %.
- **Quasi-parfait** (≤ 10 blocs) deux fois de suite : +½ cœur, puis le
  compteur repart de zéro.
- **Chrono** 60 / 40 / 30 s (Swiftness 20 s). Les 3 dernières secondes, le
  sifflement du creeper ; à zéro, l'épingle posée part toute seule, sinon
  le creeper explose : dégâts max de la manche.
- **Potions** (`POTIONS`) : aucune avant la manche 4, puis 1 manche sur 5 /
  4 / 3 selon la difficulté, jamais deux de suite, Regeneration plus rare.
  Swiftness (20 s, zone ×1,5), Mining Fatigue (pas de zoom), Wither (−½
  cœur toutes les 5 s jusqu'au guess), Regeneration (+2 cœurs si dans la
  zone), Nausea (la vue tourne seule et l'épingle tombe à côté), Darkness
  (image 10 s puis noir).
  Blindness (« Thick fog ») : la même place photographiée dans le brouillard
  (`locations.fog_url`, tournée brouillard du mod 1.8.0). Tirée seulement
  s'il reste un lieu qui a sa photo brouillard (`fog_left`), et la manche
  se joue alors sur un tel lieu ; jamais d'imitation (si le seul lieu
  brouillard est déjà vu, la manche part sans potion). Elle vient donc
  d'elle-même, au fur et à mesure des photos.
  **Les 740 photos brouillard faites le 2026-10-18** (vérifié : toutes
  rattachées, tuiles présentes, mêmes places que les photos normales). À
  distance 6 (~100 blocs), le lointain et les nuages disparaissent mais le
  proche reste net : Blindness forte sur les paysages ouverts, presque
  nulle dans les rues et lieux fermés. Proposé à Yasuro : refaire la
  tournée à distance 2 si on la veut forte partout.
- **Révélation** : cercles autour de la réponse, vert (sans dégât), jaune
  (dégâts), rouge (au-delà, mort avec les cœurs qui restaient). Dégâts
  écrits « −6.5 » + un cœur (demande de Yasuro, pas « 6½ hearts »).
- **Potions, présentation** (choix de Yasuro) : la potion est tirée **au
  guess** (`potion()`, gardée dans `survival_runs.next_effect`) et appliquée
  à la manche suivante. Au résultat, le bouton attend : son de lancer
  (`random/bow`), GIF `static/potion-throw.gif`, verre brisé
  (`random/glass1-3`), puis la carte de la potion et le bouton. **Le GIF
  est celui de Yasuro** (97 images, 3,07 s : quelqu'un arrive en courant,
  lance la bouteille qui éclate en rouge sur l'écran), versionné par
  `asset()` (`data-throw`), chargé une fois puis rejoué par une adresse
  `blob:` neuve (sinon 1,6 Mo par potion). Sons calés image par image et
  comptés depuis l'affichage réel (`load`) : lancer à 1 690 ms (image 51),
  verre à 1 950 ms (image 60), carte à 3 070 ms ; vérifié à ±3 ms. Pour un
  nouveau GIF : refaire la planche des images et régler `THROW_MS`,
  `THROWN_MS`, `SPLASH_MS` dans `survival.js`. **Piège** : `tools/potions.py`
  dessinait le GIF provisoire, il ne le fait plus (il aurait écrasé le
  sien). Sans image, la carte s'affiche tout de suite (jamais de partie
  bloquée sans bouton). Pour envoyer un fichier animé : `scp` sur le
  serveur, pas le chat (il l'aplatit en une image transparente). Les
  flacons (`static/potions.png`, couleurs des effets de Minecraft) sont à
  nous. Un rechargement montre la carte sans le lancer. Le lancer prend tout
  l'écran (demande de Yasuro), par-dessus le résultat.
- Effets côté page : Mining Fatigue (zoom de la carte bloqué), Nausea (la
  vue tourne seule, voir plus bas), Darkness (noir après 10 s, Yasuro : 5
  était trop court ; même après un rechargement), Wither (les cœurs tombent à l'écran toutes les 5 s, le
  serveur compte). Le flacon de la manche est dans le menu (sur téléphone,
  sans son nom, et les points s'effacent pendant la manche : le menu
  débordait).
- Cœurs espacés d'un pixel du dessin (demande de Yasuro).
- **Panneau de test** (demande de Yasuro : « give me a way to test
  everything easly ») : `beta.wynndle.com/survival?difficulty=normal&test=1`
  (ou hard, hardcore), connecté avec un compte de `REVIEWERS`, et seulement
  là où `capture_key` existe (la bêta). Une partie de test
  (`survival_runs.test`) n'entre jamais au classement ni dans l'XP. Le
  panneau : boire une potion (pendant une manche : tout de suite, la
  manche repart sous elle ; sur un résultat : pour la manche suivante),
  régler les cœurs, sauter à une manche (sentir la zone de la manche 20),
  lancer le creeper dans 4 s. Replié sur téléphone.
- **Nausea refaite** (2026-10-18) : la première version (panorama qui
  tangue en CSS) était « super easy » et faisait ramer (un panorama 3D animé
  en CSS se recalcule à chaque image). Après essai de quatre remplaçantes
  au panneau de test, Yasuro a choisi **Shaky Hands + Dizziness** réunies
  sous le nom Nausea : la vue tourne seule (rotation de Pannellum, `NAUSEA_SPIN`
  = -40 °/s, un tour en 9 s ; -9 était « way » trop lent,
  impossible à tenir, aucun coût en plus) et le serveur décale l'épingle de
  20 à 60 blocs (`SHAKE`) ; la révélation montre le point visé (rond blanc)
  et le point tombé. Écartées : Tunnel Vision (champ fixé à 35°), Mirror
  (image retournée).
- **Lait** (2026-10-18, demande de Yasuro : « 2 milk buckets for free …
  with a nice moment to use them (after potion effect) ») : 2 seaux par
  partie **si l'option Milk est cochée** (décochée par défaut, voir
  « Survival à plusieurs » : classement à part) (`MILK`,
  `survival_runs.milk`), jamais achetables. Bouton « Drink
  Milk · N left » sur la carte de la potion lancée (après le GIF) ; il
  annule la potion de la manche suivante (`api/survival/milk`, gardée dans
  `survival_guesses.milked`). Bu comme dans Minecraft (recherche : 32 ticks
  = 1,6 s, `entity.generic.drink` toutes les 4 ticks après les 7
  premières, pas de rot à la fin) : le seau se lève et penche, 7 gorgées
  (`random/drink`, son `drink`), puis la carte devient « Milk! No more X. »
  avec le seau vide (`static/buckets.png`, dessiné par `tools/potions.py`).
  « Next » n'attend que la réponse du serveur, pas la gorgée. Une manche
  annulée compte comme une manche sans potion (la suivante peut en avoir
  une). Panneau de test : « Milk: 2 » remplit. **Mise en prod : copier
  aussi `static/sounds/drink1.mp3`** (ou relancer `tools/sounds.py`).
- **Score** = lieux survécus, départage = total des points (formule
  Classic). Un classement par difficulté, plus aucune option (toutes les
  provinces, vue libre), anciens scores Survival effacés.
- **Cœurs dessinés** d'après une capture de l'ancien pack Wynncraft fournie
  par Yasuro (9×9 façon Minecraft) : plein, demi, vide, Hardcore.
- **Anti-triche complète** demandée : la partie vit sur le serveur
  (section « Survival » d'`app.py`, son en-tête liste les parades et les
  limites). Tables `survival_runs` (une partie, `phase` guess / result /
  over) et `survival_guesses` (chaque guess, temps compris, pour vérifier).
  Les tuiles passent par `survival/tile/<jeton>/`, un jeton neuf par
  manche, mort dès le guess (`Cache-Control: private` : **piège payé**,
  Cloudflare gardait la tuile et le jeton mort répondait encore). La
  migration efface les anciens scores Survival une fois, et `api/score`
  refuse désormais tout score Survival envoyé par le navigateur (on
  pouvait poster « 500 »).
- **Anti-triche étendue au Classic** (2026-10-18, accord de Yasuro : « fix
  classic for solo and multi so no cheater ») :
  - le **Classic solo se joue sur le serveur** (section « Solo » d'`app.py`,
    tables `solo_games` / `solo_guesses`, `api/solo/...`), même principe que
    le Survival ; règles et écrans inchangés pour le joueur (le dernier
    tour a son écran de score, puis « See Results »). Recharger reprend la
    manche ; une partie finie va au classement de ses réglages (provinces
    écrites `str(liste)` dans l'ordre de `PROVINCES`, comme le filtre) ou,
    sans compte, attend une connexion (`session['pending']`) ;
  - **`api/locations` (tous les lieux avec coordonnées et dossiers) et
    `api/score` (un score dicté par le navigateur) n'existent plus** ;
  - **aucune page ne voit plus un vrai dossier de tuiles** : salons et solo
    passent par `play/tile/<jeton>/` (table `tiles`, un jeton par manche de
    salon, gardé pour les rejeux, un par manche de solo, effacé au guess).
    Seuls `/review` (réservé) et l'accueil (`static/demo`) montrent des
    adresses réelles ;
  - limite qui reste : un script qui reconnaîtrait les images elles-mêmes
    (comparaison de tuiles) ; le chrono démarre côté serveur, chargement de
    l'image compris (avant, le Classic attendait le chargement).
- Page `survival` (`survival.html`, `survival.js`) : menu solo → Survival →
  difficulté (les autres réglages se cachent), `/game?mode=survival`
  redirige. Recharger reprend la même manche et son chrono ; une partie en
  cours d'une autre difficulté est terminée par la nouvelle. Une partie
  jouée sans compte passe au compte à la connexion (`adopt`). Score
  inscrit dès le premier lieu et mis à jour à chaque manche (une partie
  abandonnée garde le sien).
- Classement : onglet Survival = trois tableaux (Normal, Hard, Hardcore),
  colonnes Locations / Points / Date, départage aux points. Profil :
  « N locations » et la difficulté.
- Tests (scratchpad, à refaire) : moteur par le client de test Flask avec
  une horloge déplacée à la main (47 vérifications, dont chaque technique
  de triche) ; page par Playwright (menu, cœurs, cercles, creeper, mort,
  reprise), classement (ordre, une seule partie par joueur).

## Survival à plusieurs (2026-10-18, bêta)

Étapes validées par Yasuro : 1. lait en solo ; 2. moteur (section « Survival
with friends » d'`app.py`) ; 3. boutique « Potion Merchant » et page du
salon (section « survival » de `room.js`) — **faites** ; 4. vraie partie sur
la bêta, puis réglage des prix. Battle Royale ne se crée plus (`MODES`) ;
ses parties passées restent rejouées pour les profils.

Décisions de Yasuro, après un plan complet (« let's fully plan this idea ») :

- **Remplace Battle Royale** dans « Create a Room » (Classic · Duel ·
  Survival). Les 24 salons Battle Royale passés gardent victoires, séries et
  XP : `progress()` les rejoue par `standings()`, donc la règle Battle Royale
  y reste, en lecture seule.
- Règles du Survival solo, en même temps pour tous : même lieu, difficulté
  choisie par l'hôte (cœurs, zone, chrono, creeper), quasi-parfait ×2 = +½
  cœur. À 0 cœur, on regarde. **La partie s'arrête dès qu'il ne reste qu'un
  joueur** (Yasuro : pour monter au classement, jouer en solo ou mieux
  jouer) ; morts dans la même manche : le plus de points gagne.
- **Classement : le même que le Survival solo** (lieux survécus, par
  difficulté), « probablement un peu plus dur, même catégorie ».
- **Émeraudes** (monnaie de Wynncraft), gagnées **à la distance**, pas aux
  points : les points des vrais guess de salon sont tassés près de 5 000
  (4 750 guess : médiane 4 929, 3 sur 4 au-dessus de 4 477). Proposé :
  ≤ 10 blocs 10, zone verte 6, jaune 2, rouge ou rien 0 — à calibrer par
  simulation (un joueur correct s'offre une petite potion par manche, une
  chère toutes les 3).
- **Potions au hasard gardées** (taux de la difficulté, tirage par joueur),
  et **tout s'empile** avec celles des joueurs : aucune limite, ni d'achats
  ni de cibles (« pure chaos »). **Deux fois la même = niveau supérieur**,
  façon Minecraft (Wither II : ½ cœur toutes les 2,5 s ; Darkness II : noir
  après 5 s ; Nausea II : tourne plus vite, épingle plus loin ; Swiftness II :
  15 s ; Blindness et Mining Fatigue : pas plus fort).
- **Morts** : regardent, et peuvent dépenser leurs dernières émeraudes.
- **Lait** : en boutique, 2 achats par partie au plus, puis rupture ; il
  annule tout ce qui vous touche pour la manche.
- **Entre deux manches, dans l'ordre** (jamais pendant une manche) :
  1. révélation ; les potions au hasard sont lancées ;
  2. boutique : on achète et on choisit ses cibles ;
  3. « Ready » de tous, ou 20 s ;
  4. les potions achetées sont lancées, un toast pour tout le monde
     (« X → Darkness → Y ») ;
  5. 5 s avant la manche : l'image charge sans se montrer, chacun voit ses
     effets et peut boire du lait.
- Boutique « Potion Merchant » dans la DA (cases d'inventaire, infobulle
  d'objet Minecraft/Wynncraft, sons de villageois) : **recherche d'abord**
  (ce qui fait la magie de Wynncraft, ce qui fait humain, les sons).
- **Survival solo : 2 laits offerts par partie** (jamais achetables, pas de
  boutique), à boire au bon moment : sur la carte de la potion lancée —
  **fait** (voir « Lait » dans la section Survival).

**Le moteur (étape 2)**, ce que le code ne dit pas d'un coup d'œil :

- **Calibrage des émeraudes** (4 611 vrais guess de 94 joueurs, salons du vrai
  site + parties Survival de la bêta) : par manche, ~9 pour le dixième le
  plus fort, ~5,5 pour le joueur médian, ~4 pour le quart le plus faible,
  presque constant de la manche 1 à 20 (la zone rétrécit, mais les gains
  suivent). Prix d'abord 5 / 10 / 15 (une potion par manche) ; après la
  première vraie partie (Yasuro et Ragus, 2026-10-18 : « right now only one
  is kinda boring ») : **au plus 3 achats par joueur et par boutique**
  (`SHOP_MAX`, « so someone don't buy all the effects for the other ») et
  des prix pour en acheter deux ou trois : Mining Fatigue, Swiftness **2** ;
  Wither, Nausea, Blindness **3** ; lait **4** ; Darkness **5** ;
  Regeneration **6**. Qui a fait ses 3 achats est prêt d'office.
- **Lait : une option, décochée par défaut** (Yasuro : distinguer les parties
  avec lait des autres), en solo (2 seaux offerts) comme à plusieurs (vendu
  en boutique, 2 par joueur). Choisie avec la difficulté (`difficulty.html`),
  gardée par la partie (`survival_runs.milk_on`, `rooms.milk`) et par le
  score (`scores.milk`) : **les parties avec lait ont leur propre classement**
  (filtre « Milk : Off / On » du Survival), le profil écrit « · Milk ». Les
  scores d'avant l'option : comptent avec lait seulement les parties où un
  seau a été bu (avoir des seaux sans les boire n'aidait pas).
- **Choix faits en codant, à confirmer avec Yasuro si besoin** :
  - **pas de dernier appel** : chacun a tout son chrono, comme en solo. Un
    dernier appel de 15 s a été ajouté puis **retiré le même jour** : Yasuro
    avait mal compris ma question (« I misunderstood … we should keep that
    out ! »). Qui n'a pas deviné à la fermeture reçoit une ligne sans
    épingle (le creeper) avec le temps qu'il a eu, pour Wither ;
  - la manche 1 a aussi ses 5 s de chargement ;
  - les potions **au hasard sont publiques** dès la révélation (lancées à
    l'étape 1) ; les **achats restent secrets** jusqu'à la fermeture de la
    boutique, puis tout le monde voit qui a lancé quoi sur qui ;
  - les émeraudes de chacun ne sont visibles que de lui ;
  - Regeneration et le lait s'achètent pour soi, ne se lancent pas, et ne
    déclenchent pas la phase de lancer (pas de toast) ;
  - la boutique se ferme dès que tous les présents sont prêts **ou ne
    peuvent plus rien payer** (pas de 20 s d'attente pour rien) ; un joueur
    prêt n'achète plus ;
  - le lait se boit pendant le lancer ou les 5 s (jusqu'à 1 s après le
    départ), seulement si quelque chose vous touche ; il annule tout, même
    Regeneration ;
  - l'hôte peut écourter la révélation (vers la boutique), pas la boutique ;
  - un salon Survival ne prend que des lieux qui ont leur photo brouillard
    (s'il y en a au moins 100 : sinon tous, et Blindness n'est ni tirée ni
    vendue là où la photo manque) ;
  - 100 lieux par salon (`SURVIVAL_ROUNDS`) : à 100 manches avec plusieurs
    vivants, le plus de cœurs gagne, puis les points ;
  - un « Play Again » de Battle Royale repart en Survival normal.
- **Niveaux des potions** : Wither k = ½ cœur toutes les 5/k s ; Swiftness
  20, 15, 10 s (`SWIFT_STEP`, `SWIFT_MIN`), zone ×1,5 ; Nausea k = épingle
  k fois plus loin (et la page tournera k fois plus vite) ; Regeneration k
  = 2k cœurs ; Darkness k = noir après 10/k s (côté page).
- **API** pour l'étape 3 : `api/room/<code>` renvoie `phase` (waiting,
  prep, throw, guess, reveal, shop, finished), `phase_left`, `starts_in`,
  `time`/`time_left` (le chrono **du joueur**), `url` (brouillard sous
  Blindness), `throws` (achats lancés), `me` (émeraudes, lait en main,
  laits encore achetables, gain de la manche), `wares` (ce que **ce**
  joueur peut acheter, avec les prix), et par joueur `left` (demi-cœurs),
  `out`, `delta`, `survived`, `effects` ({potion: niveau}), `milked`,
  `ready`, `result` (guess, visée Nausea, dégâts, Wither, soin, zone).
  Actions : `buy` (item, target, round), `ready` (round), `milk` (round).
- Classement : une partie finie entre au classement Survival de sa
  difficulté (`scores.room` = code, donc pas deux fois au profil), lieux
  survécus = manches traversées vivant (le gagnant : toutes) ; 0 lieu ou
  invité : rien. XP comme les autres salons (points/100 + victoire).
- **Interface (étape 3, 2026-10-18)**, d'après la recherche demandée par
  Yasuro (« research what makes wynncraft's magic … don't forget sounds ») :
  - **Wynncraft 2.1** habille ses menus en bois et papier (des packs de
    joueurs le trouvent même « trop poli ») : la boutique reprend nos
    matériaux, pas le gris de Minecraft. Ses marchands sont des PNJ au nom
    magenta qui ouvrent un écran d'échange ; sa police remplace `²` `½` `¼`
    par l'émeraude, le bloc, l'émeraude liquide ; ses objets marquent une
    condition remplie `✔` (vert) ou non `✖` (rouge) : repris pour le prix.
  - **Minecraft** : effet bon en bleu `#447FFF`, mauvais en rouge
    `#FF5555`, niveau en chiffres romains (« Wither II ») ; un échange
    épuisé barré d'une croix rouge ; une potion lancée s'appelle « Splash
    Potion of … » ; ses sons de lancer (`random/bow`) et de bris
    (`random/glass`) sont déjà nos `throw`/`splash`.
  - **Voix du marchand** : le *wandering trader* de Minecraft, le seul
    marchand qui boit lui-même potions et lait : `trader` (son « hmm » à
    l'ouverture), `sold` (oui, achat), `refused` (non : pas assez
    d'émeraudes, avec la bourse qui tremble) ; `pickup` (`random/pop`,
    ramasser un objet) quand la manche rapporte des émeraudes.
  - **Ergonomie d'une boutique de jeu** (doc Fortnite/Roblox, retours de
    joueurs) : prix toujours visible, ce qui est trop cher reste lisible
    (prix en rouge) au lieu d'être grisé, un refus se dit par un son et une
    secousse, un achat se récompense (la bouteille saute, le marchand dit
    oui).
  - Écrans : **couvercle** de pierre pendant le lancer et les 5 s (« Round
    3 · Starts in 4 s », les effets du joueur, « Drink Milk · N left ») ; le
    panneau du haut et le chat restent au-dessus. **Manche** : cœurs en bas
    à gauche comme en solo, potions du joueur sur le panneau, celles de
    chacun en petites bouteilles à côté des noms, creeper (sifflement à
    3 s, explosion sans épingle à 0). **Révélation** : la zone du joueur
    (vert/jaune/rouge), où visaient les Nausea, « −3.5 ♥ · +6 émeraude »,
    tableau Joueur / Manche (Safe, −3.5 ♥) / Cœurs, la potion au hasard
    lancée avec la révélation (GIF puis carte). **Boutique** (page encadrée,
    panneau « Potion Merchant ») : bourse, chrono, 8 cases d'inventaire
    creusées dans le papier (case choisie dorée), infobulle violette à la
    Minecraft (nom, effet coloré, texte, `✔ Price: 10` ou `✖`), « Throw it
    at: » (les vivants, leurs cœurs et potions connues) ou « Drink it /
    Buy it », ce que le joueur a acheté, Ready, qui est prêt. **Lancers** :
    un toast par lancer pour tous (« A → Wither ×2 → B »), le GIF pour qui
    est touché. **Fin** : le dernier debout, les autres « Out in round N ».
  - `static/js/potions.js` : noms, textes **par niveau** (Wither II toutes
    les 2,5 s…), bouteilles, cœurs, émeraude, creeper et GIF, partagés par
    `survival.js` (solo, refait dessus) et `room.js` (section « survival »).
    `templates/difficulty.html` : le choix de difficulté, partagé par le
    menu solo et le salon (son script ne montre « Rounds » qu'en Classic,
    sinon Duel le réaffichait). Émeraude dessinée par `tools/potions.py`.
  - **Panneau des joueurs** (retour de Yasuro : trop chargé) : sur
    ordinateur, les joueurs quittent le panneau de la manche pour un
    panneau à eux, pendu à droite, un par ligne, cœurs (PV, vies) alignés
    à droite ; plus de « … » pour qui n'a pas deviné, une coche pour qui a
    deviné ; sur téléphone ils restent dans le panneau de la manche
    (`roundPlayers()`, tous les modes de salon).
  - **Piège payé** : la page redessine la boutique à chaque interrogation
    (1 s) ; l'infobulle d'une potion survolée disparaissait au bout d'une
    seconde. Elle suit désormais la potion sous la souris (`shopHover`),
    sinon la potion choisie.
  - **Creeper** (« absent from the multiplayer game », 2026-10-18) : non
    reproduit. Le sifflement part à 3 s pour qui devine encore, l'explosion
    à 0 pour qui n'a pas d'épingle, comme en solo ; vérifié en navigateur
    (sans épingle, et épingle posée jusqu'au bout). Dans leurs parties,
    Yasuro devinait presque toujours tôt : pas de creeper pour lui.
    Question posée : l'entendre aussi après avoir deviné ?
  - Pièges de test payés : `wait_for_selector(state='hidden')` sur le
    couvercle répond tout de suite hors de l'écran de manche (son écran
    parent est caché) : attendre `s.phase == 'guess'` ; les boutons sont
    en capitales par le CSS (« SHOP (7) »).
- Tests (scratchpad, à refaire) : `t_multi.py`, 93 vérifications au client
  Flask avec une horloge à la main et des pages qui interrogent chaque
  seconde comme `room.js` (règles, phases, chaque triche essayée, fin à
  deux morts, Classic et Duel inchangés) ; Classic et Duel rejoués en
  navigateur (`t_room.py`). Piège de test : la manche se ferme à
  l'interrogation **suivante** le dernier guess, la révélation finit donc
  une seconde plus tard que le guess + 10 s.

## Niveaux, XP et séries de victoires

2026-10-17, demande de Yasuro : des niveaux pour les comptes, « genre barre
d'xp minecraft + lvl au milieu », ni trop durs ni trop faciles, sans fouillis ;
au classement des onglets Levels et Wins ; des séries de victoires en multi.

- **XP** (comptes seulement, jamais les invités) : 1 XP par 100 points
  (chaque manche de salon, chaque partie solo Classic) ; 45 XP par lieu trouvé
  en Survival (la partie ne garde que la série ; un lieu à moins de 500 blocs
  vaut au moins 3 915 points, ~4 500 en moyenne) ; +50 XP par victoire en
  salon (règle de `history()` : salon terminé, au moins 2 joueurs, 1er,
  égalité comprise).
- **Jamais stockée** : `progress()` la recalcule depuis `history()` et
  `room_guesses`, comme les PV et les vies. Les parties d'avant les niveaux
  comptent, et changer une règle recalcule tout le monde. Toute manche jouée
  en salon compte, même dans une partie abandonnée.
- **Courbe** : le niveau L demande 50·L·(L−1) XP au total, chaque niveau
  100 XP de plus que le précédent (niveau 2 à 100, 5 à 1 000, 10 à 4 500, 20 à
  19 000). Formule dans `level_of()` (app.py) et recopiée dans `levelOf()`
  (xp.js). Calibrée sur les vraies données : une manche vaut 3 500 points en
  moyenne (médiane 4 441), une partie de 5 manches ~175 XP, donc niveau 2 dès
  la première partie, 5 en ~6 parties, 10 en ~25, 20 en ~110. Le 2026-10-17 :
  Yasuro 8, 13tiak 5, Ragus 4, kemmi et Roguefort 3. Inspirée de Minecraft
  (coût par niveau qui croît linéairement), de GeoGuessr (XP selon le score)
  et du game design (petites victoires dès les premières minutes, paliers qui
  s'espacent sans mur exponentiel).
- **Où** : le niveau dans le carré du bouton Profile du menu, avec une fine
  barre en bas ; sur le profil, la grande barre (« N XP to level L+1 » et une
  ligne d'explication) ; en fin de partie solo (écran final) et de salon
  (résultats) : « +N XP », la barre se remplit, le niveau fait un « pop » et
  « Level N! » à chaque palier, puis le menu se met à jour. Joueur anonyme ou
  invité : une seule ligne « Log in / Make an account to earn XP ».
- **Sons** : l'orbe de Minecraft à hauteur aléatoire toutes les 100 ms
  pendant le remplissage (comme le jeu : 0,55 à 1,25), son « level up » à
  chaque niveau, plus fort tous les 5 niveaux. Voir « Sons » plus bas.
- **Séries de victoires** (salons) : `best`, le record, toujours affiché (plaque
  du profil, colonne du classement) ; `streak`, la série en cours, seulement à
  partir de 2 (flamme sur le profil, dans l'onglet Wins, en fin de salon gagné).
  Une série cassée n'est jamais affichée « 0 » : afficher la perte crée de
  l'anxiété, le record sert de trophée permanent (recherche sur les séries).
- **Classement** : Classic, Survival, Levels (niveau, XP, parties), Wins
  (victoires, meilleure série, parties en salon ; seulement ceux qui ont gagné
  au moins une fois ; départage : meilleure série, puis le moins de parties).
  Dans **tous** les onglets, devant chaque pseudo son niveau, et après lui sa
  série en cours (flamme + nombre, dès 1 victoire) : demande de Yasuro, qui a
  refusé l'onglet Streaks (ajouté puis retiré le 2026-10-17) et une colonne
  dédiée. Sur téléphone la dernière colonne est masquée : n'y mettre que du
  secondaire. Pas d'onglet « Games » : presque identique à Levels. Les filtres
  se masquent sur Levels et Wins.
- API : `api/score` renvoie `xp` et `gained` ; `GET api/room/<code>/xp` (salon
  terminé) renvoie `xp`, `gained`, `bonus`, `streak`, ou `guest`. `ladder()`
  calcule les deux onglets (~5 ms le 2026-10-17).
- **Limite connue** : les scores solo sont envoyés par le navigateur (comme
  pour le classement), donc un tricheur peut gonfler son XP solo. Les salons
  sont calculés par le serveur.

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
- **Outils de l'hôte** (2026-10-18, demande de Yasuro : « kick or grant
  player the head ») : dans la liste des joueurs du salon d'attente, sur
  chaque autre joueur, « Make host » (étoile creuse, seulement s'il est là)
  et « Kick » (deux clics : le premier arme un bouton rouge « Kick? » pendant
  3 s, pas de `confirm()`). Kick seulement avant le début ; le joueur est
  retiré et inscrit dans `room_bans` : sa page se recharge sur « The host
  removed you from this room », il ne peut pas revenir. Un invité peut
  revenir sous un autre pseudo (nouveau compte invité) : accepté, minimal.
  Pour ces outils, `api/room/<code>` envoie désormais l'`uid` des joueurs
  (déjà public par les liens du classement ; le chat ne l'envoie toujours
  pas).
- Scores calculés **côté serveur** (`guess_score`, même formule que `game.js`).
- **On devine un bloc** (2026-10-17, des joueurs n'arrivaient jamais à 5 000 :
  la formule ne le donne qu'à moins d'un demi-bloc, donc au hasard du clic).
  Les photos sont aux coordonnées du bloc du joueur (`getBlockX`) et la carte
  est à 1 px par bloc : `block.js` (`blockAt`, `blockSpot`, `blockCursor`)
  fait du clic le bloc visé (coordonnées entières envoyées, épingle au centre
  du bloc) et, à partir du zoom 2, encadre le bloc sous la souris. Vérifié :
  le cadre tombe pile sur un pixel de la carte. **Tolérance `PERFECT` = 2
  blocs** : à 2 blocs ou moins, 5 000 (dans `guess_score` et `points()` de
  game.js). Réponses et guess sont dessinés au centre des blocs.
- Couleur d'un joueur = son rang d'arrivée (`COLORS` dans `room.js`).
- Chat : `room_chat`, 200 caractères, 0,7 s entre deux messages, livré par le
  poll (`chat=<dernier id>`). Un seul widget déplacé selon l'écran : sous les
  joueurs (attente), en haut à gauche sur le panorama (replié par défaut sur
  téléphone, **sous la carte** sinon il cache « Guess! »), dans le panneau de
  droite en révélation (jamais sur la carte : il cachait la réponse), sous les
  résultats.
  **Piège payé (2026-10-18)** : un élément déplacé (ou replié) perd son
  défilement, le chat remontait tout en haut à chaque changement d'écran
  (« super annoying in a big lobby »). `chatStick`/`chatTop` retiennent où
  le joueur l'a laissé (en bas = suit les messages), `chatPlace()` le remet
  après chaque déplacement, dépliage ou message.
- Temps restant : boîte **statique sous le bandeau**, sans animation, rouge à
  10 s (Yasuro a refusé le gros chiffre au centre et les pulsations).
- Sons : voir « Sons » plus bas.
- `beforeunload` : confirmation pour quitter pendant une manche/révélation
  (salon) ou une partie solo ; pas pour les redirections du jeu lui-même.

## Sons (2026-10-17)

Demande de Yasuro : « refaire tous les sons », plein de petits sons
d'interaction en jeu, **de préférence ceux de Minecraft**, sans fouillis
sonore ; certains sons se coupaient.

- **Les sons de Minecraft, hors git** : `tools/sounds.py` les télécharge
  chez Mojang (index d'assets de la dernière version) et les convertit en mp3
  (tous les navigateurs les décodent, vérifié Chromium et Firefox) dans
  `static/sounds/`, **à lancer sur chaque site** (bêta fait ; prod à faire
  lors de la mise en prod). Ils appartiennent à Mojang : le dépôt public ne
  les porte pas. Risque signalé à Yasuro (un site de fan non commercial qui
  les sert reste exposé à une demande de retrait de Mojang) ; **il a choisi
  de les garder** le 2026-10-18 (« keep the minecraft sounds ! »).
- `static/js/sound.js` (`Sfx.play(nom, hauteur, volume)`), inclus par
  `game.html` et `room.html` avant `xp.js`. Fichiers chargés une fois, joués
  en entier (les anciens bips étaient des notes coupées à la main). Contre le
  fouillis : volume propre à chaque son (`LOUD`), même son ignoré à moins de
  80 ms, 6 sons par seconde au plus, rien quand l'onglet est caché, rien
  avant le premier clic (sinon des sons s'empilaient et partaient tous d'un
  coup). **Piège payé en test** : la limite comptait les sons « en cours »
  par `onended`, qui ne vient jamais si l'audio dort ; après 6 sons, plus un
  bruit. D'où un compte par seconde à l'horloge.
- Bouton volume unique (`#sound-button`, clé `wynnguessr-muted`) : dans le
  chat des salons, et dans la barre du solo.
- Moments (un seul son par événement) : épingle posée (dessin sur carte de la
  table de cartographie), guess (pop), un autre joueur devine (clic de bois),
  manche suivante (page de livre), compte à rebours 10 et 5 s (cloche de
  bloc musical) puis 3, 2, 1 (charleston, de plus en plus aigu), bullseye ≥
  4 950 (« ding » de la flèche qui touche), dégât en Duel/BR et Survival raté
  (coup reçu du joueur), éliminé (objet cassé), victoire (fanfare de défi
  accompli), défaite (« hmm » du villageois), quelqu'un entre dans le salon
  (porte), début de partie (cloche de village), XP (orbe, level up).
- **Deuxième passe (2026-10-18)**, Yasuro : « still kinda feels empty »,
  « met des sons un peu partout pour rendre le jeu plus vivant », **en jeu
  seulement pour l'instant** (les animations seront son étape suivante) :
  - clic des menus de Minecraft sur boutons, choix et onglets des pages de
    jeu (`sound.js`, sauf le bouton Guess qui a son pop) ;
  - **révélation en étapes** (salons) : les épingles tombent une à une, la
    plus loin d'abord, chacune sur une note plus haute (harpe de bloc
    musical, `SCALE`, `noteBlock()`), puis tes points défilent avec un tic
    toutes les 140 ms, puis un verdict : éliminé, bullseye, dégât, bon
    (≥ 4 000, `GOOD` : pling), raté (≤ 1 500 ou rien, `BAD` : basse). Même
    défilement et verdict en solo (`countUp`). Le poll réécrit la ligne
    chaque seconde ; le défilement écrit par-dessus jusqu'à la fin ;
  - **podium** (fin d'un salon en direct) : les 3 premiers apparaissent du
    3e au 1er (`.podium-wait`), une note chacun, puis fanfare ou « hmm »,
    puis l'XP (avant, les orbes couvraient tout) ;
  - **bulle du chat** de Minecraft quand un autre écrit, une toutes les 2 s
    au plus, rien pour les messages déjà là à l'ouverture.
  `SOUND_MAX` passé à 14 par seconde : à 6, les orbes d'XP (10 par
  seconde) étaient coupées.
  Volumes jamais validés à l'oreille : à régler sur les retours de Yasuro.

## Animations (2026-10-18)

Demande de Yasuro : tout plus vivant (pages, transitions, résultats), mais
**rien de « visiblement généré par IA »**, dans la DA Wynncraft, sans
encombrer ni lasser. Avant : une seule animation sur tout le site (`xp-pop`).

- **Ce que wynncraft.com anime vraiment** (leurs CSS téléchargées et
  `document.getAnimations()` sur l'accueil, 2026-10-18) : un ciel de 3
  couches de nuages qui dérivent en 60, 80 et 100 s (la vie vient du décor
  lent, pas de l'interface) ; transitions surtout `.3s ease` (105 sur 248) ;
  survol = agrandissement 1,02 à 1,1 et icône qui monte de 5 px ; courbes
  **qui dépassent puis reviennent** : `cubic-bezier(.57,.04,.32,1.47)` (0,5 s,
  icônes), `cubic-bezier(.44,.51,.53,1.94)` (0,15 s, survols « bouncy ») ;
  reflet blanc en diagonale qui traverse un bouton une fois (1 s,
  `wynn-shine-worker`) ; séparateurs qui se dessinent en largeur (0,5 s) ;
  icônes qui flottent de quelques px (5 s) ; bordures or/argent/bronze qui
  brillent lentement (10 s, rangs). Leur « pop-in » (fondu + 30 px vers le
  haut) existe aussi : c'est justement le tic à éviter chez nous.
- **Minecraft** : l'interface change d'un coup (aucun fondu entre écrans),
  les toasts glissent depuis le coin, l'écran titre tourne lentement son
  panorama : du mouvement lent en fond, une interface sèche.
- **Tics « IA » du mouvement** (rapport Sailop 2026, HN, hustletoai) :
  fondu + 20 px vers le haut à l'entrée dans l'écran, décalé de 0,1 s par
  élément, sur tout (défaut de Framer Motion / shadcn / v0) ; cartes qui se
  soulèvent de 4 px avec une ombre floue au survol ; lueurs au survol sur
  tout ; halo qui suit la souris ; barre de progression du défilement ;
  dégradés et reflets qui tournent en boucle ; même durée et même courbe
  partout ; transitions inégales d'un composant à l'autre. Diagnostic du
  rapport : « animation as performative competence ».
- **Ce qui fait humain** : chaque mouvement a une cause (une action du
  joueur, un événement du jeu), sinon rien ; un seul élément mène, le reste
  apparaît ; durées selon la taille et la distance (NN/g : ~100 ms pour un
  retour simple, 200-300 ms pour un grand changement, 400 ms au plus) ;
  sortie plus courte que l'entrée ; une physique propre au monde (bois,
  papier, clous, cordes) ; un peu d'irrégularité ; tout interruptible.
- **Ne pas lasser** : plus c'est fréquent, plus c'est court ou absent (NN/g,
  Emil Kowalski : pas d'animation sur ce qu'on fait des dizaines de fois) ;
  intensité par paliers (clic < écran < manche < partie) ; un clic passe
  toute séquence ; jamais de délai imposé au jeu ; `prefers-reduced-motion`
  coupe tout (aujourd'hui il ne coupe que les transitions, pas `xp-pop`).
  Piège technique : les salons se redessinent chaque seconde, une animation
  doit partir d'un **changement d'état** (comme les sons), pas du rendu.

**Fait (2026-10-18, les 8 choix de Yasuro, en bêta)** — section « Motion »
de `style.css` et `static/js/motion.js` (inclus par `game.html` et
`room.html`) :
- **Panneaux** (`.sign`, toutes les pages) : descend sur ses cordes et
  oscille jusqu'à l'arrêt (0,9 s, pivot 100 px au-dessus). Le titre des
  résultats se balance encore quand le gagnant s'affiche (`replay()`).
- **Accueil** : la rue de Wynn (tuiles `static/demo`) tourne derrière le
  titre, -2,5 °/s, partant de l'est (la photo fixe `hero.webp`, qui reste
  dessous jusqu'au chargement) ; champ calculé sur les proportions de
  l'écran (au plus 90° en hauteur, sinon déformé sur téléphone) ; arrêtée
  hors de vue (`IntersectionObserver`), pas créée en mouvement réduit.
- **Épingles** : la tienne tombe et rebondit (0,22 s, `pin-drop`), celles de
  la révélation tombent de plus haut (`pin-land`) et le pointillé se trace
  depuis la réponse (`drawLine`, 260 ms) ; idem en solo.
- **Révélation** : « Bullseye! » n'apparaît qu'une fois les points comptés,
  et frappe comme un tampon (`stamp`, salon et solo) ; à la même seconde,
  la case PV/vies de chaque touché tremble (`hit`) et un cœur regagné saute
  (`heal`). **Le tableau n'est réécrit que s'il change** (`revealRows`,
  `resultRows`) : sinon le poll coupait l'animation, ou la rejouait.
- **Podium** : chaque place glisse comme une planche et bute (`plank-in`),
  puis le reflet traverse une fois la ligne du gagnant (`shine()`, après la
  fin de la planche : sa position est mesurée).
- **Reflet** des gros boutons (`.btn.big`, Guess) au survol : sous le texte
  (`z-index: -1` dans le bouton).
- **Barre d'XP du profil** : se remplit en arrivant, puis le niveau saute.
- **Toasts** (`toast()`) : « X joined » (regroupés : « X and 2 more
  joined »), « X is now the host » / « You are now the host » (son
  `ui/toast/in`), « Level N! » ; papier, carré d'encre, glissent du coin.
- Les épingles bougent par la propriété CSS `translate`, pas `transform` :
  Leaflet place ses marqueurs avec `transform`.
- `prefers-reduced-motion` coupe désormais aussi les `animation`.
- Vérifié (Chromium + Firefox, 1280 et 375 px, salons Duel/BR jusqu'à 25
  manches) par `animationstart` : chaque animation part une fois par
  événement, aucune rejouée par le poll, jamais plus large que l'écran.



**Tout doit respecter la DA, partout** (Yasuro y tient beaucoup).
**Refonte complète le 2026-10-17**, demande de Yasuro : l'interface faisait
« clunky and cheap », il la voulait « really like wynncraft's site » (site de
fan, sans rien voler).

- **Palette** relevée dans le thème « journey » de wynncraft.com
  (`cdn.wynncraft.com/nextgen/themes/journey/theme.css`) : variables en tête de
  `style.css` — sable `--sand` (une page), papier `--paper` (un panneau), bois
  `--wood`, encre `--ink`, vert `--green`, or `--gold`.
- **Polices** : Ubuntu (texte) et Architects Daughter (menu, panneaux
  suspendus, onglets, en-tête du chat), celles de wynncraft.com, libres.
- **Leur technique, pas leurs fichiers** : aplats coupés de facettes dures
  (`--facet`, `--facet-big` : blanc et noir translucides, valables sur toute
  couleur), cadres en anneaux de bois faits de `box-shadow` empilés
  (`--frame`, `--frame-thin`), titres de page sur panneau suspendu à deux
  cordes (`.sign` ; cordes de 600 px qui passent sous le menu, et `.page` isole
  son contexte d'empilement pour qu'elles passent devant le cadre). Aucun
  dégradé décoratif, aucune ombre floue. **Aucune image ni aucun SVG de
  wynncraft.com** : facettes, clous, pierres et textures sont dessinés pour
  nous, lisibles dans `style.css` (seul `#` y est échappé en `%23`).
- **Le décor est sombre, les panneaux restent clairs** (la règle « aucun
  panneau sombre » tient) : fond de pierre partout, comme sur wynncraft.com ;
  pages en sable, panneaux en papier.
- **Accueil** : photo de la rue de Wynn (`hero.webp`, face est du lieu « Look
  Around » en 2048 px, 150 Ko ; l'ancien fond PNG pesait 19,8 Mo, supprimé),
  rangée de pierres en bas, puis deux bandes sur terre sombre (titre vert,
  texte clair, image dans un cadre de bois) qui remplacent les trois cartes.
  `hero.webp` est appelé par le CSS, sans `?v=` : changer de nom pour en
  changer. `friends.webp` : vrai morceau de la carte Wynntils autour de Ragni
  (1,5 px par bloc) avec les épingles de `room.js` (réponse et trois joueurs),
  webp sans perte (le plus léger pour du pixel art).
- Menu : page courante en **or** (comme l'onglet choisi du classement) ;
  choix cochés en vert ; MAJUSCULES seulement sur les boutons, comme sur
  wynncraft.com.
- `<head>`, menu et pied de page partagés : `head.html`, `nav.html`,
  `footer.html` (`game.html` et `review.html` gardent leur propre barre).
  Bootstrap retiré : rien ne s'en servait.
- Radios et cases à cocher masquées **mais focalisables** (`.chips > input`) :
  les choix se font au clavier, ce que l'ancien `display: none` empêchait.
- **Tics des sites générés par IA, évités exprès** (recherche du 2026-10-17) :
  Inter/Roboto, dégradés violets, verre dépoli, rangées de trois cartes
  identiques, ombres grises floues partout, apparitions animées au défilement,
  petites étiquettes en majuscules au-dessus des titres, numéros 01/02/03,
  émojis en guise d'icônes. Ne pas les réintroduire.
- Yasuro a validé la refonte telle quelle (« just what I wanted »). Toute
  nouvelle page reprend ces composants : `.page` + `.sign`, `.panel` (titre
  `h2` sur la ligne à clou), `.btn` (`.wood`, `.red`, `.big`, `.wide`),
  `.chips`/`.chip`, `.field`, `.tabs`, `.leaderboard-table`.
- **Outils (`tools/`)** : `ornaments.py` et `textures.py` impriment les
  variables de dessin de `style.css` (facettes, clou, pierres, textures) ;
  pour retoucher un dessin, modifier le script et recoller sa sortie dans
  `:root`. `solo.py` et `room.py` (Playwright) jouent une partie solo de 3
  manches et un salon à deux invités `zz_` (`room.py <url> <préfixe>
  classic|duel|royale [largeur hauteur]`) et photographient chaque écran.
  `xpsolo.py` (un compte `zz_` vise juste en solo, puis photographie la barre
  d'XP qui se remplit ; la page ne connaît plus la réponse : 6e argument =
  chemin de la base, pour viser) et `xproom.py` (deux comptes `zz_`, deux salons gagnés
  d'affilée : bonus de victoire et série ; 3e argument = chemin de la base,
  pour lire les réponses).
- **Méthode qui a marché** : développer sur une copie isolée dans le
  scratchpad (templates + statiques copiés, grosses images en liens, base
  copiée par `sqlite3.backup`, gunicorn sur un port libre), jamais en direct dans
  `~/Wynnguessr-beta` : ses fichiers statiques sont servis tout de suite et
  kemmi peut être en train de trier. Vérifier sous Chromium **et Firefox**
  (navigateur de Yasuro), ordinateur et 375 px. Puis copier, recharger la
  bêta, effacer les copies de base du scratchpad. Les réglages de test passent
  par un petit `dev_app.py` à côté (il importe `app`, fait
  `is_reviewer.__defaults__ = ((<id du compte de test>,),)` (des ids depuis que
  les pseudos se changent), désactive `SESSION_COOKIE_SECURE` (copie en http)
  et active le rechargement des templates) : `app.py` reste identique à celui de la bêta et se recopie tel
  quel. Une copie de la **vraie** base montre les niveaux réels des joueurs ;
  une session de test se signe avec la clé de la copie (cookie
  `wynnguessr_session`).
- Référence de leur style : leurs pages se photographient avec Playwright
  (site rendu en JS) ; les pages stats/classement sont derrière une
  vérification Cloudflare, ne pas la contourner.

- `mode` : choix **Solo / With Friends** d'abord (`?play=solo|friends`), puis
  réglages (`settings.html` + `modes.html`, partagés avec la salle d'attente).
- `profile` : barre d'XP, stats multijoueur (parties, victoires, meilleure
  série) + historique (2026-10-17 : tableau au style du classement, résultat
  sur une plaque facettée verte/rouge/bois ; Yasuro trouvait les anciennes
  bandes à bord coloré hors DA) façon
  Valorant (`history()` ; une partie de salon est dans `scores` avec `room`,
  pour ne pas la compter deux fois). Volontairement différent du classement.
- **Survival est le mode principal** (décision de Yasuro, 2026-10-18) : premier
  et coché par défaut dans « Play Solo » comme dans le classement ; Classic
  reste choisissable. Sous Difficulty, seule la difficulté cochée dit ce
  qu'elle fait (`.difficulty-rules`), pas les trois à la fois.
- `about` refaite (2026-10-18, demande de Yasuro : chiffres + cartes des
  modes « humainement compréhensibles ») : joueurs en ligne (panneau à
  part, carré vert d'un serveur allumé), puis Visitors, Player accounts,
  Games played, Guesses, Locations sur une bande de papier ; « Game Modes »
  en deux panneaux (On Your Own : Survival « main mode », Classic ; With
  Friends : Survival, Classic, Duel), chaque mode montré par ses propres
  objets dans une case comme celles du marchand (cœur, épingles, potion et
  émeraude, barre de vie), son but en vert ; le Discord avec ses membres et
  ses connectés (invitation publique `?with_counts=true`, relue toutes les
  10 min). **Visiteurs** : `visitors` (un identifiant au hasard dans la
  session, écrit une fois par minute au plus, robots exclus), compté **depuis
  le 2026-10-18** (rien n'existait avant : le journal d'accès ne remonte qu'au
  dernier redémarrage) ; en ligne = vu dans les 5 dernières minutes.
- Classement (2026-10-18, demande de Yasuro) : **sa propre place épinglée en
  haut** de chaque tableau (ligne verte, mêmes colonnes, trait épais), quelle
  qu'elle soit, ou « You are not on this board yet. » ; **50 lignes à la
  fois** (`BOARD_PAGE`) puis « Show 50 more ».
- `leaderboard` : onglets Survival/Classic (filtres, meilleure partie par
  joueur) et Levels/Wins (voir « Niveaux ») ; un pseudo lié Wynncraft = lien souligné vert + coche + icône.
- `about` (onglet About, 2026-10-18) : un seul panneau, le Discord du projet
  (`DISCORD` dans `app.py`). Le texte reprend les mots de Yasuro (« garder ma
  touche ») ; ne rien y ajouter sans lui demander.
- Pied de page hors jeu (`footer.html`) : Made by Ched3, Hosted & modified
  by Yasuro, Wynncraft, Fan-made, not official (séparés par l'espace, plus par
  des points médians).

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

## Mod de capture (`mod/`)

Mod Fabric client **Wynndle Panorama**, pour refaire les images (les 622 de
l'origine datent d'août 2024). Touche **Maj droite** (réglable, catégorie Divers ; Yasuro n'a pas de
touches F) :
appelle le panorama intégré de Minecraft (`grabPanoramixScreenshot` : 6 faces
rendues en 4096, monde seul, sans interface ni main ; enregistrées réduites ×4
d'origine ; `PanoramaDownscaleMixin` force ×1 → **4096** depuis la 1.6.0),
centre = **nord**, et écrit les faces dans `.minecraft/wynndle/<X>_<Z>.zip`
(`_2`… si le nom existe déjà). Jusqu'à la 1.5 il les assemblait en
équirectangulaire 8192×4096 (4096×2048 avant la 1.1, jugé trop flou). La province n'est pas dans le nom : à déduire
de la position à l'import.
**Envoi automatique** (1.2.0) : si `config/wynndle-panorama.json` (créé vide au
premier lancement, lu au démarrage du jeu) contient une `key`, chaque photo est
aussi envoyée à `POST <url>/api/capture?x=&z=` (en-tête `X-Wynndle-Key`, corps
JPEG). Le chat dit « sent », ou « saved, not sent (raison) » : la copie locale
reste toujours.
**Tournée** (1.4.0, touche **Ctrl droit**, solo seulement) : vers le point
`planned` le plus proche, `tp` en haut de la colonne, attente du chunk, `tp`
au sol (premier bloc qui arrête un joueur **et qui se voit** en partant du
haut — **piège payé** : Wynncraft coiffe des zones de barrières invisibles,
Yasuro atterrissait dessus dans le ciel —, feuilles exclues, eau comprise), tour complet sur soi (Yasuro : Distant Horizons ne
charge que ce qui est regardé), courte attente, photo, point suivant **sans
attendre l'envoi** (1.5.0 : assemblage, sauvegarde et envoi passent dans une
file à un seul fil, `WORKER`). Durées réglables dans
`config/wynndle-panorama.json` : `spinSeconds` et `waitSeconds`, **4 s et 3 s
par défaut** (1.5.1 ; la 1.5.0 était passée à 2 et 1, trop court pour DH
selon Yasuro).
**Piège payé (1.5.0)** : en raccourcissant les attentes, le sol était cherché
avant l'arrivée des blocs du chunk ; faute de sol, le mod laissait le joueur
en haut de la colonne, dans les plafonds de barrières de Wynncraft (« on
spawn en l'air, bloqué par des barrières »). Depuis la 1.5.1, pas de sol
trouvé = on attend encore (jusqu'à l'abandon à 15 s), jamais de repli en haut. Un point est
fait une fois par tournée : jamais chargé (15 s) il est sauté, et un envoi
raté le laisse bleu pour la tournée suivante.
La province d'un point est **déjà devinée** (règle Fruma, sinon lieu
d'origine le plus proche, `deleted` compris) : 100 % de bonnes réponses en
validation croisée sur les 622 lieux d'origine, et juste sur les 148
premiers points de Yasuro (vérifié sur la carte).
Téléchargement de la carte : Yasuro a choisi **Simple World Downloader**
(Modrinth, 1.21.11), pour voler en créatif et choisir l'heure, usage
personnel. Dans le monde solo, couper la « distant generation » de DH, sinon
il invente du terrain là où rien n'est téléchargé.
**Face avant incomplète** : sur les
premières tournées, la face nord (centre de l'image, rendue en premier)
n'avait ni paysage lointain Distant Horizons ni nuages. DH a une image de
retard après le changement de caméra : `PanoramaWarmupMixin` dessine chaque
face deux fois et garde la seconde. **Inefficace** (mixin retiré en 1.7.0),
comme « Disable Frustum Culling » de DH : sur une photo de Fruma (1.6.1), la
face nord n'avait **ni DH ni nuages** (vanilla), les 5 autres si. C'est la
**première face dessinée** par `grabPanoramixScreenshot` qui sort incomplète,
cause non trouvée. Contournement (1.7.0) : deux panoramas d'affilée, le
second démarré à l'est (yaw 270) ; sa face 3 (yaw 180, même caméra que la
face 0 du premier) remplace le nord. **Échec aussi.**
**Vraie cause, trouvée par diagnostic (2026-10-17)** : la caméra à **yaw
180,0 exactement**. Même endroit, même instant : à 180,0 le nord est vide,
à 180,5 et à 225 tout est complet (la face 3 du second panorama de la 1.7.0
tombait elle aussi pile à 180). Seulement en solo (pas vu sur Wynncraft),
même sans aucun mod d'optimisation. Depuis la 1.7.2 : `NORTH = 180.5f`, un
seul panorama ; le cube est tourné d'un demi-degré, invisible.
**Sans entités** (1.3.0, demande de Yasuro) : pendant la capture
(`WynndlePanorama.capturing`), `HideEntitiesMixin` cache toute entité vivante
(mobs, PNJ, joueurs, familiers) et les `TextDisplay` ; `HideNamesMixin` retire
les noms au-dessus des entités. Les supports d'armure restent (Wynncraft en
décore), seul leur nom part. Télécharger la carte (Chunky, world downloader) a
été écarté : Chunky génère un monde côté serveur et ne copie rien de
Wynncraft.

**Tournée brouillard** (1.8.0, touche **Alt droite**, réglable : « Wynndle
fog tour » dans Contrôles → Divers) : comme la tournée, mais sur les lieux
**gardés** qui n'ont pas encore leur photo brouillard (`GET
api/capture/fog`), sans le tour sur soi (rien de loin à charger). Elle
refuse de partir sans **distance de rendu 6** et si **Distant Horizons**
est chargé (choix de Yasuro : 6 chunks, DH retiré à la main). La photo
part avec `&fog=<id>` et rejoint le lieu (`fog_url`), sans tri ; copie
locale dans `.minecraft/wynndle/fog/`. Elle se pose comme la tournée (sol
le plus haut) : une photo prise à la main ailleurs qu'au sol ne sera pas
au même endroit en hauteur. Le Push emporte `fog_url` vers le vrai site
dès que celui-ci a la colonne (son `app.py` l'ajoute au démarrage), et
marche sans en attendant.

- Cible : pack Modrinth **Wynncraft Plus** (Fabric, MC 1.21.11), celui de Yasuro.
  Il contient Iris, Distant Horizons, Sodium : leur effet sur la capture n'a
  pas encore été vérifié en jeu.
- Compiler : `JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 ./gradlew build`
  → `build/libs/`. JDK 21 installé par apt le 2026-10-16 (il n'y avait que le
  JRE). **Loom 1.15.5 et pas 1.18** : la 1.18 exige Java 25 pour tourner.
- L'assemblage a été vérifié hors jeu (une ancienne image découpée en cube à
  la manière de Minecraft puis réassemblée : identique, sans couture).

## En suspens

- Survival de Yasuro absente du classement après correction : le test réel
  passe ; journal d'accès activé pour voir sa prochaine partie.
- Flash blanc entre pages : corrigé sans vérification visuelle.
- `www.wynndle.com` non configuré ; « Always Use HTTPS » à activer côté Cloudflare.

### Photo d'accueil (« Look Around »)

2026-10-17, choix de Yasuro : le lieu X -881 Z -1576 (Wynn). Ses tuiles
multires sont **copiées dans `static/demo/`, dans git** (niveaux 1 à 3 et
`fallback`, 5,5 Mo ; le niveau 4 pèserait 10 Mo de plus pour une petite
fenêtre) : `static/tiles` n'existe que sur la bêta et le lieu peut être
supprimé au tri. Pour en changer, remplacer le dossier entier par un **nouveau
nom** : Cloudflare garde 4 h les fichiers statiques, et des tuiles neuves sous
les mêmes noms se mélangeraient aux anciennes.

### Aperçu des liens partagés (Discord…)

- **Lien de salon** (2026-10-18, demande de Yasuro) : la carte dit le salon
  (« Room Y2JHUC · Survival (Hard, milk) ») et où il en est (« Yasuro is
  waiting in the lobby. Hop on! », « 3 players waiting… », « Game on: round
  4… », « This game is over. ») : `room_card()`. Le robot de Discord n'a pas
  de session : `/room` le renvoie vers `/guest?next=room?code=…`, c'est cette
  page qui porte la carte. **Instantané** : Discord garde la carte telle
  qu'au moment du partage, elle ne se met pas à jour.


2026-10-17, demande de Yasuro. Balises Open Graph dans `templates/share.html`,
incluse par `index`, `layout` et `game` (pas `review`). L'image
`static/banner.jpg` (1200×630) est tirée du même lieu que la photo d'accueil
(rue vers le château de Wynn, face est) avec le logo et le titre. Son adresse
doit être complète : le nom du site est celui de la requête quand il finit par
`wynndle.com` (la bêta montre donc sa propre image), sinon `wynndle.com`.
Couleur de la barre Discord = le vert du logo. Discord met l'aperçu en cache :
un lien déjà partagé peut garder l'ancien.

### Fruma et moteurs de recherche

- **Fruma ouverte le 2026-10-17** (70 lieux gardés, demande de Yasuro) :
  dans `PROVINCES`, cochée par défaut partout (solo, salons, filtre du
  classement). Choix de Yasuro, en connaissance de cause : le classement ne
  compare que les parties aux provinces identiques, donc les scores d'avant
  (sans Fruma) ne se voient plus qu'en décochant Fruma ; le classement par
  défaut repart de zéro. L'ordre des provinces doit rester le même partout
  (formulaire, `PROVINCES`, filtre) : la chaîne enregistrée doit être
  exactement celle du filtre. Le texte d'accueil dit « Over 700 spots ».
- Seul `wynndle.com` doit être indexé : `after_request` envoie
  `X-Robots-Tag: noindex` pour tout autre nom (bêta, ancienne adresse ts.net).
  cloudflared transmet bien le `Host` d'origine (vérifié). Search Console et
  les liens externes sont l'affaire de Yasuro.
- Texte d'accueil (2026-10-17, « sell it a bit more ») : d'abord trois cartes
  entre la bannière et Look Around (Yasuro avait refusé le texte entassé dans
  la boîte Look Around : « horrible placement »). Depuis la refonte du même
  jour, le même texte est réparti dans deux bandes, chacune avec son image :
  « Look Around » (**« Over 600 spots »**, 671 lieux `kept` ce jour-là, à côté
  de la photo à faire tourner) et « Play With Friends » (salons, et les modes
  réels : solo Classic, Survival ; salon Classic, Duel, Battle Royale). Le
  titre de la bannière est devenu « WynnGuessr » + « The GeoGuessr of
  Wynncraft » (ancien titre de la section des cartes) ; « Discover Wynncraft »
  a disparu. À corriger si le nombre de lieux ou les modes changent.

### Publication des lieux (bouton Push)

- Le vrai site ne fabrique plus de lieux : **ils viennent tous de la bêta**.
  Bouton « Push to wynndle.com » de `/review`, réservé à `PUBLISHER`
  (Yasuro ; kemmi trie mais ne publie pas). Il écrit dans
  `~/Wynnguessr/database.db` (`LIVE_DB`, voisin du dossier bêta) : tout y passe
  en `deleted`, puis les points verts de la bêta y entrent en `kept` sous le
  **même `location_id`** (la bêta est une copie de la base du vrai site, qui
  n'a jamais créé de lieu : pas de collision). Rien n'est effacé là-bas : les
  salons finis rejouent leurs lieux.
- Les photos ne sont pas copiées : `~/Wynnguessr/static/tiles` est **aussi un
  lien vers `/data/wynnguessr-tiles`**, posé à la main (hors git) lors de la
  mise en prod. Corollaire : **un lieu `kept` supprimé à la bêta ne doit
  jamais voir ses tuiles effacées** (seuls `new` et `planned`, jamais publiés,
  le sont) — sinon le vrai site perd la photo avant le prochain Push.
- Première publication le 2026-10-17 : 671 lieux. Sauvegarde de la base du vrai
  site juste avant : `/data/wynnguessr-live-before-push-2026-10-17.db`.

### Prochains chantiers (demandés le 2026-10-17, rien de commencé)

Liste de Yasuro d'après les parties et les retours des testeurs : réparer le
chat, un meilleur écran spectateur, refaire complètement le Survival, refaire
tous les sons, des modes plus fun et dynamiques. Yasuro prépare son propre
plan : **attendre ses choix avant de coder**. Mes propositions, en attente :

1. **Chat** — on ne sait pas encore ce qui gêne : demander les retours exacts.
   Défaut proposé : place fixe en partie (tiroir à droite, compteur de non
   lus), plus lisible, messages du jeu (« X a deviné », éliminé, rejoint),
   plein écran sur téléphone.
2. **Spectateur** (éliminé ou arrivé en retard) — aujourd'hui un bouton gris
   « Spectating ». Proposé : il voit la réponse dès le début de la manche, le
   panneau des joueurs en lice (PV/cœurs, qui a deviné), les épingles qui
   tombent à la révélation. À trancher : risque de souffler la réponse
   (chat des spectateurs réservé aux spectateurs pendant la manche, ou
   confiance).
3. **Survival** (aucune partie Survival en prod : on peut changer les règles
   sans rien casser) — proposé : « à cœurs » façon Minecraft, 10 cœurs, perte
   selon la distance, un 5 000 rend un cœur, chrono qui descend (60 s → 20 s),
   score = lieux survécus (points en départage). Barème à calculer sur les
   vraies distances, comme l'XP.
4. **Sons** — fait le 2026-10-17 (voir « Sons »), avec ceux de Minecraft,
   choix de Yasuro.
5. **Modes plus dynamiques** — à choisir, ne pas tout empiler : révélation
   animée (épingles une à une, scores qui défilent, « Perfect! »), bonus de
   rapidité en Classic, dernière manche ×2, coups de Duel en grand, zone qui
   se resserre en Battle Royale, podium en bois à la fin, réactions rapides.
   Mes préférées : révélation animée, podium, dernière manche ×2.

Ordre proposé : sons → chat → spectateur → modes → Survival. Méthode : copie
isolée, vraies parties à plusieurs, téléphone et Firefox, puis **bêta** pour
les testeurs avant la prod (changements trop gros pour aller direct).

### Mise en prod du 2026-10-18

Accord de Yasuro (« let's push it »). Tout le travail des 17-18 octobre :
profils, sons, salons (exclure/passer la main), animations, Survival refait
(mode principal), anti-triche Classic, page About. Fusion `--ff-only` de
`beta` dans `main`, `HUP`, sons copiés de la bêta (`static/sounds/`, hors
git). Sauvegarde de la base juste avant :
`/data/wynnguessr-live-before-survival-2026-10-18.db`. Les colonnes
(`fog_url`, `scores.difficulty/points`) se sont créées au démarrage.
**Les photos brouillard n'arrivent sur le vrai site qu'au prochain Push**
(`review_push` les copie) : avant, Blindness n'y tombe jamais.
Le même jour, quelqu'un a sondé une injection HTML par `game?rounds=` :
échappée par Jinja, et `rounds` est validé côté serveur (`SOLO_ROUNDS`).

### Mise en prod du Survival à plusieurs (2026-10-18, 15 h 24)

Accord de Yasuro (« yes you can push ! »). Lait en solo, Survival à
plusieurs (moteur, salon, Potion Merchant), lait en option, Battle Royale
retiré de la création. Sauvegarde juste avant :
`/data/wynnguessr-live-before-survival-multi-2026-10-18.db` ; 16 sons
copiés de la bêta (`drink`, `trader`, `sold`, `refused`, `pickup`) ;
fusion `--ff-only` puis `HUP` dans la même commande. Vérifié après : toutes
les colonnes et tables, **aucune partie solo en cours avec du lait** (34
en cours ; voir le piège ci-dessous), aucun score passé au classement avec
lait, plus aucun salon Battle Royale en attente, 244 comptes ; Chromium et
Firefox sans erreur sur le vrai site (menu, classement, une partie).

- **Piège évité**, trouvé en rejouant les migrations sur une copie de la
  base du vrai site : la colonne `survival_runs.milk` créée avec
  `DEFAULT 2` aurait donné deux seaux aux parties solo en cours et rangé
  leurs scores au classement avec lait. Défaut ramené à 0 (sans effet sur
  la bêta, où la colonne existait déjà). **Méthode à garder** : avant une
  mise en prod qui ajoute des colonnes, importer `app.py` sur une copie
  (`sqlite3.backup`) de la base du vrai site et regarder ce que les
  migrations ont fait.
- L'annonce Discord de la première mise en prod a été postée par Yasuro à
  12 h 21 ; pour celle-ci, un court journal des nouveautés.
- **Reste côté Yasuro** : appuyer sur Push (`/review` de la bêta) pour
  envoyer les 741 photos brouillard au vrai site (0 le 2026-10-18) : sans
  elles, Blindness n'y existe pas. Question ouverte : le creeper entendu
  aussi par qui a déjà deviné ?

### Où on en est (2026-10-17, fin de session)

- Flux : mod → tri sur la bêta → Push. **2026-10-17 au soir, mis en prod**
  (accord de Yasuro après une vérification complète) : refonte de la DA,
  niveaux/XP/séries, Fruma jouable (741 lieux gardés). Bêta et prod au même
  commit ; recharge à chaud par `HUP`. **Le classifieur de Claude Code refuse les mises en prod
  (fusion, redémarrage, écriture dans la base du vrai site) tant que Yasuro
  ne l'a pas dit explicitement dans le message même** (« push everything »
  a suffi) : demander, ne pas contourner.
- À faire côté Yasuro : Search Console (propriété « Domaine », TXT dans
  Cloudflare, demande d'indexation), liens externes (r/WynnCraft, forums,
  GitHub), photos de Fruma. Le 2026-10-17 le site n'apparaissait encore ni
  pour « wynndle » ni pour « wynnguessr » : normal, jamais exploré ; rien ne
  bloque (robots.txt de Cloudflare = commentaires seuls, Googlebot reçoit 200).
- Proposé sans réponse : préchargement de l'image suivante en solo (le salon
  l'a déjà).
