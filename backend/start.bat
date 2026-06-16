@echo off
:: ═══════════════════════════════════════════════════════
::  AGROTECH BACKEND STARTER
::  Double-click this every time you want to run the backend.
::  Keep this window open while using the app.
:: ═══════════════════════════════════════════════════════

echo.
echo ====================================================
echo   AgroTech Backend Starting...
echo ====================================================
echo.
echo   API will be available at: http://localhost:8000
echo   API docs available at:    http://localhost:8000/docs
echo.
echo   Keep this window OPEN while using the app.
echo   To stop: press Ctrl + C
echo.
echo ====================================================
echo.

:: Activate the virtual environment
call venv\Scripts\activate.bat

:: Check that model files exist
if not exist "plant_model.h5" (
    echo ERROR: plant_model.h5 not found!
    echo Please copy plant_model.h5 into this backend folder.
    pause
    exit
)

if not exist "class_labels.pkl" (
    echo ERROR: class_labels.pkl not found!
    echo Please copy class_labels.pkl into this backend folder.
    pause
    exit
)

:: Start the backend server
:: --reload means: restart automatically when you edit main.py
:: --port 8000 means: listen on port 8000
uvicorn main:app --reload --port 8000
