@echo off
title Huppa OpenCart Studio
cd /d "%~dp0"

echo ======================================================================
echo              HUPPA OPENCART STUDIO - START
echo ======================================================================
echo.

:: 1. Search for Python
set PY_CMD=

python --version >nul 2>&1
if not errorlevel 1 (
    set PY_CMD=python
    goto :PYTHON_READY
)

py -3 --version >nul 2>&1
if not errorlevel 1 (
    set PY_CMD=py -3
    goto :PYTHON_READY
)

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :PYTHON_READY
)

if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    goto :PYTHON_READY
)

if exist "C:\Python311\python.exe" (
    set "PY_CMD=C:\Python311\python.exe"
    goto :PYTHON_READY
)

if exist "C:\Python312\python.exe" (
    set "PY_CMD=C:\Python312\python.exe"
    goto :PYTHON_READY
)

if exist "%USERPROFILE%\miniconda3\python.exe" (
    set "PY_CMD=%USERPROFILE%\miniconda3\python.exe"
    goto :PYTHON_READY
)

if exist "%USERPROFILE%\anaconda3\python.exe" (
    set "PY_CMD=%USERPROFILE%\anaconda3\python.exe"
    goto :PYTHON_READY
)

:: 2. Auto-download and install Python
echo [1/3] Python is not installed on this PC.
echo       Downloading official Python 3.11 installer, please wait...

powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe' -OutFile '%TEMP%\py_installer.exe' -UseBasicParsing"

if not exist "%TEMP%\py_installer.exe" (
    echo.
    echo [ERROR] Failed to download Python. Check your internet connection.
    echo Or install Python manually from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [2/3] Installing Python (approx. 1-2 minutes)...
start /wait "" "%TEMP%\py_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
del /f /q "%TEMP%\py_installer.exe" >nul 2>&1

:: Refresh environment path
set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"

if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    goto :PYTHON_READY
)

python --version >nul 2>&1
if not errorlevel 1 (
    set PY_CMD=python
    goto :PYTHON_READY
)

echo.
echo [ERROR] Python installation finished, but python.exe was not detected.
echo Please restart your PC or install Python from https://www.python.org/downloads/
pause
exit /b 1

:PYTHON_READY
echo [OK] Using Python: %PY_CMD%

:: 3. Setup Virtual Environment
if exist "venv\Scripts\python.exe" goto :VENV_READY

echo.
echo [1/2] Creating local environment (venv)...
"%PY_CMD%" -m venv venv
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to create virtual environment.
    pause
    exit /b 1
)

echo [2/2] Installing required libraries (first launch only)...
call "venv\Scripts\activate.bat"
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install packages. Check internet connection.
    pause
    exit /b 1
)
echo [OK] Environment setup complete!

:VENV_READY
call "venv\Scripts\activate.bat"

echo.
echo ======================================================================
echo  Launching Huppa Studio... Your browser will open shortly!
echo ======================================================================
echo.

streamlit run app.py --server.headless=false
if errorlevel 1 (
    echo.
    echo Application stopped.
    pause
)
