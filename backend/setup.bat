@echo off
:: ═══════════════════════════════════════════════════════
::  AGROTECH BACKEND SETUP SCRIPT
::  Double-click this file ONE TIME to set everything up.
::  After setup, use start.bat to run the backend.
:: ═══════════════════════════════════════════════════════

echo.
echo ====================================================
echo   AgroTech Backend Setup
echo   This will take 5-10 minutes (downloading packages)
echo ====================================================
echo.

:: Step 1 - Create virtual environment
echo [1/4] Creating virtual environment...
py -3.11 -m venv venv
echo       Done!

:: Step 2 - Activate it
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat

:: Step 3 - Upgrade pip (the package installer)
echo [3/4] Upgrading pip...
python -m pip install --upgrade pip

:: Step 4 - Install all required packages
echo [4/4] Installing packages (this takes a few minutes)...
pip install fastapi==0.111.0
pip install uvicorn==0.29.0
pip install python-multipart==0.0.9
pip install sqlalchemy==2.0.30
pip install pillow==10.3.0
pip install numpy==1.26.4
pip install reportlab==4.2.0
pip install tensorflow==2.16.1

echo.
echo ====================================================
echo   SETUP COMPLETE!
echo.
echo   Now run start.bat to start the backend server.
echo ====================================================
echo.
pause
