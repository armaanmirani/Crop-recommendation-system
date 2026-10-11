@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Preparing Terra crop recommendation app...
rem Use a dedicated environment so an existing incompatible .venv is preserved.
set "TERRA_PYTHON=py -3.12"
%TERRA_PYTHON% -c "import sys,platform; sys.exit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 and platform.machine().upper() in ('AMD64','X86_64') else 1)" >nul 2>&1
if not errorlevel 1 goto python_ready
set "TERRA_PYTHON=python"
%TERRA_PYTHON% -c "import sys,platform; sys.exit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 and platform.machine().upper() in ('AMD64','X86_64') else 1)" >nul 2>&1
if errorlevel 1 goto missing_python
:python_ready
if exist ".venv-windows\Scripts\python.exe" goto check_environment
%TERRA_PYTHON% -m venv .venv-windows
if errorlevel 1 goto failed
:check_environment
.venv-windows\Scripts\python.exe -c "import sys,platform; sys.exit(0 if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 and platform.machine().upper() in ('AMD64','X86_64') else 1)" >nul 2>&1
if errorlevel 1 goto incompatible_environment
.venv-windows\Scripts\python.exe -m pip install --disable-pip-version-check --upgrade pip
if errorlevel 1 goto failed
rem Never fall back to compiling pandas or other native dependencies.
.venv-windows\Scripts\python.exe -m pip install --disable-pip-version-check --only-binary=:all: -r requirements.lock.txt
if errorlevel 1 goto failed
if not exist "models\crop_models.joblib" (
    .venv-windows\Scripts\python.exe train.py
    if errorlevel 1 goto failed
)
echo Starting Terra. Keep this window open while using the app.
.venv-windows\Scripts\python.exe run_local.py
if errorlevel 1 goto failed
exit /b 0
:missing_python
echo.
echo Install Python 3.12 for Windows 64-bit, then run this file again.
echo Download: https://www.python.org/downloads/release/python-31210/
echo Choose "Windows installer (64-bit)" and keep the Python launcher enabled.
echo Your other Python versions can stay installed.
pause
exit /b 1
:incompatible_environment
echo.
echo The .venv-windows folder uses an incompatible Python.
echo Rename that folder to preserve it, then run this launcher again.
pause
exit /b 1
:failed
echo.
echo Terra could not start. Check the error above. Internet access is needed for installation.
pause
exit /b 1
