#!/bin/sh
# ---------------------------------------------------------------------------
# serveur/start.sh  ==  installeur + lanceur Endstone
#
# 1. Verifie / installe Python 3 (apt, apk ou dnf) s'il est absent.
# 2. Cree un environnement virtuel persistant (serveur/.venv).
# 3. Installe ou met a jour Endstone (variable ENDSTONE_VERSION optionnelle).
# 4. Lance Endstone sur la racine du serveur.
#
# Ce fichier est lance par le wrapper ../bedrock_server. Pour le rendre
# appelable directement : chmod +x serveur/start.sh
# ---------------------------------------------------------------------------

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT" || exit 1

echo "[endstone] Dossier serveur : $ROOT"

# --- 1) Python 3 present ? sinon on l'installe ---------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[endstone] python3 absent : demande d'installation..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -y && apt-get install -y python3 python3-pip python3-venv
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 py3-pip
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 python3-pip
    else
        echo "[endstone] ERREUR : aucun gestionnaire de paquets (apt/apk/dnf)." >&2
        echo "[endstone] Impossible d'installer python3 depuis ce conteneur." >&2
        exit 1
    fi
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[endstone] ERREUR : python3 toujours introuvable apres installation." >&2
    exit 1
fi

PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)"
echo "[endstone] Python $PYVER detecte."

# --- 2) Environnement virtuel persistant ---------------------------------
VENV="$HERE/.venv"
if [ ! -x "$VENV/bin/python" ]; then
    echo "[endstone] Creation de l'environnement virtuel ($VENV)..."
    if ! python3 -m venv "$VENV"; then
        if command -v apt-get >/dev/null 2>&1; then
            apt-get install -y python3-venv
        fi
        python3 -m venv "$VENV" || { echo "[endstone] ERREUR : venv impossible." >&2; exit 1; }
    fi
fi

# --- 3) Installation / mise a jour d'Endstone ----------------------------
if [ -n "$ENDSTONE_VERSION" ]; then
    PKG="endstone==$ENDSTONE_VERSION"
else
    PKG="endstone"
fi
echo "[endstone] Installation de $PKG..."
"$VENV/bin/python" -m pip install -q -U pip
"$VENV/bin/python" -m pip install -q -U --no-warn-script-location "$PKG"

# --- 4) Lancement --------------------------------------------------------
mkdir -p plugins
echo "[endstone] Demarrage du serveur Endstone..."
exec "$VENV/bin/python" -m endstone -s "$ROOT" -y
