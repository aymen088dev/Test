# mapserver — carte isométrique en direct

Serveur **Node.js zéro dépendance** qui reçoit les chunks scannés par un plugin
Endstone et sert une **carte isométrique 3D** dans le navigateur (style BlueMap).

Deux sources de données sont acceptées :

* **`plugin-worldmap/`** — plugin maison, envoi un chunk à la fois sur
  `POST /api/chunk` (header `X-Api-Key`).
* **[MipMap](https://github.com/MipaSenpai/MipMap)** — plugin communautaire,
  paiement des chunks et des joueurs sur `POST /api/chunks-data` et
  `POST /api/players-data`. Voir [Compatibilité MipMap](#compatibilité-mipmap).

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

Dans `plugins/MipMap/config.toml` :

```toml
[api]
chunks = "http://<IP_DU_SERVEUR>:10015/api/chunks-data"
players = "http://<IP_DU_SERVEUR>:10015/api/players-data"
sendPlayers = true
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

Le MipMap d'amont déclare `api_version = "0.10"` (Endstone 0.10) ; le format
d'échange n'a pas changé, le plugin fonctionne sur Endstone 0.11.

Les joueurs sont mémorisés **30 secondes** (`MAP_PLAYER_TTL_MS`) après leur
dernier envoi, puis retirés automatiquement — comme ça les marqueurs disparaissent
quand le serveur Bedrock s'éteint.

## Persistance

Les chunks sont écrits en **append-only** dans `data/chunks.ndjson`
(une ligne = un chunk). Au démarrage le fichier est relu, la dernière valeur
l'emporte, puis un **compactage** est lancé si le fichier est gonflé par les
mises à jour. Écrit proprement à l'arrêt (`SIGINT`/`SIGTERM`).

## Tests

```bash
npm test        # 22 assertions : auth, API, statique, persistance, protocole MipMap
```

## Interface

`public/` — canvas plein écran, déplacement à la souris, molette pour zoomer,
sélecteur de dimension.

* **Rendu** : projection isométrique, faces top + deux faces latérales
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
