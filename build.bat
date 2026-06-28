@echo off
setlocal
cd /d "%~dp0"

echo Installing runtime and build dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo.
  echo Failed to install dependencies.
  pause
  exit /b 1
)

echo Building PDFTool.exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --name PDFTool ^
  --collect-all fitz ^
  --collect-all imagehash ^
  --collect-data reportlab ^
  --exclude-module pytest ^
  --exclude-module unittest ^
  merge_compress_pdf.py
if errorlevel 1 (
  echo.
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Build complete: "%~dp0dist\PDFTool\PDFTool.exe"

endlocal
