@echo off
setlocal
cd /d "%~dp0"
title ClipboardToSheets Setup

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
    set "PYW=pyw -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found.
        echo Install Python 3.10 or newer from https://www.python.org/downloads/
        echo Make sure Python is added to PATH, then run this file again.
        pause
        exit /b 1
    )
    set "PY=python"
    set "PYW=pythonw"
)

%PY% -m pip --version >nul 2>nul
if errorlevel 1 (
    %PY% -m ensurepip --upgrade
    if errorlevel 1 (
        echo Could not set up pip.
        pause
        exit /b 1
    )
)

echo Checking and installing requirements...
%PY% -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection and Python setup.
    pause
    exit /b 1
)

if not exist "credentials.json" (
    echo.
    echo Missing credentials.json.
    echo Place your Google service-account JSON key beside RUN.bat and rename it credentials.json.
    pause
    exit /b 1
)

start "" %PYW% "%~dp0clipboard_to_sheets.py"
if errorlevel 1 (
    echo Could not launch ClipboardToSheets.
    pause
    exit /b 1
)
exit /b 0
