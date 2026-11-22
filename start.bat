@echo off
setlocal
cd /d "%~dp0"
rem AktoMat - uruchomienie:  start.bat [run^|web^|docs^|eval --gt KATALOG^|classes] [opcje]
if not exist .venv (
  py -3.13 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env copy .env.example .env >nul
set "TESS=tesseract"
where tesseract >nul 2>nul || set "TESS=C:\Program Files\Tesseract-OCR\tesseract.exe"
if exist "%~dp0tessdata\pol.traineddata" set "TESSDATA_PREFIX=%~dp0tessdata"
where tesseract >nul 2>nul || if not exist "%TESS%" (
  echo [UWAGA] Brak Tesseract OCR - skany beda czytane slabszym RapidOCR. Instalacja: https://github.com/UB-Mannheim/tesseract/wiki
  goto :run
)
rem Tesseract bez jezyka polskiego: pobierz pol.traineddata do .\tessdata (jednorazowo, ok. 15 MB)
"%TESS%" --list-langs 2>nul | findstr /x "pol" >nul || (
  echo Pobieram jezyk polski dla Tesseract do .\tessdata ...
  if not exist "%~dp0tessdata" mkdir "%~dp0tessdata"
  curl -sSL -o "%~dp0tessdata\pol.traineddata" https://github.com/tesseract-ocr/tessdata/raw/main/pol.traineddata && set "TESSDATA_PREFIX=%~dp0tessdata"
)
:run
python -m odw2json %*
