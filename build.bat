@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo.
echo Building qbiq Path Editor exe...
pyinstaller qbiq.spec --clean --noconfirm

echo.
echo ========================================
echo  Done! Your app is in:
echo  dist\qbiq-path-editor\
echo  Double-click qbiq-path-editor.exe
echo ========================================
pause
