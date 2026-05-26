@echo off
setlocal enableDelayedExpansion

:: Force UTF-8 encoding for seamless French accents display in Windows Terminal/CMD
chcp 65001 >nul

set "thisDir=%~dp0"
set "app_name=TriCoreDownloader"
set "script_name=run_TriCoreDownloader.py"
set "py_ver=3.12.10"
set "modules=PyQt6 requests urllib3 anyio pyopenssl multidict netifaces2 pyctr cryptography"
set "tried=0"
set "flag_file=!thisDir!.env_ok"

set "syspath=%SYSTEMROOT%\system32\"
set "pspath=%SYSTEMROOT%\system32\WindowsPowerShell\v1.0\powershell.exe"
set "curlpath=%SYSTEMROOT%\system32\curl.exe"

set "ADVANCED_LOGS=False"
set "CONFIG_FILE=%APPDATA%\TriCoreDownloader\config.json"
if exist "!CONFIG_FILE!" (
    "!pspath!" -NoProfile -Command "try{$j=Get-Content '!CONFIG_FILE!' -Raw|ConvertFrom-Json; if($j.advanced_logs -eq $true){exit 1}else{exit 0}}catch{exit 0}" >nul 2>&1
    if !ERRORLEVEL! EQU 1 set "ADVANCED_LOGS=True"
)

if "!ADVANCED_LOGS!"=="True" (
    echo [%DATE% %TIME%] ----- BOOTSTRAP START -----
)

set "arch=amd64"
if "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "arch=win32"

title Setup : !app_name!

set "OS_LOCALE="
for /f "tokens=3" %%a in ('reg query "HKCU\Control Panel\International" /v LocaleName 2^>nul') do set "OS_LOCALE=%%a"

if "!OS_LOCALE!"=="" (
    if "!ADVANCED_LOGS!"=="True" echo [%DATE% %TIME%] No language detected, defaulting to English.
    set "LANG_CODE=EN"
) else (
    set "LANG_CODE=EN"
    if /i "!OS_LOCALE:~0,2!"=="fr" set "LANG_CODE=FR"
)

if "!LANG_CODE!"=="FR" (
    set "MSG_FILE_MISSING=[ERREUR] Le fichier est introuvable :"
    set "MSG_ALREADY_RUNNING=[INFO] L'application est déjà en cours d'exécution."
    set "MSG_SHIFT_INFO=[INFO] Maintenez SHIFT enfoncé (3s) pour purger le cache et l'environnement."
    set "MSG_SHIFT_DETECTED=[!] Touche SHIFT détectée. Purge en cours..."
    set "MSG_PURGE_SUCCESS=[OK] Cache et configuration purgés avec succès."
    set "MSG_CHK_PY=[1/3] Vérification de l'installation de Python (3.12+)..."
    set "MSG_REQ_PY=[ERREUR] Python 3.12 ou supérieur est requis pour continuer."
    set "MSG_WARN_PY313=[ATTENTION] Version de Python > 3.12 détectée (!major!.!minor!). Si vous avez un problème avec cette version, veuillez essayer la 3.12."
    set "MSG_INSTALL_TITLE=INSTALLATION DE PYTHON"
    set "MSG_INSTALL_DESC=Python 3.12+ est requis pour exécuter ce programme."
    set "MSG_PROMPT_INSTALL=Voulez-vous l'installer maintenant ? [y/n]: "
    set "MSG_FIND_PY=[2/3] Recherche de la dernière version de Python 3..."
    set "MSG_GATHERING=[INFO] Collecte des données depuis https://www.python.org/downloads/windows/..."
    set "MSG_PARSING=[INFO] Analyse de la dernière version..."
    set "MSG_PY_FOUND=[INFO] Version trouvée - Téléchargement en cours :"
    set "MSG_PY_NO_WEB=[ATTENTION] Impossible de trouver la dernière version via le web. Utilisation de la version par défaut :"
    set "MSG_DL_FAIL=[ERREUR] Échec du téléchargement."
    set "MSG_INSTALLING=[INFO] Installation en cours..."
    set "MSG_SETUP_MOD=[3/3] Configuration des modules..."
    set "MSG_CLEAN_PIP=[INFO] Nettoyage des distributions corrompues..."
    set "MSG_UP_PIP=[INFO] Mise à jour de PIP..."
    set "MSG_INS_COMP=[INFO] Installation des composants principaux..."
    set "MSG_OPT_ENV=[INFO] Optimisation de l'environnement..."
    set "MSG_ERR_MOD=[ATTENTION] Une erreur est survenue lors de l'installation des modules."
    set "MSG_LAUNCH=[INFO] LANCEMENT :"
    set "MSG_PY_EXE=[INFO] Exécutable Python :"
    set "MSG_ERR_EXIT=[ERREUR] Le script Python s'est fermé avec le code :"
    set "MSG_STARTING=[INFO] Démarrage en cours..."
    set "MSG_LOG_HINT_OFF=[INFO] Logs avancés désactivés."
    set "MSG_LOG_HINT_ON=[INFO] Logs avancés activés."
) else (
    set "MSG_FILE_MISSING=[ERROR] File not found :"
    set "MSG_ALREADY_RUNNING=[INFO] Application is already running."
    set "MSG_SHIFT_INFO=[INFO] Hold down SHIFT (3s) to clear the cache and environment."
    set "MSG_SHIFT_DETECTED=[!] SHIFT key detected. Purging..."
    set "MSG_PURGE_SUCCESS=[OK] Cache and config purged successfully."
    set "MSG_CHK_PY=[1/3] Checking for Python (3.12+) installation..."
    set "MSG_REQ_PY=[ERROR] Python 3.12 or higher is required to continue."
    set "MSG_WARN_PY313=[WARNING] Python version > 3.12 detected (!major!.!minor!). If you experience issues with this version, please try 3.12."
    set "MSG_INSTALL_TITLE=PYTHON SETUP"
    set "MSG_INSTALL_DESC=Python 3.12+ is required to run this program."
    set "MSG_PROMPT_INSTALL=Install now? [y/n]: "
    set "MSG_FIND_PY=[2/3] Searching for the latest Python 3 version..."
    set "MSG_GATHERING=[INFO] Gathering info from https://www.python.org/downloads/windows/..."
    set "MSG_PARSING=[INFO] Parsing for latest version..."
    set "MSG_PY_FOUND=[INFO] Version found - Downloading :"
    set "MSG_PY_NO_WEB=[WARNING] Could not find latest version via web. Falling back to default :"
    set "MSG_DL_FAIL=[ERROR] Download failed."
    set "MSG_INSTALLING=[INFO] Installing..."
    set "MSG_SETUP_MOD=[3/3] Module setup..."
    set "MSG_CLEAN_PIP=[INFO] Cleaning corrupted distributions..."
    set "MSG_UP_PIP=[INFO] Updating PIP..."
    set "MSG_INS_COMP=[INFO] Installing main components..."
    set "MSG_OPT_ENV=[INFO] Environment optimization..."
    set "MSG_ERR_MOD=[WARNING] An error occurred while installing modules."
    set "MSG_LAUNCH=[INFO] LAUNCHING :"
    set "MSG_PY_EXE=[INFO] Python Executable :"
    set "MSG_ERR_EXIT=[ERROR] Python script exited with code :"
    set "MSG_STARTING=[INFO] Starting application..."
    set "MSG_LOG_HINT_OFF=[INFO] Advanced logs disabled."
    set "MSG_LOG_HINT_ON=[INFO] Advanced logs enabled."
)

if exist "!thisDir!!script_name!" goto skip_missing
echo !MSG_FILE_MISSING! !script_name!
pause
exit /b 1
:skip_missing

"!pspath!" -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%%--id=!app_name!%%' AND Name LIKE '%%python%%'\" -ErrorAction SilentlyContinue; if ($p) { exit 1 } else { exit 0 }" >nul 2>&1
if !ERRORLEVEL! EQU 1 (
    echo !MSG_ALREADY_RUNNING!
    "!syspath!ping.exe" -n 3 127.0.0.1 >nul
    exit /b
)
:skip_running

echo !MSG_SHIFT_INFO!
"!pspath!" -NoProfile -Command "Add-Type -AssemblyName System.Windows.Forms; $end=(Get-Date).AddSeconds(3); while((Get-Date) -lt $end){ if([System.Windows.Forms.Control]::ModifierKeys -match 'Shift'){exit 1}; Start-Sleep -Milliseconds 100 }; exit 0"
if !ERRORLEVEL! NEQ 1 (
    cls
    goto read_flag
)

echo.
echo !MSG_SHIFT_DETECTED!
if exist "!flag_file!" del /f /a /q "!flag_file!" >nul 2>&1
for /d /r "%thisDir%" %%d in (__pycache__) do if exist "%%d" rd /s /q "%%d" >nul 2>&1
echo !MSG_PURGE_SUCCESS!
"!syspath!ping.exe" -n 2 127.0.0.1 >nul
cls

:read_flag
if not exist "!flag_file!" goto checkpy

set "flag_data="
set /p flag_data= < "!flag_file!"
if "!flag_data!"=="" (
    del /f /a /q "!flag_file!" >nul 2>&1
    goto checkpy
)

for /f "tokens=1,* delims=|" %%A in ("!flag_data!") do (
    set "saved_pc=%%A"
    set "saved_py=%%B"
)
if not defined saved_py (
    del /f /a /q "!flag_file!" >nul 2>&1
    goto checkpy
)
if "!saved_py:~-1!"==" " set "saved_py=!saved_py:~0,-1!"

if "!saved_pc!" NEQ "%COMPUTERNAME%" (
    del /f /a /q "!flag_file!" >nul 2>&1
    goto checkpy
)

if not exist "!saved_py!" (
    del /f /a /q "!flag_file!" >nul 2>&1
    goto checkpy
)

goto runscript_fast

:checkpy
call :updatepath
echo !MSG_CHK_PY!
set "pypath="
set "pydir="

set "target_local_py=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "!target_local_py!" (
    call :checkpyversion "!target_local_py!"
    if defined pypath goto checkdeps
)

set "local_root=%LocalAppData%\Programs\Python"
if exist "!local_root!" (
    for /f "delims=" %%d in ('dir /b /ad "!local_root!\Python3*" 2^>nul') do (
        if exist "!local_root!\%%d\python.exe" (
            call :checkpyversion "!local_root!\%%d\python.exe"
            if defined pypath goto checkdeps
        )
    )
)

for /f "tokens=*" %%x in ('"!syspath!where.exe" python 2^>nul') do (
    call :checkpyversion "%%x"
    if defined pypath goto checkdeps
)

if !tried! lss 1 goto askinstall

echo.
echo !MSG_REQ_PY!
pause
exit /b 1

:checkpyversion
set "v_raw="
for /f "tokens=2" %%a in ('"%~1" -V 2^>^&1') do set "v_raw=%%a"
if not defined v_raw goto :EOF

for /f "tokens=1,2 delims=." %%i in ("!v_raw!") do (
    set "major=%%i"
    set "minor=%%j"
)

if "!major!"=="3" (
    if !minor! GEQ 12 (
        set "pypath=%~1"
        set "pydir=%~dp1"
        if !minor! GTR 12 (
            echo !MSG_WARN_PY313!
        )
    )
)
goto :EOF

:askinstall
echo.
echo ============================================================
echo   !MSG_INSTALL_TITLE!
echo ============================================================
echo.
echo !MSG_INSTALL_DESC!
echo.

:prompt_loop
set "menu="
set /p "menu=!MSG_PROMPT_INSTALL!"
if /i "!menu!"=="y" goto installpy
if /i "!menu!"=="yes" goto installpy
if /i "!menu!"=="o" goto installpy
if /i "!menu!"=="oui" goto installpy
if /i "!menu!"=="n" exit /b 0
if /i "!menu!"=="no" exit /b 0
if /i "!menu!"=="non" exit /b 0
goto prompt_loop

:installpy
set /a tried+=1
echo.
echo !MSG_FIND_PY!
echo.
echo !MSG_GATHERING!

"!pspath!" -NoProfile -Command "[System.Net.ServicePointManager]::ServerCertificateValidationCallback={$true}; [Net.ServicePointManager]::SecurityProtocol=@('Tls12','Tls13'); (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/downloads/windows/','%TEMP%\pyurl.txt')"
"!pspath!" -NoProfile -Command "$infile='%TEMP%\pyurl.txt';$outfile='%TEMP%\pyurl.temp';try{$input=New-Object System.IO.FileStream $infile,([IO.FileMode]::Open),([IO.FileAccess]::Read),([IO.FileShare]::Read);$output=New-Object System.IO.FileStream $outfile,([IO.FileMode]::Create),([IO.FileAccess]::Write),([IO.FileShare]::None);$gzipStream=New-Object System.IO.Compression.GzipStream $input,([IO.Compression.CompressionMode]::Decompress);$buffer=New-Object byte[](1024);while($true){$read=$gzipstream.Read($buffer,0,1024);if($read -le 0){break};$output.Write($buffer,0,$read)};$gzipStream.Close();$output.Close();$input.Close();Move-Item -Path $outfile -Destination $infile -Force}catch{}"

echo !MSG_PARSING!
set "latest_py="
pushd "%TEMP%"
for /f "tokens=9 delims=< " %%x in ('findstr /i /c:"Latest Python 3 Release" pyurl.txt 2^>nul') do (
    set "latest_py=%%x"
)
popd

if not "!latest_py!"=="" (
    set "py_ver=!latest_py!"
    echo !MSG_PY_FOUND! !py_ver!
) else (
    echo !MSG_PY_NO_WEB! !py_ver!
)
if exist "%TEMP%\pyurl.txt" del /f /q "%TEMP%\pyurl.txt" >nul 2>&1

echo.
set "url=https://www.python.org/ftp/python/!py_ver!/python-!py_ver!-!arch!.exe"
set "py_exe=%TEMP%\pyinstall.exe"

if exist "!curlpath!" ( 
    "!curlpath!" -skL -o "!py_exe!" "!url!" 
) else ( 
    "!pspath!" -NoProfile -Command "[System.Net.ServicePointManager]::ServerCertificateValidationCallback={$true}; [Net.ServicePointManager]::SecurityProtocol=@('Tls12','Tls13'); (New-Object System.Net.WebClient).DownloadFile('!url!','!py_exe!')" 
)

if not exist "!py_exe!" ( 
    echo !MSG_DL_FAIL!
    pause
    goto checkpy 
)

echo.
echo !MSG_INSTALLING!
pushd "%TEMP%"
pyinstall.exe /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_pip=1 Include_launcher=1
popd

del /f /q "!py_exe!" >nul 2>&1
"!syspath!ping.exe" -n 3 127.0.0.1 >nul
goto checkpy

:checkdeps
echo.
echo !MSG_SETUP_MOD!

echo.
echo !MSG_CLEAN_PIP!
"!pypath!" -c "import site, os, shutil; [shutil.rmtree(os.path.join(p, d), ignore_errors=True) for p in site.getsitepackages() + [site.getusersitepackages()] if os.path.exists(p) for d in os.listdir(p) if d.startswith('~')]" >nul 2>&1
echo OK.

echo.
echo !MSG_UP_PIP!
"!pypath!" -m pip install --upgrade pip --no-warn-script-location >nul 2>&1
echo OK.

echo.
echo !MSG_INS_COMP!
"!pypath!" -m pip install !modules! --no-warn-script-location >nul 2>&1
echo OK.

echo.
echo !MSG_OPT_ENV!
"!pypath!" -m pip install anynet --no-deps --no-warn-script-location >nul 2>&1
echo OK.

if !ERRORLEVEL! EQU 0 goto deps_ok
echo.
echo !MSG_ERR_MOD!
pause
goto runscript

:deps_ok
if exist "!flag_file!" attrib -h "!flag_file!" >nul 2>&1
echo %COMPUTERNAME%^|!pypath!> "!flag_file!"
attrib +h "!flag_file!"

:runscript
if "!ADVANCED_LOGS!"=="True" (
    echo.
    echo ============================================================
    echo   !MSG_LAUNCH! !script_name!
    echo ============================================================
    echo.
    echo !MSG_PY_EXE! !pypath!
    echo.
) else (
    echo.
    echo !MSG_STARTING!
    echo OK.
    echo.
)

"!pypath!" "!thisDir!!script_name!" --id=!app_name!
set "PY_ERR=!ERRORLEVEL!"

if !PY_ERR! EQU 0 goto end_runscript
echo.
echo !MSG_ERR_EXIT! !PY_ERR!
pause
exit /b

:end_runscript
goto cleanup

:runscript_fast
if "!ADVANCED_LOGS!"=="True" (
    echo [%DATE% %TIME%] Fast launching with cached path: !saved_py!
    echo.
) else (
    echo.
    echo !MSG_STARTING!
    echo OK.
    echo.
)

"!saved_py!" "!thisDir!!script_name!" --id=!app_name!
set "PY_ERR=!ERRORLEVEL!"

if !PY_ERR! EQU 0 goto end_runscript_fast
echo.
echo !MSG_ERR_EXIT! !PY_ERR!
pause
exit /b

:end_runscript_fast
goto cleanup

:updatepath
set "NEWPATH="
for /f "tokens=2*" %%i in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "NEWPATH=%%j"
for /f "tokens=2*" %%i in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do call :concat_path_safe "%%j"
goto apply_path

:concat_path_safe
if "!NEWPATH!"=="" goto set_first_path
set "NEWPATH=!NEWPATH!;%~1"
goto :EOF
:set_first_path
set "NEWPATH=%~1"
goto :EOF

:apply_path
if "!NEWPATH!"=="" goto :EOF
set "PATH=!NEWPATH!"
if defined pydir (
    set "PATH=!PATH!;!pydir!;!pydir!Scripts"
)
goto :EOF

:cleanup
set "thisDir="
set "app_name="
set "script_name="
set "py_ver="
set "modules="
set "tried="
set "flag_file="
set "syspath="
set "pspath="
set "curlpath="
set "ADVANCED_LOGS="
set "CONFIG_FILE="
set "arch="
set "OS_LOCALE="
set "LANG_CODE="
set "pypath="
set "pydir="
set "target_local_py="
set "local_root="
set "flag_data="
set "saved_pc="
set "saved_py="
set "menu="
set "py_exe="
set "url="
set "py_html="
set "latest_py="
set "PY_ERR="
exit /b