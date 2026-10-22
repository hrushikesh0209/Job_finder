"""
One-command launcher for the Job Finder web app.

    python launch.py            (or double-click launch.bat on Windows)

First run: creates ./venv, installs requirements.txt and Playwright's
Chromium (needed for Indeed). Later runs skip anything already installed —
requirements are reinstalled only when requirements.txt changes — then
load API keys from .env and open the app in your browser.

Options:
    --port N            serve on port N (default 8501; next free port is used if busy)
    --skip-playwright   don't install Playwright/Chromium (Indeed is then skipped)
    --reinstall         force reinstalling requirements
    --no-browser        start the server without opening a browser tab
"""

import argparse
import hashlib
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQS = ROOT / "requirements.txt"
REQS_MARKER = VENV / ".jobfinder-requirements.sha256"
PW_MARKER = VENV / ".jobfinder-playwright"
ENV_FILE = ROOT / ".env"


def say(msg: str) -> None:
    print(f"[job-finder] {msg}", flush=True)


def run(cmd: list, **kw) -> int:
    return subprocess.call([str(c) for c in cmd], cwd=ROOT, **kw)


def in_project_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def ensure_venv() -> None:
    """Create ./venv if needed and re-run this script with its Python."""
    if in_project_venv():
        return
    if not VENV_PY.exists():
        say("Creating virtual environment in ./venv (first run only) ...")
        if run([sys.executable, "-m", "venv", VENV]) != 0:
            sys.exit("Could not create the virtual environment.")
    sys.exit(run([VENV_PY, Path(__file__).resolve(), *sys.argv[1:]]))


def ensure_requirements(force: bool) -> None:
    digest = hashlib.sha256(REQS.read_bytes()).hexdigest()
    if not force and REQS_MARKER.exists() and REQS_MARKER.read_text().strip() == digest:
        return
    say("Installing packages from requirements.txt (first run can take a few minutes) ...")
    run([VENV_PY, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    if run([VENV_PY, "-m", "pip", "install", "-r", REQS, "--prefer-binary", "-q"]) != 0:
        sys.exit("Package install failed — see the pip output above.")
    REQS_MARKER.write_text(digest)


def ensure_playwright() -> None:
    """Indeed needs a headless Chromium. Failure here is not fatal: the app
    just skips Indeed, exactly as it does without Playwright."""
    if PW_MARKER.exists():
        return
    say("Installing Playwright + Chromium for Indeed (one time, ~150 MB) ...")
    ok = (run([VENV_PY, "-m", "pip", "install", "playwright", "-q"]) == 0
          and run([VENV_PY, "-m", "playwright", "install", "chromium"]) == 0)
    if ok:
        PW_MARKER.write_text("ok")
    else:
        say("Playwright install failed — the app still works, Indeed will be skipped. "
            "Retry later by running this launcher again.")


def load_env_file() -> list[str]:
    """KEY=value lines from .env (API keys). Real environment variables win."""
    loaded = []
    if not ENV_FILE.exists():
        return loaded
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]
        else:                         # unquoted: drop an inline "# comment"
            value = value.split("#", 1)[0].strip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def main() -> None:
    if sys.version_info < (3, 10):
        sys.exit("Python 3.10+ is required — install it from python.org.")

    parser = argparse.ArgumentParser(description="Set up and launch Job Finder")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--skip-playwright", action="store_true")
    parser.add_argument("--reinstall", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    ensure_venv()                     # re-execs inside ./venv when needed
    ensure_requirements(args.reinstall)
    if not args.skip_playwright:
        ensure_playwright()

    keys = load_env_file()
    if keys:
        say(f"Loaded from .env: {', '.join(keys)}")

    port = free_port(args.port)
    if port != args.port:
        say(f"Port {args.port} is busy — using {port}.")
    say(f"Starting the app at http://localhost:{port}  (Ctrl+C to stop)")
    try:
        sys.exit(run([
            VENV_PY, "-m", "streamlit", "run", "app.py",
            "--server.port", port,
            # local only — don't expose the app (and your CV) to the network
            "--server.address", "localhost",
            # headless=false makes Streamlit open the browser automatically
            "--server.headless", "true" if args.no_browser else "false",
            "--browser.gatherUsageStats", "false",
        ]))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
