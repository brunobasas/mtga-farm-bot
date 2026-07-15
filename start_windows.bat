@echo off
setlocal enabledelayedexpansion

rem One-click launcher for Windows. Creates a local .venv on first run,
rem installs requirements.txt, then starts ui.py. Later runs reuse the
rem venv and start instantly.

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "VENV_DIR=%ROOT_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
set "REQ_FILE=%ROOT_DIR%\requirements.txt"
set "MARKER=%VENV_DIR%\.requirements.installed"

rem --- Minimized relaunch (Explorer double-click): the parent window already
rem ran the setup below, so skip straight to starting the UI. This avoids
rem running the whole dependency check twice. ---
if /i "%~1"=="--minimized" goto start_ui

rem --- Locate a Python interpreter (py -3 is preferred on Windows) ---
set "PY_LAUNCHER="
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    set "PY_LAUNCHER=py -3"
) else (
    where python >nul 2>&1
    if !ERRORLEVEL!==0 (
        set "PY_LAUNCHER=python"
    )
)

if not defined PY_LAUNCHER (
    echo.
    echo [ERROR] Python 3 wurde nicht gefunden.
    echo Bitte Python 3.10 oder neuer installieren:
    echo     https://www.python.org/downloads/
    echo Beim Installer "Add Python to PATH" aktivieren.
    echo.
    pause
    exit /b 1
)

rem --- Create venv on first run ---
if not exist "%VENV_PYTHON%" (
    echo [INFO] Erstelle virtuelle Umgebung in "%VENV_DIR%" ...
    %PY_LAUNCHER% -m venv "%VENV_DIR%"
    if not exist "%VENV_PYTHON%" (
        echo [ERROR] Konnte .venv nicht anlegen.
        pause
        exit /b 1
    )
)

rem --- Install requirements only when requirements.txt content changed ---
rem The marker is a copy of the last installed requirements.txt; a byte
rem compare avoids both date-format pitfalls and pointless reinstalls
rem after git pull touches the file without changing it.
set "NEED_INSTALL=0"
if not exist "%MARKER%" set "NEED_INSTALL=1"
if exist "%MARKER%" (
    fc /b "%REQ_FILE%" "%MARKER%" >nul 2>&1
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" (
    echo [INFO] Installiere Abhaengigkeiten aus requirements.txt ...
    "%VENV_PYTHON%" -m pip install --upgrade pip
    "%VENV_PYTHON%" -m pip install -r "%REQ_FILE%"
    if errorlevel 1 (
        echo [ERROR] pip install ist fehlgeschlagen.
        pause
        exit /b 1
    )
    copy /y "%REQ_FILE%" "%MARKER%" >nul
) else (
    echo [INFO] Dependencies unchanged - starting directly.
)

rem --- Minimize Explorer-style cmd /c launches after setup succeeds. ---
rem Setup ran visibly in this window; relaunch minimized (which skips setup via
rem the guard above) so the console does not sit in the foreground. Direct cmd
rem runs stay attached; pass --foreground to keep the visible window and the
rem real process exit code (e.g. from PowerShell or automation).
if /i not "%~1"=="--foreground" (
    echo(!cmdcmdline! | findstr /i /c:"%~f0" >nul
    if !ERRORLEVEL!==0 (
        start "" /min "%ComSpec%" /d /c call "%~f0" --minimized
        exit /b 0
    )
)

rem --- Start the UI ---
:start_ui
cd /d "%ROOT_DIR%"
"%VENV_PYTHON%" "%ROOT_DIR%\ui.py"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [WARN] ui.py endete mit Code %RC%.
    pause
)
exit /b %RC%
