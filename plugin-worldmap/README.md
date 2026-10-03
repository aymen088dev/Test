# WorldMap — scanner de monde pour Endstone

Plugin Endstone (Python) qui lit le monde et envoie la **carte en direct** à un
serveur Node.js (le projet `mapserver/` à la racine du dépôt).

## Commandes

| Commande | Effet |
|---|---|
| `/map` | état du scan, joueurs connectés, chunks chargés — connexion serveur |
| `/mapscan [rayon]` | scanne une fois les chunks **chargés** autour des joueurs — *op* |
| `/mapfollow` | active/désactive le suivi continu des joueurs (carte live) — *op* |
| `/mapstop` | arrête le scan et le suivi — *op* |
| `/maptest` | teste l'URL, la clé d'API et affiche l'état du monde — *op* |

## Pourquoi le scan suit les joueurs

Le serveur Bedrock ne garde **en mémoire** que les chunks qui entourent les
joueurs connectés (le `view-distance` de `server.properties`). L'API Endstone ne
peut pas lire un chunk non chargé : `get_highest_block_at()` y renvoie de l'air.

C'est pour ça qu'un scan « rayon 32 » (1 024 blocs de côté) produisait
4 225 chunks **vides**. Le plugin ne met donc plus en file que ce que
`Dimension.loaded_chunks` contient, trié par distance au joueur le plus proche.

Conséquence : **il faut au moins un joueur connecté pour que la carte avance**,
et la zone cartographiée correspond à ce que les joueurs explorent. C'est le
compromis inherent à BDS : lire le monde « hors ligne » demanderait de parser
soi-même `level.db` (pas possible depuis l'API).

## Comment ça marche

1. Le scan tourne **sur le thread principal** (contrainte de l'API Endstone),
   `chunks_per_tick` chunks à la fois, via le scheduler.
2. Pour chaque colonne, `Dimension.get_highest_block_at(x, z)` donne le bloc du
   dessus, puis on descend de `depth` blocs pour recolter les **parois** visibles.
3. Le payload part dans une **file**, envoyé par un thread daemon en `POST
   /api/chunk` (zéro dépendance : `urllib` de la bibliothèque standard).

### Format du payload

```json
{
  "v": 1,
  "dim": "minecraft:overworld",
  "cx": 3, "cz": -2,
  "depth": 4,
  "palette": ["minecraft:grass_block", "minecraft:stone"],
  "cells": [[64, 0, 63, 1, 62, 1, 61, 1], "..."]
}
```

`cells` contient 256 entrées (index `lz*16 + lx`), chacune une liste de paires
`(y, index_de_palette)` allant du haut vers le bas, en ignorant l'air.

* `depth = 1` → simple heightmap (colonne d'une couleur)
* `depth = 4` → + parois colorées → rendu isométrique type BlueMap

## Configuration (`src/endstone_worldmap/config.toml`)

Copié automatiquement dans le dossier de données du plugin au premier démarrage.

```toml
endpoint = "http://151.240.30.8:10015"   # serveur Node.js
api_key  = "changh"                       # doit matcher la clé du serveur

center_x = 0            # 0,0 = suit les joueurs connectés
center_z = 0
radius_chunks = 0       # 0 = tout ce qui est chargé ; 8 = proche des joueurs
dimensions  = ["overworld"]

depth = 4               # blocs solides par colonne
chunks_per_tick = 2     # baisse si le serveur rame
send_delay_ms = 50
auto_scan = false       # scan unique au démarrage
auto_follow = true      # carte live : suivi des joueurs
follow_interval_seconds = 10
```

> ⚠️ **Volume** : avec `view-distance = 10`, un joueur charge ~2 100 chunks.
> `chunks_per_tick = 2` (40 chunks/s) et `send_delay_ms = 50` (20 envois/s) : la
> première passe prend ~1 min 45. Baisse `depth` si tu veux aller plus vite.

## Utilisation

```
/mapfollow      # la carte se construit toute seule quand tu joues
/map            # suivi : nombre de chunks traités/envoyés
/mapscan        # scan ponctuel de la zone actuellement chargée
/mapscan 4      # seulement les chunks à 4 chunks (64 blocs) du joueur
/mapstop        # stoppe tout
```

Le suivi mémorise les chunks déjà envoyés (`_seen`) : un chunk déjà cartographié
n'est renvoyé que s'il change réellement. La première fois qu'un joueur se
connecte après un redémarrage du serveur, toute sa zone est renvoyée.

## Build & install

```bash
cd plugin-worldmap
./build.sh        # -> dist/endstone_worldmap-0.1.0-py3-none-any.whl
```

Copie le `.whl` dans le dossier **`plugins/`** du serveur Endstone, puis
redémarre.

## Tests

```bash
python3 test_pipeline.py
```

Valide sans Endstone : `build_queue_loaded` (file limitée aux chunks chargés,
rayon, dédoublonnage du suivi), `scan_chunk` (surface + profondeur),
démarrage du serveur Node, envoi HTTP avec clé d'API, et le service des
fichiers statiques.
