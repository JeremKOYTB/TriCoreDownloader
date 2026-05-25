@echo off
setlocal enableDelayedExpansion

:: Force UTF-8 encoding configuration to support dynamic native accents handling
chcp 65001 >nul

set "targetDir=%APPDATA%\TriCoreDownloader"
set "pspath=%SYSTEMROOT%\system32\WindowsPowerShell\v1.0\powershell.exe"

set "OS_LOCALE="
for /f "tokens=3" %%a in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do set "OS_LOCALE=%%a"

set "LANG_CODE=EN"
if defined OS_LOCALE (
    if /i "!OS_LOCALE:~0,2!"=="fr" set "LANG_CODE=FR"
)

if "!LANG_CODE!"=="FR" (
    set "MSG_TITLE=REINITIALISATION COMPLETE DES DONNEES (APPDATA)"
    set "MSG_INTRO=NOTE : Ce script sert uniquement si l'application rencontre un souci, n'arrive pas à se lancer ou s'il est impossible d'effacer la sauvegarde."
    set "MSG_DESC=Ce script va supprimer INTEGRALEMENT le dossier de configuration et de sauvegarde :"
    set "MSG_WARN=ATTENTION : Cela va remettre l'application dans son état d'origine sans sauvegarde"
    set "MSG_IMPORTANT=IMPORTANT : Assurez-vous que TriCoreDownloader est complètement fermé avant de continuer."
    set "MSG_NOT_FOUND=[INFO] Le dossier n'existe pas ou a déjà été supprimé."
    set "MSG_CONFIRM=Voulez-vous vraiment supprimer ce dossier et tout son contenu ? (O/N) : "
    set "MSG_CANCELLED=Opération annulée. Rien n'a été modifié."
    set "MSG_DELETING=Suppression du dossier en cours..."
    set "MSG_SUCCESS=[OK] Le dossier AppData a été supprimé avec succès."
    set "MSG_ERROR=[ERREUR] Impossible de supprimer le dossier, certains fichiers restent verrouillés."
    set "MSG_NEED_ADMIN=[INFO] Droits administrateurs requis pour forcer la suppression du dossier verrouillé..."
) else (
    set "MSG_TITLE=COMPLETE DATA RESET (APPDATA)"
    set "MSG_INTRO=NOTE: This script is strictly intended for use if the application encounters an issue, fails to launch, or if it is impossible to delete the save data."
    set "MSG_DESC=This script will COMPLETELY delete the data and configuration folder:"
    set "MSG_WARN=WARNING: This will reset the application to its original state without any save data"
    set "MSG_IMPORTANT=IMPORTANT: Make sure TriCoreDownloader is completely closed before continuing."
    set "MSG_NOT_FOUND=[INFO] The directory does not exist or has already been deleted."
    set "MSG_CONFIRM=Are you absolutely sure you want to delete this folder and all its contents? (Y/N) : "
    set "MSG_CANCELLED=Operation cancelled. Nothing was changed."
    set "MSG_DELETING=Deleting directory..."
    set "MSG_SUCCESS=[OK] The AppData directory has been successfully deleted."
    set "MSG_ERROR=[ERROR] Failed to delete the directory, some files remain locked."
    set "MSG_NEED_ADMIN=[INFO] Administrator privileges required to force deletion of the locked folder..."
)

if "%~1"=="--admin-run" goto execution_delete

echo.
echo ============================================================
echo   !MSG_TITLE!
echo ============================================================
echo.
echo !MSG_INTRO!
echo.
echo !MSG_DESC!
echo   [Path] : "!targetDir!"
echo.
echo !MSG_WARN!
echo !MSG_IMPORTANT!
echo.

if not exist "!targetDir!" (
    echo !MSG_NOT_FOUND!
    goto end
)

set /p confirm="!MSG_CONFIRM!"

set "isValidInput=0"
if /i "!confirm!"=="O" set "isValidInput=1"
if /i "!confirm!"=="Y" set "isValidInput=1"

if "!isValidInput!"=="0" (
    echo.
    echo !MSG_CANCELLED!
    goto end
)

:execution_delete
if "%~1"=="--admin-run" (
    echo.
    echo ============================================================
    echo   !MSG_TITLE! [ADMIN]
    echo ============================================================
)

echo.
echo !MSG_DELETING!

if exist "!targetDir!" rmdir /s /q "!targetDir!"

if not exist "!targetDir!" (
    echo.
    echo !MSG_SUCCESS!
    goto end
)

if "%~1" NEQ "--admin-run" (
    echo.
    echo !MSG_NEED_ADMIN!
    "!pspath!" -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '--admin-run' -Verb RunAs"
    exit /b
)

echo.
echo !MSG_ERROR!

:end
set "targetDir="
set "pspath="
set "OS_LOCALE="
set "LANG_CODE="
set "confirm="
set "isValidInput="
echo.
pause