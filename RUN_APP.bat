@echo off
setlocal
cd /d "%~dp0"
echo Preparing Terra crop recommendation app...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.lock.txt
if errorlevel 1 goto failed
if not exist "models\crop_models.joblib" (
    .venv\Scripts\python.exe train.py
    if errorlevel 1 goto failed
)
echo Starting Terra. Keep this window open while using the app.
.venv\Scripts\python.exe run_local.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Terra could not start. Check the error above and confirm Python 3.12 is installed.
pause
exit /b 1
