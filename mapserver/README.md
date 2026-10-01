# mapserver — carte isometrique en direct

Serveur **Node.js zéro dépendance** qui reçoit les chunks scannés par le plugin
`plugin-worldmap/` et sert une **carte isométrique 3D** dans le navigateur
(style BlueMap).

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
| `MAP_DATA_FILE` | `data/chunks.ndjson` | fichier de persistance |
| `MAP_TILE_CHUNKS` | `8` | taille d'une tuile en chunks |

**Mets `MAP_API_KEY`** et mets la même valeur dans `api_key` du plugin :
sinon n'importe qui peut écrire sur ta carte.

## API

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/api/chunk` | reçoit un chunk (header `X-Api-Key`) |
| `GET` | `/api/status` | chunks, tiles, dimensions |
| `GET` | `/api/meta?dim=<d>` | étendue + Y min/max d'une dimension |
| `GET` | `/api/tile/<dim>/<tx>/<tz>` | chunks d'une tuile (consommé par l'UI) |
| `GET` | `/api/chunk/<dim>/<cx>/<cz>` | un chunk précis |
| `GET` | `/api/chunks?dim&cx0&cz0&cx1&cz1` | plage de chunks |
| `GET` | `/` | l'interface de la carte |

## Persistance

Les chunks sont écrits en **append-only** dans `data/chunks.ndjson`
(une ligne = un chunk). Au démarrage le fichier est relu, la dernière valeur
l'emporte, puis un **compactage** est lancé si le fichier est gonflé par les
mises à jour. Écrit proprement à l'arrêt (`SIGINT`/`SIGTERM`).

## Tests

```bash
npm test        # 14 assertions : auth, API, statique, persistance
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
* **Couleurs** : table `public/blocks.js`, avec repli déterministe pour les
  blocs inconnus.
