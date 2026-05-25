@echo off
setlocal enableDelayedExpansion

:: Force UTF-8 encoding configuration to support dynamic native accents handling
chcp 65001 >nul

set "thisDir=%~dp0"
set "count=0"
set "deleted=0"
set "failed=0"

:: Architecture and registry language analysis matrix
set "OS_LOCALE="
for /f "tokens=3" %%a in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do set "OS_LOCALE=%%a"

set "LANG_CODE=EN"
if defined OS_LOCALE (
    if /i "!OS_LOCALE:~0,2!"=="fr" set "LANG_CODE=FR"
)

if "!LANG_CODE!"=="FR" (
    set "MSG_TITLE=NETTOYAGE DES DOSSIERS __pycache__"
    set "MSG_DESC=Ce script va supprimer tous les dossiers '__pycache__' dans ce dossier et ses sous-dossiers."
    set "MSG_USE_CASE=A utiliser en cas de problème avec le cache Python ou simplement pour garder un projet propre."
    set "MSG_IMPORTANT=IMPORTANT : Veuillez fermer toutes les fenêtres Python (scripts, interpréteurs, IDE) avant de continuer."
    set "MSG_SEARCHING=Recherche en cours..."
    set "MSG_FOUND=Trouvé :"
    set "MSG_NOT_FOUND=Aucun dossier trouvé."
    set "MSG_TOTAL=Nombre total trouvé :"
    set "MSG_CONFIRM=Confirmer la suppression ? (O/N) : "
    set "MSG_CANCELLED=Opération annulée."
    set "MSG_DELETING=Suppression en cours..."
    set "MSG_DELETE_ITEM=Suppression de :"
    set "MSG_ERR_DELETE=[ERREUR] Impossible de supprimer :"
    set "MSG_SUMMARY=Résumé :"
    set "MSG_DELETED=Supprimés :"
    set "MSG_FAILED_COUNT=Échecs     :"
) else (
    set "MSG_TITLE=CLEANING __pycache__ DIRECTORIES"
    set "MSG_DESC=This script will delete all '__pycache__' folders in this directory and all subdirectories."
    set "MSG_USE_CASE=Use if you have issues with Python cache or simply to keep your project clean."
    set "MSG_IMPORTANT=IMPORTANT: Please close all Python windows (scripts, interpreters, IDEs) before continuing."
    set "MSG_SEARCHING=Searching..."
    set "MSG_FOUND=Found:"
    set "MSG_NOT_FOUND=No folders found."
    set "MSG_TOTAL=Total found:"
    set "MSG_CONFIRM=Confirm deletion? (Y/N) : "
    set "MSG_CANCELLED=Operation cancelled."
    set "MSG_DELETING=Deleting..."
    set "MSG_DELETE_ITEM=Deleting:"
    set "MSG_ERR_DELETE=[ERROR] Failed to delete:"
    set "MSG_SUMMARY=Summary:"
    set "MSG_DELETED=Deleted:"
    set "MSG_FAILED_COUNT=Failed :"
)

echo.
echo ============================================================
echo   !MSG_TITLE!
echo ============================================================
echo.
echo !MSG_DESC!
echo.
echo !MSG_USE_CASE!
echo.
echo !MSG_IMPORTANT!
echo.
echo !MSG_SEARCHING!
echo.

for /f "delims=" %%D in ('dir /ad /b /s __pycache__ 2^>nul') do (
    if exist "%%D" (
        echo !MSG_FOUND! %%D
        set /a count+=1
    )
)

if !count! EQU 0 (
    echo.
    echo !MSG_NOT_FOUND!
    goto end
)

echo.
echo !MSG_TOTAL! !count!
echo.

set /p confirm="!MSG_CONFIRM!"

set "isValidInput=0"
if /i "!confirm!"=="O" set "isValidInput=1"
if /i "!confirm!"=="Y" set "isValidInput=1"

if "!isValidInput!"=="0" (
    echo.
    echo !MSG_CANCELLED!
    goto end
)

echo.
echo !MSG_DELETING!
echo.

:: Iterating in reverse sorted order to handle recursive sub-tree deletion cleanly
for /f "delims=" %%D in ('dir /ad /b /s __pycache__ 2^>nul ^| sort /r') do (
    if exist "%%D" (
        echo !MSG_DELETE_ITEM! %%D
        rmdir /s /q "%%D"
        if exist "%%D" (
            echo !MSG_ERR_DELETE! %%D
            set /a failed+=1
        ) else (
            set /a deleted+=1
        )
    )
)

echo.
echo ============================================================
echo !MSG_SUMMARY!
echo   !MSG_DELETED! !deleted!
echo   !MSG_FAILED_COUNT! !failed!
echo ============================================================

:end
set "thisDir="
set "count="
set "deleted="
set "failed="
set "OS_LOCALE="
set "LANG_CODE="
set "confirm="
set "isValidInput="
pause