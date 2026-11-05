# qbiq Path Tool for Revit 2024

A "Path Tool" ribbon tab in Revit. **Open Path Tool** opens a window with the current model in 3D, Auto-path, path
editing and a video timeline. **Save path (XML)** writes the Enscape path file; you load it into Enscape yourself.

## Install

1. Close Revit.
2. In this folder run: `powershell -ExecutionPolicy Bypass -File install.ps1`
3. Start Revit 2024. The **Path Tool** tab appears.

To update, close Revit and run `install.ps1` again. To remove: `install.ps1 -Uninstall`.

## How it works

The add-in reads the open model (read-only, it never changes or saves it) and sends one level to a small local engine
(`engine\qbiq-engine.exe`, the same engine as the web tool). The engine listens on `127.0.0.1` only, on a random port, and
answers only calls that carry a per-session key. The add-in starts it when you open the window and stops it when Revit
closes. Nothing leaves your computer.

- Level read: the active view's level (open the floor plan you want first), else the lowest level.
- **Refresh model** re-reads Revit and keeps your points; points no longer on walkable floor are marked amber.
- Broken Rooms (unplaced, unenclosed, no area, duplicate numbers) show a banner with **Load JSON instead**.
- **Dump level JSON** (same tab) writes the level payload to `%TEMP%` for checking the extraction.

## Antivirus

`qbiq-engine.exe` is a PyInstaller program that opens a localhost port. Some antivirus tools flag that pattern; if the
window stays empty, allow `%AppData%\Autodesk\Revit\Addins\2024\QbiqPathTool\engine\qbiq-engine.exe`.

## Build

`build-all.bat` (needs the .NET SDK, and Python with `requirements.txt` + `pyinstaller`) writes `addin\out`.
Tests: `dotnet test Qbiq.PathTool.Tests`. For development without the packaged engine set `QBIQ_ENGINE_PYTHON` (a python.exe)
and `QBIQ_ENGINE_SCRIPT` (`run.py`) before starting Revit.
