"""Configuration loading, validation, and saved-search importing."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


EXTENSION_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXTENSION_DIR.parents[1]
DEFAULT_CONFIG_PATH = EXTENSION_DIR / "config.json"

SUPPORTED_SITES = {
    "linkedin", "indeed", "remoteok", "remotive", "jobicy", "arbeitnow",
    "themuse", "naukri", "seek", "jobstreet", "bayt", "reed", "rozee",
    "adzuna", "jooble", "companies",
}
INTERVAL_HOURS = {1, 3, 6, 12}
PROFILE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ConfigError(ValueError):
    """Raised when alert configuration is invalid."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Top-level value in {path} must be an object")
    return data


def save_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(data, handle, ensure_ascii=True, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = load_json(Path(path))
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    timezone_name = config.get("timezone", "Asia/Kolkata")
    try:
        ZoneInfo(str(timezone_name))
    except Exception as exc:
        raise ConfigError(f"Unknown timezone: {timezone_name}") from exc

    profiles = config.get("profiles")
    if not isinstance(profiles, list):
        raise ConfigError("profiles must be an array")

    seen_ids: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            raise ConfigError("Each profile must be an object")
        profile_id = str(profile.get("id", ""))
        if not PROFILE_ID_RE.fullmatch(profile_id):
            raise ConfigError(f"Invalid profile id: {profile_id!r}")
        if profile_id in seen_ids:
            raise ConfigError(f"Duplicate profile id: {profile_id}")
        seen_ids.add(profile_id)

        titles = profile.get("titles")
        if not isinstance(titles, list) or not any(str(t).strip() for t in titles):
            raise ConfigError(f"Profile {profile_id}: titles must not be empty")
        if not str(profile.get("country", "")).strip():
            raise ConfigError(f"Profile {profile_id}: country is required")

        sites = profile.get("sites")
        if not isinstance(sites, list) or not sites:
            raise ConfigError(f"Profile {profile_id}: sites must not be empty")
        invalid_sites = set(sites) - SUPPORTED_SITES
        if invalid_sites:
            raise ConfigError(
                f"Profile {profile_id}: unsupported sites: {sorted(invalid_sites)}"
            )

        _bounded_int(profile, "max_results", 1, 100, profile_id)
        _bounded_int(profile, "hours_old", 1, 720, profile_id)
        _validate_schedule(profile_id, profile.get("schedule", {}))
        _validate_experience(profile_id, profile.get("experience", {}))
        _validate_filters(profile_id, profile.get("filters", {}))


def _bounded_int(
    mapping: dict[str, Any], key: str, minimum: int, maximum: int, profile_id: str
) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"Profile {profile_id}: {key} must be an integer")
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"Profile {profile_id}: {key} must be between {minimum} and {maximum}"
        )
    return value


def _validate_schedule(profile_id: str, schedule: Any) -> None:
    if not isinstance(schedule, dict):
        raise ConfigError(f"Profile {profile_id}: schedule must be an object")
    kind = schedule.get("kind")
    if kind == "interval":
        if schedule.get("hours") not in INTERVAL_HOURS:
            raise ConfigError(
                f"Profile {profile_id}: interval hours must be one of "
                f"{sorted(INTERVAL_HOURS)}"
            )
    elif kind == "daily":
        if not TIME_RE.fullmatch(str(schedule.get("time", ""))):
            raise ConfigError(f"Profile {profile_id}: daily time must be HH:MM")
    else:
        raise ConfigError(
            f"Profile {profile_id}: schedule kind must be interval or daily"
        )


def _validate_experience(profile_id: str, experience: Any) -> None:
    if not isinstance(experience, dict):
        raise ConfigError(f"Profile {profile_id}: experience must be an object")
    if not experience.get("enabled", False):
        return
    minimum = experience.get("min_years")
    maximum = experience.get("max_years")
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (minimum, maximum)):
        raise ConfigError(f"Profile {profile_id}: experience years must be integers")
    if not 0 <= minimum <= maximum <= 50:
        raise ConfigError(f"Profile {profile_id}: invalid experience range")


def _validate_filters(profile_id: str, filters: Any) -> None:
    if not isinstance(filters, dict):
        raise ConfigError(f"Profile {profile_id}: filters must be an object")
    if filters.get("score_logic", "either") not in {"either", "both"}:
        raise ConfigError(f"Profile {profile_id}: score_logic must be either or both")
    for key in ("match", "ats"):
        rule = filters.get(key, {})
        if not isinstance(rule, dict):
            raise ConfigError(f"Profile {profile_id}: {key} rule must be an object")
        minimum = rule.get("minimum", 0)
        if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
            raise ConfigError(f"Profile {profile_id}: {key} minimum must be numeric")
        if not 0 <= float(minimum) <= 100:
            raise ConfigError(f"Profile {profile_id}: {key} minimum must be 0-100")
    digest_size = filters.get("max_email_jobs", 20)
    if isinstance(digest_size, bool) or not isinstance(digest_size, int):
        raise ConfigError(f"Profile {profile_id}: max_email_jobs must be an integer")
    if not 1 <= digest_size <= 50:
        raise ConfigError(f"Profile {profile_id}: max_email_jobs must be 1-50")


def profile_needs_scoring(profile: dict[str, Any]) -> bool:
    filters = profile.get("filters", {})
    return bool(
        filters.get("match", {}).get("enabled", False)
        or filters.get("ats", {}).get("enabled", False)
    )


def profile_needs_playwright(profile: dict[str, Any]) -> bool:
    return bool(set(profile.get("sites", [])) & {"indeed", "naukri"})


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "imported-search"


def import_saved_search(
    name: str,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    saved_searches_path: Path | str | None = None,
) -> str:
    source_path = Path(saved_searches_path or REPO_ROOT / "saved_searches.json")
    saved = load_json(source_path)
    if name not in saved or not isinstance(saved[name], dict):
        raise ConfigError(f"Saved search not found: {name}")

    path = Path(config_path)
    config = load_config(path)
    source = saved[name]
    profile_id = slugify(name)
    existing = next(
        (p for p in config["profiles"] if p.get("id") == profile_id), None
    )
    schedule = (existing or {}).get("schedule", {"kind": "interval", "hours": 3})
    filters = (existing or {}).get(
        "filters",
        {
            "match": {"enabled": True, "minimum": 50},
            "ats": {"enabled": True, "minimum": 60},
            "score_logic": "either",
            "max_email_jobs": 20,
        },
    )
    titles = list(source.get("titles", []))
    titles.extend(
        line.strip() for line in str(source.get("custom", "")).splitlines() if line.strip()
    )
    titles = list(dict.fromkeys(titles))
    profile = {
        "id": profile_id,
        "label": name,
        "enabled": bool((existing or {}).get("enabled", False)),
        "titles": titles,
        "country": source.get("country", ""),
        "city": source.get("city", ""),
        "sites": source.get("sites", []),
        "max_results": int(source.get("max_results", 30)),
        "hours_old": int(source.get("hours_old", 168)),
        "remote_only": bool(source.get("remote_only", False)),
        "experience": {
            "enabled": bool(source.get("use_exp", False)),
            "min_years": int(source.get("exp_min", 0)),
            "max_years": int(source.get("exp_max", 5)),
        },
        "schedule": schedule,
        "filters": filters,
    }
    if existing is None:
        config["profiles"].append(profile)
    else:
        config["profiles"][config["profiles"].index(existing)] = profile
    validate_config(config)
    save_json_atomic(path, config)
    return profile_id
