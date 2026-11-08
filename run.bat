@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo No se encontro Python. Instalalo desde https://www.python.org/downloads/ y marca "Add python.exe to PATH".
  exit /b 1
)

if not exist .venv\Scripts\python.exe (
  python -m venv .venv
)

call .venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
streamlit run app.py
