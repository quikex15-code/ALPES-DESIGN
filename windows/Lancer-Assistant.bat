@echo off
rem Lance l'assistant de dessin AutoCAD (ouvrez AutoCAD avant).
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0AssistantAutoCAD.ps1"
