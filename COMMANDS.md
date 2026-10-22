# Commands

## Run the web app (one command)

```powershell
.\launch.bat            # Windows — or just double-click launch.bat
./launch.sh             # macOS / Linux
python launch.py        # any OS
```

The first run creates `venv`, installs `requirements.txt` and Playwright's
Chromium (for Indeed), then opens http://localhost:8501. Later runs skip
straight to launching; packages are reinstalled only when
`requirements.txt` changes.

Options: `--port 8502`, `--no-browser`, `--skip-playwright`, `--reinstall`.

API keys (optional): copy `.env.example` to `.env` and fill in the keys you
have — the launcher loads it automatically. `.env` is git-ignored.

## CLI

```powershell
.\venv\Scripts\python.exe run.py --keyword "Software Engineer" --location "Hyderabad, India" --country India --cv my_cv.pdf
```

## Email alerts (GitHub Actions)

See `extensions/job_alerts/README.md`.
