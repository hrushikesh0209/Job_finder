"""Headless scheduled-search orchestration for the isolated extension."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .config import profile_needs_scoring
from .cv_secret import decode_cv_secret
from .email_sender import build_digest_message, send_message, settings_from_env
from .filters import apply_experience_filter, apply_score_filter, rank_jobs
from .scoring import REPO_ROOT, score_jobs
from .state import (
    job_identity,
    mark_notified,
    mark_run,
    profile_state,
    save_state,
)


logger = logging.getLogger(__name__)

REMOTE_REGIONS = {
    "Worldwide": "Worldwide",
    "US Only": "United States",
    "Europe": "European Union",
    "Asia Pacific": "Asia",
    "LATAM": "Latin America",
}


@dataclass
class RunResult:
    profile_id: str
    status: str
    found: int = 0
    qualifying: int = 0
    selected: int = 0
    emailed: int = 0
    error: str = ""


def build_location(country: str, city: str) -> str:
    clean_city = str(city or "").strip()
    if country == "Remote (Worldwide)":
        for separator in ("\u2013", "-"):
            if separator in clean_city:
                region = clean_city.split(separator, 1)[1].strip()
                return REMOTE_REGIONS.get(region, "Worldwide")
        return "Worldwide"
    if clean_city == "Entire country (no city filter)":
        clean_city = ""
    if not clean_city or clean_city == country:
        return country
    return f"{clean_city}, {country}"


def _search(profile: dict[str, Any]) -> pd.DataFrame:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scraper import search_jobs_multi

    # The experience filter reads the description too — without it every
    # LinkedIn card (title only) would pass a "2-5 years" filter unchecked.
    needs_descriptions = profile_needs_scoring(profile) or bool(
        profile.get("experience", {}).get("enabled", False)
    )
    return search_jobs_multi(
        keywords=[str(value).strip() for value in profile["titles"] if str(value).strip()],
        location=build_location(profile["country"], profile.get("city", "")),
        max_results=int(profile["max_results"]),
        hours_old=int(profile["hours_old"]),
        sites=list(profile["sites"]),
        remote_only=bool(profile.get("remote_only", False)),
        fetch_full_descriptions=needs_descriptions,
        desc_workers=5,
        country=profile["country"],
    )


def _unique_unnotified(
    df: pd.DataFrame, notified: dict[str, str]
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, Any]] = []
    identities: list[str] = []
    seen_this_run: set[str] = set()
    for job in df.to_dict("records"):
        identity = job_identity(job)
        if identity in notified or identity in seen_this_run:
            continue
        seen_this_run.add(identity)
        rows.append(job)
        identities.append(identity)
    return pd.DataFrame(rows), identities


def _redacted_error(error: Exception) -> str:
    message = str(error)
    for name in (
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "NOTIFY_EMAIL",
        "ADZUNA_APP_ID",
        "ADZUNA_APP_KEY",
        "JOOBLE_API_KEY",
        "REED_API_KEY",
    ):
        value = os.getenv(name, "")
        if value:
            message = message.replace(value, f"[{name} redacted]")
    return message[:1000]


def run_profile(
    profile: dict[str, Any],
    state: dict[str, Any],
    state_path: Path | str,
    dry_run: bool = False,
) -> RunResult:
    profile_id = profile["id"]
    current_state = profile_state(state, profile_id)
    found = 0
    qualifying = 0
    try:
        jobs = _search(profile)
        if jobs is None or jobs.empty:
            result = RunResult(profile_id, "no-results")
        else:
            found = len(jobs)
            jobs = apply_experience_filter(jobs, profile.get("experience", {}))
            if profile_needs_scoring(profile):
                cv_text = decode_cv_secret(os.getenv("JOBFINDER_CV_GZIP_BASE64", ""))
                if not cv_text:
                    raise ValueError(
                        "JOBFINDER_CV_GZIP_BASE64 is required for score filters"
                    )
                jobs = score_jobs(jobs, cv_text)
            jobs = apply_score_filter(jobs, profile.get("filters", {}))
            qualifying = len(jobs)
            jobs = rank_jobs(jobs)
            fresh, identities = _unique_unnotified(
                jobs, current_state.get("notified", {})
            )
            if fresh.empty:
                result = RunResult(profile_id, "no-new-matches", found, qualifying)
            else:
                limit = int(profile.get("filters", {}).get("max_email_jobs", 20))
                fresh = fresh.head(limit).reset_index(drop=True)
                identities = identities[: len(fresh)]
                if dry_run:
                    result = RunResult(
                        profile_id, "dry-run", found, qualifying, len(fresh), 0
                    )
                else:
                    settings = settings_from_env()
                    message = build_digest_message(
                        profile, fresh.to_dict("records"), settings
                    )
                    send_message(message, settings)
                    mark_notified(current_state, identities)
                    result = RunResult(
                        profile_id, "sent", found, qualifying, len(fresh), len(fresh)
                    )
    except Exception as exc:
        logger.exception("Alert profile %s failed", profile_id)
        result = RunResult(
            profile_id,
            "error",
            found=found,
            qualifying=qualifying,
            error=_redacted_error(exc),
        )

    if not dry_run:
        mark_run(
            current_state,
            result.status,
            result.found,
            error=result.error,
        )
        save_state(state_path, state)
    return result


def run_profiles(
    profiles: list[dict[str, Any]],
    state: dict[str, Any],
    state_path: Path | str,
    dry_run: bool = False,
) -> list[RunResult]:
    return [run_profile(profile, state, state_path, dry_run=dry_run) for profile in profiles]
