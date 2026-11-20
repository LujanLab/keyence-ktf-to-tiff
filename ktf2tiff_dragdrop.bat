@echo off
rem Drag .ktf files or folders onto this file to convert them to TIFF.
python "%~dp0ktf2tiff.py" %*
pause
