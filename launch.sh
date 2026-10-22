#!/usr/bin/env sh
# One command to set up (first run) and launch Job Finder:  ./launch.sh
cd "$(dirname "$0")" || exit 1
if [ -x venv/bin/python ]; then exec venv/bin/python launch.py "$@"; fi
exec python3 launch.py "$@"
