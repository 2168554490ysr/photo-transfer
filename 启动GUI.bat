@echo off
cd /d "%~dp0"

rem ============================================
rem  Photo/Video transfer tool - one-click GUI launch
rem  Double-click to open the GUI (no console window).
rem  If it fails, run the following to see logs:
rem     python modules\gui\gui.py
rem ============================================

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "modules\gui\gui.py"
) else (
    start "" python "modules\gui\gui.py"
)
