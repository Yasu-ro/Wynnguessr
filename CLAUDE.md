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
- **Battle Royale** : 3 vies ; le pire de la manche perd une vie (égalité = rien) ;
  un bullseye (≥ 4 950 pts) ne perd **jamais** de vie et en rend une (règle
  ajoutée après une vraie partie : 4 976 contre 4 979 coûtait une vie).
- Duel/BR : joueurs présents au lancement = `seat=1` ; éliminés et retardataires
  regardent. Au moins 2 joueurs. Jusqu'à 25 manches. **PV et vies ne sont
  stockés nulle part** : `standings()` rejoue les guess à chaque fois.
- Seules les parties Classic (solo et salon) vont au classement ; les comptes
  invités jamais.

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
- **Sons** (`xp.js`, WebAudio, aucun fichier) : un tintement d'orbe à hauteur
  aléatoire toutes les 100 ms pendant le remplissage (Minecraft : 10 orbes par
  seconde, hauteur 0,55 à 1,25), un carillon montant à chaque niveau, plus long
  tous les 5 niveaux (Minecraft joue sa fanfare tous les 5 niveaux). Coupés par
  le bouton son des salons (`wynnguessr-muted`). Volume jamais validé à
  l'oreille.
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
- Temps restant : boîte **statique sous le bandeau**, sans animation, rouge à
  10 s (Yasuro a refusé le gros chiffre au centre et les pulsations).
- Sons générés en WebAudio (aucun fichier) : un joueur valide ; 10, 5, 3, 2, 1 s.
  Bouton muet mémorisé (localStorage). Volume jamais validé à l'oreille.
- `beforeunload` : confirmation pour quitter pendant une manche/révélation
  (salon) ou une partie solo ; pas pour les redirections du jeu lui-même.

## Pages et direction artistique

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
  d'XP qui se remplit) et `xproom.py` (deux comptes `zz_`, deux salons gagnés
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
- `leaderboard` : onglets Classic/Survival (filtres, meilleure partie par
  joueur) et Levels/Wins (voir « Niveaux ») ; un pseudo lié Wynncraft = lien souligné vert + coche + icône.
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
4. **Sons** — remplacer les bips WebAudio par de vrais sons **CC0** (packs
   Kenney…, jamais ceux de Minecraft : propriété de Mojang), un bouton son
   unique partout (solo compris) avec volume. Moments : épingle, guess, autre
   joueur qui devine, compte à rebours, révélation, 5 000, perte de PV/cœur,
   élimination, victoire/défaite, orbes et niveau.
5. **Modes plus dynamiques** — à choisir, ne pas tout empiler : révélation
   animée (épingles une à une, scores qui défilent, « Perfect! »), bonus de
   rapidité en Classic, dernière manche ×2, coups de Duel en grand, zone qui
   se resserre en Battle Royale, podium en bois à la fin, réactions rapides.
   Mes préférées : révélation animée, podium, dernière manche ×2.

Ordre proposé : sons → chat → spectateur → modes → Survival. Méthode : copie
isolée, vraies parties à plusieurs, téléphone et Firefox, puis **bêta** pour
les testeurs avant la prod (changements trop gros pour aller direct).

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
