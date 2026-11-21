@echo off
setlocal
cd /d "%~dp0"
rem AktoMat - uruchomienie:  start.bat [run^|web^|eval --gt KATALOG^|classes] [opcje]
if not exist .venv (
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env copy .env.example .env >nul
where tesseract >nul 2>nul || if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" echo [UWAGA] Brak Tesseract OCR - skany nie beda odczytane. Instalacja: https://github.com/UB-Mannheim/tesseract/wiki (z jezykiem polskim)
python -m odw2json %*
