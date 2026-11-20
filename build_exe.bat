@echo off
rem Rebuilds KTF2TIFF.exe in this folder. Needs Python 3.9+ and internet for pip.
setlocal
set ENV=%TEMP%\ktf2tiff_buildenv
set WORK=%TEMP%\ktf2tiff_build
if not exist "%ENV%\Scripts\python.exe" python -m venv "%ENV%" || goto :err
"%ENV%\Scripts\python.exe" -m pip install -q pyinstaller numpy pillow tifffile imagecodecs || goto :err
"%ENV%\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name KTF2TIFF --paths "%~dp0." --hidden-import imagecodecs._imcd --hidden-import imagecodecs._shared --exclude-module matplotlib --exclude-module scipy --distpath "%~dp0." --workpath "%WORK%\work" --specpath "%WORK%" "%~dp0ktf2tiff_gui.py" || goto :err
echo Built "%~dp0KTF2TIFF.exe"
pause
exit /b 0
:err
echo Build failed.
pause
exit /b 1
