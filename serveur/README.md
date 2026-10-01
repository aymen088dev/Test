# Dossier serveur Endstone

Contient l'installeur Endstone lancé par le wrapper `../bedrock_server`.

- `start.sh` : installe Python 3 s'il manque, crée un venv (`serveur/.venv`),
  installe/maj Endstone, puis lance le serveur.
- `.venv/` : environnement Python persistant (créé automatiquement).
- `plugins/` : dépose ici tes plugins Endstone au format `.whl`, puis redémarre.

## Utilisation sur Pterodactyl

1. Arrête le serveur.
2. Renomme le binaire vanilla `bedrock_server` → `bedrock_server.orig`.
3. Copie `bedrock_server` et tout le dossier `serveur/` à la racine du serveur.
4. `chmod +x bedrock_server` (via SFTP — le gestionnaire web ne pose pas le +x).
5. Démarre. La commande fixe `./bedrock_server` lance Endstone.

Variable optionnelle : `ENDSTONE_VERSION` (ex. `0.11.5`) pour épingler une version.
