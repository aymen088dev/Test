# mapserver — webmap MipMap portée en Node.js

Serveur **Node.js zéro dépendance** qui reçoit les chunks scannés par un plugin
Endstone et sert dans le navigateur :

* l'**interface web de MipMap** (Leaflet), servie sur `/`, avec ses **tuiles
  texturées** rendues côté serveur (16 px/bloc, zoom 0–4) ;
* une **carte isométrique 3D** interactive (style BlueMap), rendue côté client
  (ancienne interface, `/index.html`) ;
* un **relief vu de dessus** (plongée) **rendu côté serveur** : le serveur
génère un PNG ombré à partir des chunks stockés, le navigateur ne fait que
l'afficher. La page **s'ouvre à plat en relief vu de dessus** (la vue « de
face ») ; la bascule `3D` / `Relief` de l'en-tête permet de revenir à
l'isométrique (`?view=iso` pour ouvrir directement en 3D).

Deux sources de données sont acceptées :

* **`plugin-mipmap/`** — **le plugin carte du dépôt** :
  [MipMap](https://github.com/MipaSenpai/MipMap) porté sur Endstone 0.11. Il
  envoie les chunks sur `POST /api/chunks-data` et les joueurs sur
  `POST /api/players-data`. Voir [Compatibilité MipMap](#compatibilité-mipmap).
* **Format interne** (`POST /api/chunk`, header `X-Api-Key`) — pour un plugin
  maison ou un import manuel : un chunk = `{v, dim, cx, cz, depth, palette,
  cells}`.

## Démarrage

```bash
node server.js
# ou
npm start
```

Aucune étape `npm install` : il n'y a **aucune dépendance**.

Sur **Pterodactyl (egg Node.js)** : mets le dossier `mapserver/` à la racine de
l'instance, commande de démarrage `node server.js`, variable `PORT` fixée par le
panel (ici `10015`).

## Serveur Minecraft et mapserver sur des machines différentes

Le plugin doit pouvoir faire un `POST` vers le mapserver : c'est la **seule**
contrainte. Trois cas :

| Situation | URL à mettre dans `config.toml` |
|---|---|
| Même instance Pterodactyl (mapserver lancé dans le même conteneur) | `http://127.0.0.1:10015/api/chunks-data` |
| Deux instances Pterodactyl **sur le même node** | `http://<IP_DU_NODE>:<PORT_ALLOCATION>/api/chunks-data` |
| Mapserver ailleurs (VPS, PC perso, Docker…) | `http://<IP_PUBLIQUE>:10015/api/chunks-data` |

⚠️ **`127.0.0.1` ne marche que dans le même conteneur.** Deux serveurs
Pterodactyl sont deux conteneurs séparés : depuis le serveur Minecraft,
`127.0.0.1` désigne *son propre* conteneur, pas le node. Il faut l'IP du node et
l'allocation du serveur mapserver (visible dans l'onglet *Network* du panel).

Côté mapserver :

* il écoute déjà `0.0.0.0` (`HOST` par défaut) — ne pas mettre `127.0.0.1` ;
* mets `PORT` sur la **valeur de l'allocation** Pterodactyl, sinon le panel ne
  route pas le trafic ;
* pas de dépendance : seul le port TCP du mapserver doit être ouvert.

Test depuis le serveur Minecraft (ou n'importe où) :

```bash
curl http://<IP_DU_MAPSERVER>:10015/api/status
```

Si ça répond, le plugin répondra aussi. Sinon c'est le réseau (IP, port,
firewall, allocation), pas le code.

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `PORT` | `10015` | port d'écoute (`MAP_PORT` accepté aussi) |
| `HOST` | `0.0.0.0` | adresse d'écoute |
| `MAP_API_KEY` | *(vide)* | clé d'API exigée pour `POST /api/chunk` |
| `MAP_MIPMAP_TOKEN` | *(vide)* | clé exigée pour les routes MipMap (`?key=`) |
| `MAP_PLAYER_TTL_MS` | `30000` | durée de vie d'un joueur (repli après inactivité) |
| `MAP_DATA_FILE` | `data/chunks.ndjson` | fichier de persistance |
| `MAP_TILE_CHUNKS` | `8` | taille d'une tuile en chunks |
| `MAP_SIZE` | `2000` | taille de vue annoncée à l'UI MipMap (px) |
| `MAP_UPDATE_INTERVAL` | `5000` | intervalle de rafraîchissement des joueurs (ms) |
| `MAP_DEFAULT_WORLD` | `Overworld` | monde ouvert au chargement (`Overworld`/`Nether`/`TheEnd`) |
| `MAP_TEXTURES_DIR` | `assets/textures/blocks` | dossier des textures de blocs |
| `MAP_RELIEF_MAX_SIDE` | `4096` | côté max (px) de l'image de relief |
| `MAP_RELIEF_EXAGGERATION` | `1` | exagération des écarts de hauteur dans l'ombrage (`1` = MipMap) |

**Configure la clé d'API** et mets la même valeur dans `api_key` du plugin :
sinon n'importe qui peut écrire sur ta carte.

Deux façons de la définir (la variable d'environnement reste prioritaire) :

1. **En haut de `server.js`** : change la constante
   ```js
   const API_KEY = "change-me";   // mets ta clé ici, "" pour désactiver
   ```
2. **Variable d'environnement** `MAP_API_KEY` (panel, systemd, `--env-file`…).

## API

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/api/chunk` | reçoit un chunk (header `X-Api-Key`) — plugin maison |
| `POST` | `/api/chunks-data` | reçoit `{"chunk": {...}}` — plugin MipMap |
| `POST` | `/api/players-data` | reçoit `{"players": [...]}` — plugin MipMap |
| `GET` | `/api/status` | chunks, tiles, dimensions, joueurs en ligne |
| `GET` | `/api/players` | joueurs connus, groupés par dimension |
| `GET` | `/api/meta?dim=<d>` | étendue + Y min/max d'une dimension |
| `GET` | `/api/config` | réglages de l'UI MipMap (`mapSize`, `updateInterval`, `defaultWorld`, zoom) |
| `GET` | `/api/tiles/<monde>/<zoom>/<x>/<y>` | **tuile PNG 256 px**, 16 px/bloc (textures + ombrage MipMap) |
| `GET` | `/api/players/<nom>/skin.png` | visage 8×8 (recadré du skin envoyé par le plugin) |
| `GET` | `/api/relief/<dim>` | **relief vu de dessus**, PNG ombré (rendu serveur) |
| `GET` | `/api/tile/<dim>/<tx>/<tz>` | chunks d'une tuile (consommé par l'UI) |
| `GET` | `/api/chunk/<dim>/<cx>/<cz>` | un chunk précis |
| `GET` | `/api/chunks?dim&cx0&cz0&cx1&cz1` | plage de chunks |
| `GET` | `/` | l'interface de la carte |

## Compatibilité MipMap

Ce serveur parle le **protocole d'ingestion de MipMap** sans utiliser son
propre serveur Python (FastAPI/Pillow/Leaflet) : on garde l'UI isométrique.

Le plugin MipMap envoie, en JSON, sur deux URL libres :

* `{"chunk": {"dimension": "Overworld", "blocks": [{"name": "minecraft:grass_block", "coordinates": [x, y, z]}, ...]}}`
  — 256 blocs de surface (le plus haut de chaque colonne) par chunk ;
* `{"players": [{"name": "Aymen", "xuid": "...", "skin": "<hex PNG>", "skinShape": "classic", "dimension": "Overworld", "x": .., "y": .., "z": ..}]}`

`mapserver/mipmap.js` convertit ces payloads au format interne : les blocs
sont regroupés par chunk (`x>>4`, `z>>4`), le plus haut `y` gagne par colonne,
et les dimensions sont normalisées (`"Overworld"` → `minecraft:overworld`,
`"The End"` / `"TheEnd"` → `minecraft:the_end`, `"Nether"` → `minecraft:nether`).

Les coordonnées de chunk ne sont **pas** dans le payload (le plugin les retire
avant l'envoi) : elles sont déduites des coordonnées de blocs, comme le fait le
serveur amont. Le calcul utilise un plancher mathématique, donc correct pour les
chunks négatifs.

### Configuration du plugin

Dans `plugins/mipmap/config.toml` :

```toml
sendPlayers = true

[api]
chunks = "http://151.240.30.8:10015/api/chunks-data"
players = "http://151.240.30.8:10015/api/players-data"
```

Si `MAP_MIPMAP_TOKEN` est défini côté serveur, ajoute la clé dans l'URL
(MipMap n'envoie aucun header d'authentification) :

```toml
chunks = "http://<IP_DU_SERVEUR>:10015/api/chunks-data?key=<TOKEN>"
players = "http://<IP_DU_SERVEUR>:10015/api/players-data?key=<TOKEN>"
```

**Le plugin exige une réponse HTTP 200** : sinon il journalise
`[Mipmap] HTTP error <status> for chunk (x, z)` et passe son chemin. Le serveur
répond `200` uniquement si le chunk contient au moins un bloc valide, `400` pour
du JSON illisible et `422` pour un payload vide ou invalide.

Le plugin livré dans `plugin-mipmap/` est le MipMap d'amont porté sur
**Endstone 0.11** (voir son README pour la liste des correctifs). Le format
d'échange est inchangé, donc un MipMap 0.10 d'origine écrit aussi sur ce serveur.

Les joueurs sont mémorisés **30 secondes** (`MAP_PLAYER_TTL_MS`) après leur
dernier envoi, puis retirés automatiquement — comme ça les marqueurs disparaissent
quand le serveur Bedrock s'éteint.

## Persistance

Les chunks sont écrits en **append-only** dans `data/chunks.ndjson`
(une ligne = un chunk). Au démarrage le fichier est relu, la dernière valeur
l'emporte, puis un **compactage** est lancé si le fichier est gonflé par les
mises à jour. Écrit proprement à l'arrêt (`SIGINT`/`SIGTERM`).

## Relief vu de dessus (rendu serveur)

`GET /api/relief/<dim>` renvoie un **PNG** — pas du JSON — calculé par le
serveur à partir des chunks stockés :

1. `relief.js` construit une grille **1 pixel = 1 bloc** (hauteur du bloc de
   surface + couleur), bornée par l'étendue de la dimension. Si le monde dépasse
   `MAP_RELIEF_MAX_SIDE` / 12 M pixels, la grille est sous-échantillonnée
   (hauteur maximale conservée) pour garder un fichier raisonnable.
2. La grille est **éclairée avec la recette de MipMap** (`webmap/services/tileGenerator.py`) :
   * teinte d'altitude par bandes : assombri + voile **bleu** sous le niveau de
     la mer (Y = 63), ×0.9 jusqu'à Y = 100, de plus en plus clair vers les
     sommets, voile **blanc** au-dessus de Y = 200 ;
   * **occlusion ambiante** sur les 8 voisins (un voisin plus haut assombrit) ;
   * **éclairage directionnel** depuis le **nord-ouest** (3 voisins) ;
   * **courbes de niveau** tous les 20 blocs (voile noir, alpha 30).
   Les zones non cartographiées restent transparentes.

   MipMap recouvre chaque bloc de sa texture 16×16 et travaille en 16 px/bloc
   avec une pyramide de zoom ; ici on reste en 1 px/bloc dans un seul PNG, la
   couleur vient de `public/blocks.js`, mais l'éclairement suit la même formule.
3. `png.js` encode le résultat en PNG RGBA avec le `zlib` **intégré à Node** :
   aucune dépendance n'est ajoutée (pas de canvas, pas de sharp).

Le PNG est **mis en cache** par dimension et invalidé dès qu'un nouveau chunk
arrive : recharger la page ne relance pas le rendu tant que rien n'a changé.
Une dimension sans chunk renvoie `404`.

C'est un rendu **synchrone** : sur un très gros monde la première génération
prend quelques instants (les suivantes sont servies depuis le cache).

## Interface MipMap portée en Node.js

L'UI web de MipMap (`webmap/web/`, MIT) est **vendorée** dans
`public/mipmap/` et servie sur `/` : carte **Leaflet** plein écran,
sélecteur Overworld / Nether / End, coordonnées cliquables et marqueurs de
joueurs avec leur visage. Ses assets sont servis sous `/static/*`.

Le serveur Python (FastAPI + Pillow de MipMap) n'est **pas** utilisé : les
routes qu'attend cette UI sont réimplémentées ici, sans dépendance :

* `/api/config` — réglages (`MAP_SIZE`, `MAP_UPDATE_INTERVAL`, monde par défaut) ;
* `/api/players` — liste `players[]` avec `dimension` en nom de monde et
  l'URL du visage ;
* `/api/players/<nom>/skin.png` — visage 8×8 recadré du skin brut envoyé par
  le plugin (repli : `assets/skins/default.png`) ;
* `/api/tiles/<monde>/<zoom>/<x>/<y>` — tuile PNG **rendue à la volée**.

### Rendu des tuiles

Comme MipMap, chaque bloc est recouvert de **sa texture 16×16**
(`assets/textures/blocks`, 970+ fichiers vendorés depuis MipMap) puis éclairé
avec la recette MipMap (`shade.js`) : bandes d'altitude, occlusion ambiante,
lumière nord-ouest, courbes de niveau. Particularités de ce port :

* `png.js` décode les textures (palette 2/4/8 bits, RVB, RGBA, tRNS, filtres
  0–4) en plus d'encoder le PNG de sortie — toujours **zéro dépendance** ;
* une tuile de zoom 4 fait 256 px pour 16 blocs (16 px/bloc) ; le zoom 0
  couvre 256 blocs à 1 px/bloc : la tuile est rendue **directement** à la
  résolution demandée (pas de pyramide pré-générée comme `zoomGenerator.py`) ;
* les textures animées (bandes 16×64…) ne gardent que la **première image** ;
* la **banque de textures est complétée** : beaucoup de blocs Bedrock n'ont pas
  de fichier à leur nom (clôtures, murs, vitres, portes…). MipMap les peignait
  en magenta ; ici le bloc est résolu vers son matériau de base
  (`oak_fence` → `oak_planks`, `*_wall` → pierre, `*_glass_pane` → verre teinté,
  `melon` → `melon_block`, `iron_bars` → `iron_block`…), et à défaut il est
  peint avec la **couleur du bloc** (`public/blocks.js`) — plus de blocs roses ;
* les tuiles sont **mises en cache** (clé `store.rev`) et revalidées par `ETag`
  (`Cache-Control: no-cache`, `304` si rien n'a bougé) : le navigateur ne
  conserve donc pas une tuile vide alors que des chunks viennent d'arriver ;
* une zone non cartographiée répond **`200` avec une tuile transparente**
  (et non `404`) : Leaflet garde l'affichage stable au lieu de faire
  disparaître des morceaux quand on dézoome, et une erreur de rendu renvoie la
  tuile vide plutôt qu'un `500`.

L'ancienne interface canvas (isométrique 3D + relief) reste disponible sur
`/index.html`.

## Tests

```bash
npm test        # 26 scénarios : auth, API, statique, persistance, protocole MipMap, relief, ombrage, tuiles MipMap
```

## Interface

`public/` — canvas plein écran, déplacement à la souris, molette pour zoomer,
sélecteur de dimension, bascule **3D / Relief**. La carte s'ouvre en **relief**
(vue de dessus) ; le bouton **3D** bascule vers l'isométrique.

* **Vue relief** : l'image PNG de `/api/relief/<dim>` est affichée telle quelle
  (serveur), avec sa taille en légende. **Déplaçable et zoomable** : glisser
  pour déplacer, molette pour zoomer sous le curseur, double-clic pour
  recentrer. Les tuiles ne sont pas téléchargées dans ce mode.
* **Rendu 3D** : projection isométrique, faces top + deux faces latérales
  (parois colorées grâce à `depth > 1` côté plugin), ordre peintre par `x+z`.
* **Performance** : le monde est rendu **progressivement** dans un canvas
  hors-échelle (22 ms par frame), puis simplement blité à chaque image →
  pan/zoom fluides. Un rebuild est relancé quand des tuiles arrivent.
* **Chargement** : seules les tuiles **visibles** sont téléchargées,
  6 en parallèle.
* **Joueurs** : marqueurs 3D (ombre au sol + silhouette) tirés de `api/players`,
  plus une liste latérale des joueurs connectés.
* **Couleurs** : table `public/blocks.js`, avec repli déterministe pour les
  blocs inconnus.
