#!/usr/bin/env zsh

# Placement automatique dans le répertoire du script
THIS_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$THIS_DIR"

APP_NAME="TriCoreDownloader"
SCRIPT_NAME="run_TriCoreDownloader.py"
VENV_DIR="$THIS_DIR/.venv"
FLAG_FILE="$THIS_DIR/.env_ok"
MODULES=(PyQt6 requests urllib3 anyio pyopenssl multidict netifaces2 pyctr cryptography)

# Fichier de configuration sous macOS (~/Library/Application Support/TriCoreDownloader/config.json)
CONFIG_DIR="$HOME/Library/Application Support/TriCoreDownloader"
CONFIG_FILE="$CONFIG_DIR/config.json"

# Détection de l'option logs avancés
ADVANCED_LOGS="False"
if [ -f "$CONFIG_FILE" ]; then
    if python3 -c "import json, sys; sys.exit(0 if json.load(open('$CONFIG_FILE')).get('advanced_logs') else 1)" 2>/dev/null; then
        ADVANCED_LOGS="True"
    fi
fi

# Détection de la langue du système macOS
OS_LOCALE=$(defaults read -g AppleLocale 2>/dev/null || echo "$LANG")
if [[ "$OS_LOCALE" == fr* ]]; then
    LANG_CODE="FR"
else
    LANG_CODE="EN"
fi

if [ "$LANG_CODE" = "FR" ]; then
    MSG_FILE_MISSING="[ERREUR] Le fichier est introuvable :"
    MSG_ALREADY_RUNNING="[INFO] L'application est déjà en cours d'exécution."
    MSG_PURGE_HINT="[INFO] Appuyez sur la touche [P] dans les 3 secondes pour purger l'environnement et le cache."
    MSG_PURGE_DETECTED="[!] Touche de purge détectée. Nettoyage en cours..."
    MSG_PURGE_SUCCESS="[OK] Cache et environnement virtuels purgés avec succès."
    MSG_CHK_PY="[1/3] Vérification de l'installation de Python (3.12+)..."
    MSG_REQ_PY="[ERREUR] Python 3.12 ou supérieur est requis. Installez-le via 'brew install python@3.12' ou depuis python.org."
    MSG_SETUP_MOD="[2/3] Configuration de l'environnement virtuel (.venv) et des modules..."
    MSG_UP_PIP="[INFO] Mise à jour de PIP..."
    MSG_INS_COMP="[INFO] Installation des composants principaux..."
    MSG_OPT_ENV="[INFO] Optimisation de l'environnement..."
    MSG_LAUNCH="[INFO] LANCEMENT :"
    MSG_PY_EXE="[INFO] Exécutable Python :"
    MSG_ERR_EXIT="[ERREUR] Le script Python s'est fermé avec le code :"
    MSG_STARTING="[INFO] Démarrage en cours..."
else
    MSG_FILE_MISSING="[ERROR] File not found :"
    MSG_ALREADY_RUNNING="[INFO] Application is already running."
    MSG_PURGE_HINT="[INFO] Press [P] key within 3 seconds to purge environment and cache."
    MSG_PURGE_DETECTED="[!] Purge key detected. Cleaning up..."
    MSG_PURGE_SUCCESS="[OK] Cache and virtual environment purged successfully."
    MSG_CHK_PY="[1/3] Checking for Python (3.12+) installation..."
    MSG_REQ_PY="[ERROR] Python 3.12 or higher is required. Install it via Homebrew or python.org."
    MSG_SETUP_MOD="[2/3] Virtual environment (.venv) and module setup..."
    MSG_UP_PIP="[INFO] Updating PIP..."
    MSG_INS_COMP="[INFO] Installing main components..."
    MSG_OPT_ENV="[INFO] Environment optimization..."
    MSG_LAUNCH="[INFO] LAUNCHING :"
    MSG_PY_EXE="[INFO] Python Executable :"
    MSG_ERR_EXIT="[ERROR] Python script exited with code :"
    MSG_STARTING="[INFO] Starting application..."
fi

# 1. Vérification du script principal
if [ ! -f "$THIS_DIR/$SCRIPT_NAME" ]; then
    echo "$MSG_FILE_MISSING$SCRIPT_NAME"
    read -k 1 "?Appuyez sur une touche pour quitter..."
    exit 1
fi

# 2. Vérification d'une instance déjà en cours
if pgrep -f "$SCRIPT_NAME --id=$APP_NAME" >/dev/null 2>&1; then
    echo "$MSG_ALREADY_RUNNING"
    sleep 2
    exit 0
fi

# 3. Détection de la touche de purge [P] (3 secondes)
echo "$MSG_PURGE_HINT"
read -k 1 -t 3 KEY 2>/dev/null
if [[ "$KEY" == "p" \vert{}\vert{} "$KEY" == "P" ]]; then
    echo ""
    echo "$MSG_PURGE_DETECTED"
    rm -rf "$VENV_DIR" "$FLAG_FILE"
    find "$THIS_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
    echo "$MSG_PURGE_SUCCESS"
    sleep 1
    clear
fi

# Fonction de recherche d'une version Python 3.12+ compatible
find_python() {
    for cmd in python3.12 python3.13 python312 python3; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
                echo "$(command -v "$cmd")"
                return 0
            fi
        fi
    done
    return 1
}

# 4. Lancement rapide si l'environnement `.venv` existe et est valide
if [ -f "$FLAG_FILE" ] && [ -d "$VENV_DIR" ]; then
    PY_BIN="$VENV_DIR/bin/python"
    if [ -f "$PY_BIN" ]; then
        if [ "$ADVANCED_LOGS" = "True" ]; then
            echo "[$(date)] Fast launching with cached venv:$PY_BIN"
            echo ""
        else
            echo ""
            echo "$MSG_STARTING"
            echo "OK."
            echo ""
        fi

        "$PY_BIN" "$THIS_DIR/$SCRIPT_NAME" --id="$APP_NAME"
        PY_ERR=$?

        if [ $PY_ERR -ne 0 ]; then
            echo ""
            echo "$MSG_ERR_EXIT$PY_ERR"
            read -k 1 "?Appuyez sur une touche pour quitter..."
            exit $PY_ERR
        fi
        exit 0
    fi
fi

# 5. Recherche du binaire Python système
echo ""
echo "$MSG_CHK_PY"
SYSTEM_PY=$(find_python)

if [ -z "$SYSTEM_PY" ]; then
    echo ""
    echo "$MSG_REQ_PY"
    read -k 1 "?Appuyez sur une touche pour quitter..."
    exit 1
fi

# 6. Création et configuration du Virtualenv local
echo ""
echo "$MSG_SETUP_MOD"

if [ ! -d "$VENV_DIR" ]; then
    "$SYSTEM_PY" -m venv "$VENV_DIR"
fi

PY_BIN="$VENV_DIR/bin/python"

echo ""
echo "$MSG_UP_PIP"
"$PY_BIN" -m pip install --upgrade pip >/dev/null 2>&1
echo "OK."

echo ""
echo "$MSG_INS_COMP"
"$PY_BIN" -m pip install "${MODULES[@]}" >/dev/null 2>&1
echo "OK."

echo ""
echo "$MSG_OPT_ENV"
"$PY_BIN" -m pip install anynet --no-deps >/dev/null 2>&1
echo "OK."

touch "$FLAG_FILE"

# 7. Lancement final
if [ "$ADVANCED_LOGS" = "True" ]; then
    echo ""
    echo "============================================================"
    echo "  $MSG_LAUNCH$SCRIPT_NAME"
    echo "============================================================"
    echo ""
    echo "$MSG_PY_EXE$PY_BIN"
    echo ""
else
    echo ""
    echo "$MSG_STARTING"
    echo "OK."
    echo ""
fi

"$PY_BIN" "$THIS_DIR/$SCRIPT_NAME" --id="$APP_NAME"
PY_ERR=$?

if [ $PY_ERR -ne 0 ]; then
    echo ""
    echo "$MSG_ERR_EXIT$PY_ERR"
    read -k 1 "?Appuyez sur une touche pour quitter..."
    exit $PY_ERR
fi

exit 0