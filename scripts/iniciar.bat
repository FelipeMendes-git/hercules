@echo off
rem Abre o Hercules (sem janela de terminal).
cd /d "%~dp0.."
if not exist ".venv\Scripts\hercules.exe" (
    echo O ambiente ainda nao foi instalado. Rode scripts\instalar.ps1 primeiro.
    pause
    exit /b 1
)
start "" ".venv\Scripts\hercules.exe"
