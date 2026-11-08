#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "No se encontró python3. Instálalo y vuelve a intentarlo."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if ! command -v tesseract >/dev/null 2>&1; then
  echo "Aviso: sin Tesseract no se leen fotos. Instala tesseract-ocr y tesseract-ocr-spa."
fi
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Aviso: sin ffmpeg no se puede crear el vídeo."
fi
exec streamlit run app.py
