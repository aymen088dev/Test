#!/bin/sh
# ---------------------------------------------------------------------------
# serveur/start.sh  ==  installeur + launcher ENDSTONE (bundle officiel)
#
# Aucune verification de Python : le bundle officiel embarque "uv", qui
# installe lui-meme un Python gere (python-build-standalone). Il n'y a donc
# PAS besoin d'un python3 systeme dans le conteneur.
#
# Ce script :
#   1. determine la version (ENDSTONE_VERSION, sinon la derniere release),
#   2. telecharge le bundle officiel endstone-<ver>-linux-x86_64.zip
#      depuis github.com/EndstoneMC/endstone/releases (start.sh + .whl +
#      LICENSE + CHANGELOG),
#   3. l'extrait dans serveur/endstone/,
#   4. prepare le dossier serveur Endstone ISOLE : serveur/data/
#   5. lance le start.sh officiel du bundle avec  -s <serveur/data> -y
#
# ---------------------------------------------------------------------------
# POURQUOI serveur/data/ ET PAS LA RACINE
# Endstone deploie le binaire Bedrock Dedicated Server dans son "server
# folder", sous le nom EXACT "bedrock_server" (voir executable_filename dans
# endstone/cli/base.py), et il ecrase toujours ce fichier. Si on lui donnait
# la racine du serveur, il remplacait notre wrapper ./bedrock_server par le
# binaire BDS. On isole donc Endstone dans serveur/data/, et le wrapper de la
# racine est preserve.
# ---------------------------------------------------------------------------
#
# Variable optionnelle : ENDSTONE_VERSION (ex. 0.11.12) pour epingler.
# ---------------------------------------------------------------------------

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT" || exit 1

REPO="EndstoneMC/endstone"
DEST="$HERE/endstone"
SERVER_DIR="$HERE/data"

echo "[endstone] Racine serveur   : $ROOT"
echo "[endstone] Dossier Endstone : $SERVER_DIR"

# --- Outil de telechargement --------------------------------------------
if command -v curl >/dev/null 2>&1; then
    DL="curl"
elif command -v wget >/dev/null 2>&1; then
    DL="wget"
else
    echo "[endstone] ERREUR : ni curl ni wget disponibles." >&2
    exit 1
fi

# --- 1) Version ----------------------------------------------------------
if [ -n "${ENDSTONE_VERSION:-}" ]; then
    VER="${ENDSTONE_VERSION#v}"
    echo "[endstone] Version epinglee : $VER"
else
    if [ "$DL" = "curl" ]; then
        VER="$(curl -fsSL -o /dev/null -w '%{url_effective}' \
            "https://github.com/$REPO/releases/latest" 2>/dev/null \
            | sed -n 's#.*/tag/v\{0,1\}##p')"
    else
        VER="$(wget -qO- "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
            | sed -n 's/.*"tag_name": *"v\{0,1\}\([^"]*\)".*/\1/p' | head -n 1)"
    fi
    if [ -z "$VER" ]; then
        echo "[endstone] ERREUR : impossible de determiner la derniere version." >&2
        exit 1
    fi
    echo "[endstone] Derniere version : $VER"
fi

BUNDLE="endstone-${VER}-linux-x86_64"
URL="https://github.com/$REPO/releases/download/v${VER}/${BUNDLE}.zip"
BUNDLE_DIR="$DEST/$BUNDLE"
BUNDLE_START="$BUNDLE_DIR/start.sh"

# --- 2) Telechargement du bundle officiel -------------------------------
if [ ! -f "$BUNDLE_START" ]; then
    mkdir -p "$DEST"
    echo "[endstone] Telechargement : $URL"
    if [ "$DL" = "curl" ]; then
        curl -fL --retry 3 -o "$DEST/$BUNDLE.zip" "$URL" \
            || { echo "[endstone] ERREUR : telechargement echoue (version inexistante ?)." >&2; exit 1; }
    else
        wget -O "$DEST/$BUNDLE.zip" "$URL" \
            || { echo "[endstone] ERREUR : telechargement echoue (version inexistante ?)." >&2; exit 1; }
    fi

    # --- 3) Extraction (plusieurs extracteurs en secours) ---------------
    echo "[endstone] Extraction..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -q -o "$DEST/$BUNDLE.zip" -d "$DEST"
    elif command -v bsdtar >/dev/null 2>&1; then
        bsdtar -xf "$DEST/$BUNDLE.zip" -C "$DEST"
    elif command -v busybox >/dev/null 2>&1; then
        busybox unzip -o "$DEST/$BUNDLE.zip" -d "$DEST"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m zipfile -e "$DEST/$BUNDLE.zip" "$DEST"
    else
        echo "[endstone] ERREUR : aucun extracteur zip (unzip/bsdtar/busybox/python3)." >&2
        exit 1
    fi
    rm -f "$DEST/$BUNDLE.zip"

    if [ ! -f "$BUNDLE_START" ]; then
        echo "[endstone] ERREUR : $BUNDLE_START introuvable apres extraction." >&2
        exit 1
    fi
    echo "[endstone] Bundle installe : $BUNDLE_DIR"
else
    echo "[endstone] Bundle deja present : $BUNDLE_DIR"
fi

# --- 4) Dossier serveur Endstone ISOLE (protege le wrapper racine) ------
mkdir -p "$SERVER_DIR"

# server.properties : le panel edite la RACINE. Endstone lit/ecrit le meme
# fichier via un lien symbolique (il ouvre le fichier en lecture puis en
# ecriture, donc le lien est suivi et preserve).
if [ ! -f "$ROOT/server.properties" ] && [ -f "$HERE/server.properties" ]; then
    echo "[endstone] Creation de server.properties a la racine."
    cp "$HERE/server.properties" "$ROOT/server.properties"
fi
if [ -f "$ROOT/server.properties" ]; then
    ln -sfn "$ROOT/server.properties" "$SERVER_DIR/server.properties"
else
    echo "[endstone] ATTENTION : aucun server.properties a la racine." >&2
fi

# plugins : depose tes .whl dans plugins/ a la racine
if [ ! -e "$ROOT/plugins" ]; then
    ln -sfn "$SERVER_DIR/plugins" "$ROOT/plugins"
fi
mkdir -p "$SERVER_DIR/plugins"

# --- 5) Lancement via le start.sh OFFICIEL du bundle --------------------
if command -v bash >/dev/null 2>&1; then
    SH="bash"
else
    SH="sh"
fi
echo "[endstone] Demarrage : $SH $BUNDLE_START -s $SERVER_DIR -y"
exec "$SH" "$BUNDLE_START" -s "$SERVER_DIR" -y
