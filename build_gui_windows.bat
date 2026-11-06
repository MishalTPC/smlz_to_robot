@echo off
setlocal
cd /d "%~dp0"
echo The Project Company - SMLX to Robot v0.1.0
where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher not found. Install Python 3.12 64-bit.
    pause
    exit /b 1
)
if not exist ".gui_venv\Scripts\python.exe" (
    py -3.12 -m venv .gui_venv
    if errorlevel 1 goto :fail
)
call ".gui_venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
call ".gui_venv\Scripts\python.exe" -m pip install -r requirements-gui.txt
if errorlevel 1 goto :fail
call ".gui_venv\Scripts\python.exe" -m unittest discover -s src -p "test_gui_workflow.py" -v
if errorlevel 1 goto :fail
call ".gui_venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name SMLX_to_Robot --paths src --add-data "assets;assets" --collect-all sectionproperties launch_gui.py
if errorlevel 1 goto :fail
echo.
echo BUILD COMPLETE: dist\SMLX_to_Robot.exe
pause
exit /b 0
:fail
echo.
echo BUILD FAILED - review messages above.
pause
exit /b 1
