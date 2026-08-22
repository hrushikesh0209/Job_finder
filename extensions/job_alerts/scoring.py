"""CV scoring adapter that uses the portal's public analyzer APIs."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
_SEARCH_URL_MARKERS = (
    "/jobs/search", "jobs?q=", "jobs-search?k=", "jobs?keywords=",
    "/?text=", "/jsearch/", "google.com/search",
)


def _ensure_repo_importable() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _is_direct_job_url(url: Any) -> bool:
    value = str(url or "").lower()
    return value.startswith(("http://", "https://")) and not any(
        marker in value for marker in _SEARCH_URL_MARKERS
    )


def score_jobs(df: pd.DataFrame, cv_text: str, fetch_workers: int = 8) -> pd.DataFrame:
    if not cv_text.strip():
        raise ValueError("CV text is required when Match or ATS filters are enabled")
    if df.empty:
        return df.copy()

    _ensure_repo_importable()
    from cv_analyzer import extract_skills, score_cv_against_jobs
    from scraper import fetch_job_page_texts

    descriptions = (
        df["description"].fillna("").astype(str).tolist()
        if "description" in df.columns
        else [""] * len(df)
    )
    urls = (
        df["job_url"].fillna("").astype(str).tolist()
        if "job_url" in df.columns
        else [""] * len(df)
    )
    missing = [
        index
        for index, (description, url) in enumerate(zip(descriptions, urls))
        if not description.strip() and _is_direct_job_url(url)
    ]
    if missing:
        fetched = fetch_job_page_texts(
            [urls[index] for index in missing], workers=fetch_workers
        )
        for index, text in zip(missing, fetched):
            if text:
                descriptions[index] = text

    match_scores = score_cv_against_jobs(cv_text, descriptions)
    cv_skills = extract_skills(cv_text)
    job_skills = [extract_skills(description) for description in descriptions]
    matched = [skills & cv_skills for skills in job_skills]

    scored = df.copy()
    scored["match_score"] = match_scores
    scored["ats_score"] = [
        round(len(overlap) / len(skills) * 100, 1) if skills else 0.0
        for overlap, skills in zip(matched, job_skills)
    ]
    scored["matched_skills"] = [sorted(overlap) for overlap in matched]
    scored["missing_skills"] = [
        sorted(skills - cv_skills) for skills in job_skills
    ]
    return scored
