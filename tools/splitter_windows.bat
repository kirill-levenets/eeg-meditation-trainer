@echo off
REM ============================================================
REM  EEG Stream Splitter — Windows Setup & Run
REM  Installs pyserial, checks com0com, detects MindWave COM port,
REM  launches splitter with two virtual COM port outputs
REM ============================================================

echo === EEG Stream Splitter — Windows ===
echo.

REM --- Check Python ---
python --version 2>NUL
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    echo Make sure "Add to PATH" is checked during installation.
    pause
    exit /b 1
)

REM --- Install pyserial if needed ---
python -c "import serial" 2>NUL
if errorlevel 1 (
    echo Installing pyserial...
    pip install pyserial
    if errorlevel 1 (
        echo ERROR: Failed to install pyserial.
        pause
        exit /b 1
    )
    echo.
)

REM --- Check com0com ---
echo Checking for com0com virtual COM ports...
echo.

REM Look for com0com in registry
reg query "HKLM\SYSTEM\CurrentControlSet\Services\com0com" >NUL 2>&1
if errorlevel 1 (
    echo ============================================================
    echo  com0com is NOT installed.
    echo.
    echo  You need com0com to create virtual COM port pairs.
    echo.
    echo  1. Download from: https://com0com.sourceforge.net/
    echo  2. Run the installer
    echo  3. Open "com0com Setup" from Start Menu
    echo  4. Create two pairs:
    echo       Pair 1: COM10 ^<-^> COM11
    echo       Pair 2: COM12 ^<-^> COM13
    echo     ^(Click "Add Pair", type the port names, check
    echo      "enable buffer overrun" on both sides^)
    echo  5. Click "Apply" and close
    echo  6. Re-run this script
    echo ============================================================
    pause
    exit /b 1
)
echo com0com driver found.
echo.

REM --- Detect MindWave COM port ---
echo Scanning for MindWave COM port...
echo.

REM List all COM ports with their descriptions
set "MINDWAVE_PORT="
set "PORT_LIST="

REM Use WMIC to find Bluetooth serial ports
for /f "tokens=1,2 delims==" %%a in ('wmic path Win32_SerialPort get DeviceID^,Description /format:list 2^>NUL ^| findstr "="') do (
    if "%%a"=="Description" set "LAST_DESC=%%b"
    if "%%a"=="DeviceID" (
        set "LAST_PORT=%%b"
        call :CHECK_PORT
    )
)

REM Also check PnP entities for BT serial ports (some MindWave installs show here)
for /f "tokens=*" %%a in ('wmic path Win32_PnPEntity where "Name like '%%COM%%'" get Name /format:list 2^>NUL ^| findstr "COM"') do (
    echo   Found: %%a
)

echo.

if defined MINDWAVE_PORT (
    echo Auto-detected MindWave on %MINDWAVE_PORT%
    set /p "CONFIRM=Use %MINDWAVE_PORT%? [Y/n] "
    if /i "%CONFIRM%"=="n" set "MINDWAVE_PORT="
)

if not defined MINDWAVE_PORT (
    echo Available COM ports:
    echo.
    REM Show all COM ports from Device Manager
    for /f "tokens=*" %%a in ('wmic path Win32_SerialPort get DeviceID^,Description /format:list 2^>NUL ^| findstr "="') do (
        echo   %%a
    )
    for /f "tokens=*" %%a in ('mode 2^>NUL ^| findstr "COM"') do (
        echo   %%a
    )
    echo.
    set /p "MINDWAVE_PORT=Enter MindWave COM port (e.g. COM5): "
)

if not defined MINDWAVE_PORT (
    echo ERROR: No COM port specified.
    pause
    exit /b 1
)

REM --- Configure output ports ---
set "OUT1=COM10"
set "OUT2=COM12"

echo.
echo === Configuration ===
echo   Source (real device):       %MINDWAVE_PORT%
echo   Output 1 (writes to):      %OUT1%  -- original app reads from COM11
echo   Output 2 (writes to):      %OUT2%  -- your app reads from COM13
echo.
echo   Original NeuroSky app: connect to COM11
echo   EEG Meditation Trainer:    connect to COM13
echo.
echo   If the original app only connects to %MINDWAVE_PORT% and can't be changed:
echo     1. Unpair the real MindWave from Windows Bluetooth
echo     2. In com0com Setup, rename COM11 to %MINDWAVE_PORT%
echo     3. Re-pair MindWave (it will get a new port, e.g. COM7)
echo     4. Re-run this script with the new port
echo.
set /p "READY=Press Enter to start (or Ctrl+C to cancel)..."

echo.
echo === Starting splitter ===
echo Press Ctrl+C to stop.
echo.

python "%~dp0splitter.py" --serial %MINDWAVE_PORT% --out1 %OUT1% --out2 %OUT2%

pause
exit /b 0

REM --- Subroutine: check if port description matches MindWave ---
:CHECK_PORT
echo   %LAST_PORT%: %LAST_DESC%
echo %LAST_DESC% | findstr /i "mindwave neurosky" >NUL 2>&1
if not errorlevel 1 (
    set "MINDWAVE_PORT=%LAST_PORT%"
)
exit /b 0