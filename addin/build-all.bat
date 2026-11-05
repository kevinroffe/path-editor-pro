@echo off
rem Builds the engine exe and the Revit add-in into addin\out (add-in DLLs, engine, install.ps1).
rem Needs: the .NET SDK (dotnet on PATH), and the Python venv from requirements.txt plus pyinstaller.
rem   set PY=C:\path\to\venv\Scripts\python.exe   (defaults to python on PATH)
setlocal
if "%PY%"=="" set PY=python
set ROOT=%~dp0..
set OUT=%~dp0out
set WORK=%TEMP%\qbiq-engine-build

echo Building the engine...
rem A short work path keeps DLL paths under the Windows limit.
call "%PY%" -m PyInstaller "%ROOT%\engine.spec" --clean --noconfirm --distpath "%WORK%\dist" --workpath "%WORK%\work" || exit /b 1

echo Building the add-in...
call dotnet build "%~dp0Qbiq.PathTool.Addin" -c Release || exit /b 1

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"
rem robocopy, not xcopy: xcopy fails on long paths. Its exit codes below 8 mean success.
robocopy "%~dp0Qbiq.PathTool.Addin\bin\Release\net48" "%OUT%\addin" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
robocopy "%WORK%\dist\qbiq-engine" "%OUT%\engine" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1
copy /y "%~dp0install.ps1" "%OUT%\install.ps1" >nul

echo.
echo Done. In addin\out run:  powershell -ExecutionPolicy Bypass -File install.ps1
endlocal
