@echo off
rem Lance l'application Factures METRO en local (http://localhost:5000)
rem Au premier lancement : cree l'environnement Python et le premier compte administrateur.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Installation de l'environnement Python...
    py -3 -m venv .venv || python -m venv .venv || goto :erreur
)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :erreur
".venv\Scripts\python.exe" manage.py initialiser || goto :erreur

rem usage local en http : cookie de session non "Secure"
set COOKIE_SECURE=0
start "" http://localhost:5000
".venv\Scripts\python.exe" app.py
goto :eof

:erreur
echo Echec. Python 3.10 ou plus recent est-il installe ?
pause
