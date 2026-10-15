#!/usr/bin/env bash

THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$THIS_DIR"

APP_NAME="TriCoreDownloader"
SCRIPT_NAME="run_TriCoreDownloader.py"
VENV_DIR="$THIS_DIR/.venv"
FLAG_FILE="$THIS_DIR/.env_ok"
MODULES=(PyQt6 requests urllib3 certifi netifaces2 pyctr cryptography py7zr darkdetect)

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/TriCoreDownloader"
CONFIG_FILE="$CONFIG_DIR/config.json"

ADVANCED_LOGS="False"
if [ -f "$CONFIG_FILE" ]; then
    if grep -Eq '"advanced_logs"[[:space:]]*:[[:space:]]*true' "$CONFIG_FILE" 2>/dev/null; then
        ADVANCED_LOGS="True"
    fi
fi

OS_LOCALE="${LC_ALL:-${LC_MESSAGES:-${LANG:-EN}}}"
if [ "$OS_LOCALE" = "EN" ] && command -v locale >/dev/null 2>&1; then
    OS_LOCALE="$(locale | grep -i LANG= | cut -d= -f2)"
fi

OS_LOCALE_LOWER=$(echo "$OS_LOCALE" | tr '[:upper:]' '[:lower:]')
if [[ "$OS_LOCALE_LOWER" == fr* ]]; then
    LANG_CODE="FR"
else
    LANG_CODE="EN"
fi

if [ "$LANG_CODE" = "FR" ]; then
    MSG_FILE_MISSING="[ERREUR] Le fichier est introuvable :"
    MSG_ALREADY_RUNNING="[INFO] L'application est déjà en cours d'exécution."
    MSG_PURGE_HINT="[INFO] Appuyez sur la touche [P] dans les 3 secondes pour purger le cache et l'environnement."
    MSG_PURGE_DETECTED="[!] Touche de purge détectée. Nettoyage en cours..."
    MSG_PURGE_SUCCESS="[OK] Cache et environnement purgés avec succès."
    MSG_CHK_PY="[1/2] Vérification de l'installation de Python (3.12+)..."
    MSG_REQ_PY="[ERREUR] Python 3.12 ou supérieur est requis."
    MSG_SETUP_MOD="[2/2] Configuration de l'environnement et des modules..."
    MSG_UP_PIP="[INFO] Installation / Mise à jour de PIP..."
    MSG_INS_COMP="[INFO] Installation des composants principaux..."
    MSG_OPT_ENV="[INFO] Optimisation de l'environnement..."
    MSG_ERR_MOD="[ERREUR] Échec de l'installation des modules Python."
    MSG_LAUNCH="[INFO] LANCEMENT :"
    MSG_PY_EXE="[INFO] Exécutable Python :"
    MSG_ERR_EXIT="[ERREUR] Le script Python s'est fermé avec le code :"
    MSG_STARTING="[INFO] Démarrage en cours..."
    MSG_PRESS_KEY="Appuyez sur une touche pour quitter..."
else
    MSG_FILE_MISSING="[ERROR] File not found :"
    MSG_ALREADY_RUNNING="[INFO] Application is already running."
    MSG_PURGE_HINT="[INFO] Press [P] key within 3 seconds to purge cache and environment."
    MSG_PURGE_DETECTED="[!] Purge key detected. Cleaning up..."
    MSG_PURGE_SUCCESS="[OK] Cache and environment purged successfully."
    MSG_CHK_PY="[1/2] Checking for Python (3.12+) installation..."
    MSG_REQ_PY="[ERROR] Python 3.12 or higher is required."
    MSG_SETUP_MOD="[2/2] Setting up environment and modules..."
    MSG_UP_PIP="[INFO] Installing / Updating PIP..."
    MSG_INS_COMP="[INFO] Installing main components..."
    MSG_OPT_ENV="[INFO] Environment optimization..."
    MSG_ERR_MOD="[ERROR] Failed to install Python modules."
    MSG_LAUNCH="[INFO] LAUNCHING :"
    MSG_PY_EXE="[INFO] Python Executable :"
    MSG_ERR_EXIT="[ERROR] Python script exited with code :"
    MSG_STARTING="[INFO] Starting application..."
    MSG_PRESS_KEY="Press any key to exit..."
fi

if [ ! -f "$THIS_DIR/$SCRIPT_NAME" ]; then
    echo "$MSG_FILE_MISSING $SCRIPT_NAME"
    read -r -n 1 -s -p "$MSG_PRESS_KEY"
    echo ""
    exit 1
fi

if pgrep -f "$SCRIPT_NAME --id=$APP_NAME" >/dev/null 2>&1; then
    echo "$MSG_ALREADY_RUNNING"
    sleep 2
    exit 0
fi

echo "$MSG_PURGE_HINT"
KEY=""
if read -r -t 3 -n 1 KEY 2>/dev/null; then
    echo ""
    if [[ "$KEY" == [pP] ]]; then
        echo "$MSG_PURGE_DETECTED"
        rm -rf "$VENV_DIR" "$FLAG_FILE"
        find "$THIS_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
        echo "$MSG_PURGE_SUCCESS"
        sleep 1
    fi
else
    echo ""
fi

if [ "$ADVANCED_LOGS" = "False" ]; then
    clear
fi

find_python() {
    for cmd in python3.12 python312 python3.13 python3.14 python3; do
        if command -v "$cmd" >/dev/null 2>&1; then
            if "$cmd" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
                command -v "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

if [ -f "$FLAG_FILE" ]; then
    CACHED_PY=""
    if [ -x "$VENV_DIR/bin/python" ]; then
        CACHED_PY="$VENV_DIR/bin/python"
    else
        SAVED_PATH="$(cat "$FLAG_FILE" 2>/dev/null)"
        if [ -n "$SAVED_PATH" ] && [ -x "$SAVED_PATH" ]; then
            CACHED_PY="$SAVED_PATH"
        fi
    fi

    if [ -n "$CACHED_PY" ]; then
        if [ "$ADVANCED_LOGS" = "True" ]; then
            echo "[$(date)] Fast launching with cached Python: $CACHED_PY"
            echo ""
        else
            echo ""
            echo "$MSG_STARTING"
            echo "OK."
            echo ""
        fi

        "$CACHED_PY" "$THIS_DIR/$SCRIPT_NAME" --id="$APP_NAME"
        PY_ERR=$?

        if [ $PY_ERR -ne 0 ]; then
            rm -f "$FLAG_FILE"
            echo ""
            echo "$MSG_ERR_EXIT $PY_ERR"
            read -r -n 1 -s -p "$MSG_PRESS_KEY"
            echo ""
            exit $PY_ERR
        fi
        exit 0
    fi
fi

echo ""
echo "$MSG_CHK_PY"
SYSTEM_PY=$(find_python)

if [ -z "$SYSTEM_PY" ]; then
    echo ""
    echo "$MSG_REQ_PY"
    read -r -n 1 -s -p "$MSG_PRESS_KEY"
    echo ""
    exit 1
fi

echo ""
echo "$MSG_SETUP_MOD"

USE_VENV=0
if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
    USE_VENV=1
else
    rm -rf "$VENV_DIR"
    if "$SYSTEM_PY" -m venv "$VENV_DIR" >/dev/null 2>&1 && "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
        USE_VENV=1
    else
        rm -rf "$VENV_DIR"
    fi
fi

DEPS_OK=1

if [ $USE_VENV -eq 1 ]; then
    PY_BIN="$VENV_DIR/bin/python"

    echo ""
    echo "$MSG_UP_PIP"
    "$PY_BIN" -m pip install --upgrade pip --disable-pip-version-check --quiet || DEPS_OK=0
    echo "OK."

    echo ""
    echo "$MSG_INS_COMP"
    "$PY_BIN" -m pip install --prefer-binary "${MODULES[@]}" --disable-pip-version-check || DEPS_OK=0
    echo "OK."

    echo ""
    echo "$MSG_OPT_ENV"
    "$PY_BIN" -m pip install --prefer-binary anynet --no-deps --disable-pip-version-check --quiet || DEPS_OK=0
    echo "OK."
else
    PY_BIN="$SYSTEM_PY"
    PIP_EXTRA_FLAGS=(--user)
    if "$PY_BIN" -m pip help install 2>/dev/null | grep -q -- "--break-system-packages"; then
        PIP_EXTRA_FLAGS+=(--break-system-packages)
    fi

    echo ""
    echo "$MSG_UP_PIP"
    if ! "$PY_BIN" -m pip --version >/dev/null 2>&1; then
        if command -v curl >/dev/null 2>&1; then
            curl -fsSL https://bootstrap.pypa.io/get-pip.py -o get-pip.py
        elif command -v wget >/dev/null 2>&1; then
            wget -q https://bootstrap.pypa.io/get-pip.py -O get-pip.py
        fi
        if [ -f "get-pip.py" ]; then
            "$PY_BIN" get-pip.py --user --break-system-packages --quiet 2>/dev/null || "$PY_BIN" get-pip.py --user --quiet || DEPS_OK=0
            rm -f get-pip.py
        else
            DEPS_OK=0
        fi
    else
        "$PY_BIN" -m pip install "${PIP_EXTRA_FLAGS[@]}" --upgrade pip --disable-pip-version-check --quiet || DEPS_OK=0
    fi
    echo "OK."

    echo ""
    echo "$MSG_INS_COMP"
    "$PY_BIN" -m pip install --prefer-binary "${PIP_EXTRA_FLAGS[@]}" "${MODULES[@]}" --disable-pip-version-check || DEPS_OK=0
    echo "OK."

    echo ""
    echo "$MSG_OPT_ENV"
    "$PY_BIN" -m pip install --prefer-binary "${PIP_EXTRA_FLAGS[@]}" anynet --no-deps --disable-pip-version-check --quiet || DEPS_OK=0
    echo "OK."
fi

if ! "$PY_BIN" -c "import PyQt6, requests, cryptography, pyctr" >/dev/null 2>&1; then
    DEPS_OK=0
fi

if [ $DEPS_OK -eq 1 ]; then
    echo "$PY_BIN" > "$FLAG_FILE"
else
    rm -f "$FLAG_FILE"
    echo ""
    echo "$MSG_ERR_MOD"
    read -r -n 1 -s -p "$MSG_PRESS_KEY"
    echo ""
    exit 1
fi

if [ "$ADVANCED_LOGS" = "True" ]; then
    echo ""
    echo "============================================================"
    echo "  $MSG_LAUNCH $SCRIPT_NAME"
    echo "============================================================"
    echo ""
    echo "$MSG_PY_EXE $PY_BIN"
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
    rm -f "$FLAG_FILE"
    echo ""
    echo "$MSG_ERR_EXIT $PY_ERR"
    read -r -n 1 -s -p "$MSG_PRESS_KEY"
    echo ""
    exit $PY_ERR
fi

exit 0
