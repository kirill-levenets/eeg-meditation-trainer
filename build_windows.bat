@echo off
REM ============================================================
REM  EEG Meditation Trainer - Windows Build Script
REM  Run this on a Windows machine with Python 3.10-3.12
REM ============================================================

echo === EEG Meditation Trainer - Windows Build ===
echo.

REM Check Python
python --version 2>NUL
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10-3.12 from python.org
    pause
    exit /b 1
)

REM Clean previous builds
echo Cleaning previous builds...
if exist "build" rd /s /q "build"
if exist "dist" rd /s /q "dist"

REM Create virtual environment if needed
if not exist "build_venv" (
    echo Creating virtual environment...
    python -m venv build_venv
)

echo Activating virtual environment...
call build_venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements_windows.txt

echo.
echo === Building executable ===
echo.
python -m PyInstaller eeg_meditation.spec --noconfirm

if errorlevel 1 (
    echo.
    echo BUILD FAILED - check errors above
    pause
    exit /b 1
)

echo.
echo === Build complete! ===
echo Output: dist\EEG_Meditation_Trainer\EEG_Meditation_Trainer.exe
echo.
echo IMPORTANT: Run the EXE from the 'dist\EEG_Meditation_Trainer' folder.
echo To distribute: zip the entire dist\EEG_Meditation_Trainer folder.
pause
