@echo off
setlocal
cd /d "%~dp0"

python merge_compress_pdf.py
if errorlevel 1 (
  echo.
  echo PDFTool failed to start.
  pause
  exit /b 1
)

endlocal
