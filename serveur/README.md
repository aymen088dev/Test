# Dossier serveur Endstone

Contient l'installeur Endstone lancé par le wrapper `../bedrock_server`.

## Ce qu'il y a ici

- `start.sh` : installeur + launcher. Il télécharge le **bundle officiel**
  `endstone-<version>-linux-x86_64.zip` depuis
  `github.com/EndstoneMC/endstone/releases`, l'extrait dans `endstone/`,
  puis lance le `start.sh` officiel du bundle.
- `server.properties` : modèle copié à la racine du serveur s'il n'existe pas.
- `endstone/` : bundle officiel téléchargé (créé automatiquement, non versionné).
- `data/` : **dossier serveur Endstone** isolé (créé automatiquement) : binaire
  BDS, mondes, `endstone.toml`, venv. Non versionné.

## Pourquoi `data/` et pas la racine

Endstone déploie le binaire Bedrock Dedicated Server dans son *server folder*
sous le nom exact **`bedrock_server`**, et il écrase toujours ce fichier (cf.
`executable_filename` dans `endstone/cli/base.py`). Si on lui donnait la racine,
il remplacerait notre wrapper `./bedrock_server` par le binaire BDS.

C'est pourquoi Endstone tourne dans `serveur/data/` :

- le wrapper `./bedrock_server` de la racine n'est **jamais** écrasé ;
- le `server.properties` de la racine reste la référence du panel : `data/server.properties`
  est un lien symbolique vers lui, donc le panel et Endstone lisent le même fichier ;
- `plugins/` à la racine pointe vers `data/plugins/`.

## Pas besoin de Python système

Le bundle officiel embarque **uv**, qui télécharge et gère lui-même un
interpréteur Python (python-build-standalone) dans son propre `.venv`.
Le script ne vérifie donc pas et n'installe pas de `python3` système.

## Utilisation sur Pterodactyl

1. Arrête le serveur.
2. Renomme le binaire vanilla `bedrock_server` → `bedrock_server.orig`.
3. Copie `bedrock_server` et tout le dossier `serveur/` à la racine du serveur.
4. `chmod +x bedrock_server` (via SFTP — le gestionnaire web ne pose pas le +x).
5. Démarre. La commande fixe `./bedrock_server` lance Endstone.

Plugins : dépose tes `.whl` dans `plugins/` à la racine, puis redémarre.

## Version

- Par défaut : la **dernière release** officielle à chaque (re)démarrage.
- Épingler une version : variable d'environnement `ENDSTONE_VERSION`
  (ex. `0.11.12`).

Pour forcer une mise à jour de version, supprime le dossier `serveur/endstone/`.
