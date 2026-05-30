# SCT — Windows installer

A minimal, no-admin installer for non-Docker Windows users. Sets up an isolated Python
virtual environment, installs all requirements, installs Chromium for Playwright (so JS
rendering and PDF reports work), and creates Desktop + Start Menu shortcuts that launch
the local web UI.

## Requirements

- Windows 10 / 11
- Python 3.10 or newer ([python.org/downloads](https://www.python.org/downloads/))
  - During Python setup, check **"Add python.exe to PATH"**.

## Install

Right-click `install.ps1` → **Run with PowerShell** (or, from a terminal):

```powershell
powershell -ExecutionPolicy Bypass -File installer\install.ps1
```

The script:

1. Verifies Python ≥ 3.10.
2. Creates `.venv` in the project root (isolated; doesn't touch system Python).
3. Installs everything in `requirements.txt` into the venv.
4. Installs Chromium for Playwright.
5. Creates **SCT** shortcuts on the Desktop and in the Start Menu.

No administrator rights are required.

## Run

Double-click the **SCT** shortcut (or `installer\run.bat`). The web UI opens at
<http://127.0.0.1:8000>.

## Uninstall

Right-click `uninstall.ps1` → **Run with PowerShell** (or
`powershell -ExecutionPolicy Bypass -File installer\uninstall.ps1`). Removes the shortcuts
and `.venv`. **Job outputs in `webapp_jobs/` are kept** — delete that folder manually if
you want to remove them too.

## Notes

- This installer is the **non-Docker path** for Windows users. For containers, use
  `docker compose up --build` (see the project README).
- Secrets (`.env`, `client_secret.json`, tokens) stay local in their gitignored folders and
  are never bundled with the installer.
- Need a true single-file `.exe`? See the *Windows installer* item in `ROADMAP.md` — a
  PyInstaller spec is the natural next step; this PowerShell installer is the reliable
  cross-Python-version path that doesn't need a build server.
