"""Alert scheduling and delivery-state helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


DEFAULT_STATE_PATH = Path(
    os.getenv(
        "JOB_ALERT_STATE_PATH",
        str(Path(tempfile.gettempdir()) / "job-finder-alert-state.json"),
    )
)
MAX_NOTIFIED_PER_PROFILE = 5000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def load_state(path: Path | str = DEFAULT_STATE_PATH) -> dict[str, Any]:
    state_path = Path(path)
    try:
        with state_path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    if not isinstance(state.get("profiles"), dict):
        state["profiles"] = {}
    return state


def save_state(path: Path | str, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=state_path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(state, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(state_path)


def profile_state(state: dict[str, Any], profile_id: str) -> dict[str, Any]:
    profiles = state.setdefault("profiles", {})
    current = profiles.setdefault(profile_id, {})
    current.setdefault("notified", {})
    return current


def is_profile_due(
    profile: dict[str, Any],
    current_state: dict[str, Any],
    timezone_name: str,
    now: datetime | None = None,
) -> bool:
    if not profile.get("enabled", False):
        return False
    now_utc = (now or utc_now()).astimezone(timezone.utc)
    last_run = parse_timestamp(current_state.get("last_run_at"))
    if last_run is None:
        return True

    schedule = profile["schedule"]
    if schedule["kind"] == "interval":
        return now_utc >= last_run + timedelta(hours=int(schedule["hours"]))

    local_tz = ZoneInfo(timezone_name)
    local_now = now_utc.astimezone(local_tz)
    local_last = last_run.astimezone(local_tz)
    hour, minute = (int(part) for part in schedule["time"].split(":"))
    scheduled_today = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return local_last.date() < local_now.date() and local_now >= scheduled_today


def due_profiles(
    config: dict[str, Any], state: dict[str, Any], now: datetime | None = None
) -> list[dict[str, Any]]:
    timezone_name = config.get("timezone", "Asia/Kolkata")
    return [
        profile
        for profile in config.get("profiles", [])
        if is_profile_due(
            profile,
            state.get("profiles", {}).get(profile["id"], {}),
            timezone_name,
            now=now,
        )
    ]


def normalized_url(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return ""
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc:
        return ""
    query = urlencode(
        sorted(
            (key, val)
            for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        )
    )
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, "")
    )


def job_identity(job: dict[str, Any]) -> str:
    url = normalized_url(job.get("job_url"))
    if url:
        source = f"url|{url}"
    elif job.get("job_id"):
        source = f"id|{job.get('site', '')}|{job.get('job_id')}"
    else:
        source = "fallback|{title}|{company}|{location}".format(
            title=str(job.get("title", "")).strip().lower(),
            company=str(job.get("company", "")).strip().lower(),
            location=str(job.get("location", "")).strip().lower(),
        )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def mark_run(
    current_state: dict[str, Any],
    status: str,
    result_count: int,
    error: str = "",
    now: datetime | None = None,
) -> None:
    current_state["last_run_at"] = iso_utc(now or utc_now())
    current_state["last_status"] = status
    current_state["last_result_count"] = int(result_count)
    if error:
        current_state["last_error"] = str(error)[:1000]
    else:
        current_state.pop("last_error", None)


def mark_notified(
    current_state: dict[str, Any], identities: list[str], now: datetime | None = None
) -> None:
    timestamp = iso_utc(now or utc_now())
    notified = current_state.setdefault("notified", {})
    for identity in identities:
        notified[identity] = timestamp
    if len(notified) > MAX_NOTIFIED_PER_PROFILE:
        newest = sorted(notified.items(), key=lambda item: item[1])[-MAX_NOTIFIED_PER_PROFILE:]
        current_state["notified"] = dict(newest)
