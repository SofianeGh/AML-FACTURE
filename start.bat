@echo off
rem Lance l'application Factures METRO (cree l'environnement Python au premier lancement)
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Installation de l'environnement Python...
    py -3 -m venv .venv || python -m venv .venv || goto :erreur
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :erreur
)
start "" http://localhost:5000
".venv\Scripts\python.exe" app.py
goto :eof

:erreur
echo Echec de l'installation. Python 3.10 ou plus recent est-il installe ?
pause
