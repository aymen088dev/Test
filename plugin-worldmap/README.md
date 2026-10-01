# WorldMap — scanner de monde pour Endstone

Plugin Endstone (Python) qui lit le monde et envoie la **carte en direct** à un
serveur Node.js (le projet `mapserver/` à la racine du dépôt).

## Commandes

| Commande | Effet |
|---|---|
| `/map` | état du scan + connexion au serveur de carte |
| `/mapscan [rayon]` | lance (ou relance) le scan — *op* |
| `/mapstop` | arrête le scan — *op* |

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
api_key  = "change-me"                    # doit matcher MAP_API_KEY

center_x = 0            # 0,0 = spawn du monde
center_z = 0
radius_chunks = 32      # 32 ≈ 1 000 blocs, 64 ≈ 2 000, 128 ≈ 4 000
dimensions  = ["overworld"]

depth = 4               # blocs solides par colonne
chunks_per_tick = 2     # baisse si le serveur rame
send_delay_ms = 50
auto_scan = true
stop_when_empty = false
```

> ⚠️ **Profondeur de données** : `radius_chunks = 64` avec `depth = 4` envoie
> ~16 000 chunks. Commence petit (32), vois le rendu, puis agrandis.

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

Valide sans Endstone : `build_queue`, `scan_chunk` (surface + profondeur),
démarrage du serveur Node, envoi HTTP avec clé d'API, et le service des
fichiers statiques.
