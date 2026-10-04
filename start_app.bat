@echo off
chcp 65001 >nul
title Huppa OpenCart Studio
cd /d "%~dp0"

echo ======================================================================
echo              🛍️ HUPPA OPENCART STUDIO — ЗАПУСК
echo ======================================================================
echo.

:: 1. Check if Python is installed on the system
set "PY_CMD="
python --version >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    ) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%PATH%"
    )
)

:: If Python is still not found, download and install it automatically!
if not defined PY_CMD (
    echo [1/3] Python не знайдено на комп'ютері.
    echo       Завантажуємо офіційний Python автоматично, зачекайте...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object System.Net.WebClient).DownloadFile('https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe', '$env:TEMP\python_installer.exe')"
    
    echo [2/3] Автоматичне встановлення Python (це займе близько 1 хвилини)...
    start /wait "" "%TEMP%\python_installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    del /f /q "%TEMP%\python_installer.exe" >nul 2>&1

    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
    ) else (
        python --version >nul 2>&1 && set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [ПОМИЛКА] Не вдалося автоматично налаштувати Python.
    echo Будь ласка, завантажте його вручну з: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 2. Check and initialize Virtual Environment
if not exist "venv\" (
    echo [1/2] Створення локального середовища програми (venv)...
    "%PY_CMD%" -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ПОМИЛКА] Не вдалося створити віртуальне оточення.
        pause
        exit /b 1
    )
    echo [2/2] Встановлення необхідних бібліотек (лише при першому запуску)...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip --quiet
    pip install -r requirements.txt --quiet
    if %ERRORLEVEL% NEQ 0 (
        echo [ПОМИЛКА] Помилка встановлення бібліотек. Перевірте з'єднання з інтернетом.
        pause
        exit /b 1
    )
) else (
    call venv\Scripts\activate.bat
)

:: 3. Launch Streamlit Dashboard
echo.
echo ======================================================================
echo  🚀 Запуск Huppa Studio... Вікно відкриється у вашому браузері!
echo ======================================================================
echo.
streamlit run app.py --server.headless=false
pause
