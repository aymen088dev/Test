# WebUI — interface in-game + tableau de bord web

Plugin Endstone (Python) qui ajoute la commande **`/test`** :

- un **menu natif** en jeu (boutons : tableau de bord, profil, joueurs, infos) ;
- un **tableau de bord HTML/CSS/JS** servi par un mini serveur web interne,
  accessible via un **lien** que le joueur ouvre dans son navigateur.

## ⚠️ À savoir sur le "full custom"

Minecraft Bedrock **ne peut pas afficher de HTML en jeu**. Le moteur ne rend que
ses *forms* natives (JSON-UI au maximum). Le seul moyen d'avoir une vraie UI
HTML/CSS/JS, c'est de la servir **hors du jeu**, dans un navigateur — c'est ce
que fait ce plugin :

```
/test          -> menu natif en jeu (Bedrock)
/test web      -> lien vers le dashboard HTML/CSS/JS (navigateur)
```

## Contenu

```
plugin-webui/
├── pyproject.toml            # métadonnées + entry point "endstone"
├── build.sh                  # build du .whl (uv)
└── src/endstone_webui/
    ├── __init__.py
    ├── plugin.py             # commande /test, menu, config, API status
    ├── server.py             # serveur HTTP interne (statique + /api/status)
    ├── config.toml           # config par défaut (copiée au 1er démarrage)
    └── web/                  # LE dashboard
        ├── index.html
        ├── styles.css
        └── app.js
```

## Build

```bash
cd plugin-webui
./build.sh          # -> dist/endstone_webui-0.1.0-py3-none-any.whl
```

Sans `uv` : `python3 -m build` (nécessite `pip install build`).

## Installation

1. Copie le `.whl` de `dist/` dans le dossier **`plugins/`** du serveur.
2. Redémarre (ou `/reload`).

## Configuration (`config.toml`)

Créé automatiquement au premier démarrage dans le dossier de données du plugin.

```toml
web_host = "0.0.0.0"   # adresse d'écoute
web_port = 8090        # PORT À ALLOUER dans Pterodactyl
public_url = ""        # ex. "http://123.45.67.89:8090" (affiché aux joueurs)
```

### Pterodactyl

Le serveur web écoute **dans le conteneur**. Pour y accéder depuis l'extérieur :

1. Dans le panel, ajoute une **allocation** avec le port `8090` (ou un autre).
2. Renseigne `public_url` avec l'adresse publique (`http://<ip-du-node>:<port>`),
   ou passe par un **reverse-proxy / domaine** si tu en as un.
3. `/test web` envoie alors le lien aux joueurs.

> Note : certains hébergeurs n'exposent que le port de jeu. Si le port web
> n'est pas joignable, le tableau de bord reste accessible en local
> (`http://localhost:8090`) sur la machine du serveur.

## API

- `GET /` → dashboard
- `GET /api/status` → JSON live : nom, version, joueurs, TPS, MSPT, uptime
