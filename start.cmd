@echo off
setlocal
title Lilac-Observer - A-share research
cd /d "%~dp0"
if errorlevel 1 goto fail
echo Starting Lilac-Observer...
where.exe codex >nul 2>&1
if errorlevel 1 (
    for /f "usebackq delims=" %%D in (`powershell.exe -NoProfile -NonInteractive -Command "(Get-AppxPackage -Name OpenAI.Codex).InstallLocation"`) do (
        if exist "%%D\app\resources\codex.exe" set "PATH=%%D\app\resources;%PATH%"
    )
)
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import xlrd" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 echo Live CSI weight updates unavailable. Using available financial snapshots.
)
".venv\Scripts\python.exe" app.py --open %*
if errorlevel 1 goto fail
pause
exit /b 0
:fail
echo Could not start Lilac-Observer. Check the error above.
pause
exit /b 1
