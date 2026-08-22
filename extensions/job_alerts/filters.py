"""Extension-owned experience and score filters."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


_EXP_RANGE_RE = re.compile(
    r"(\d{1,2})\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXP_PLUS_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)\b", re.IGNORECASE)
_EXP_MIN_RE = re.compile(
    r"(?:at least|minimum|min\.?)\s+(\d{1,2})\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)
_EXP_SINGLE_RE = re.compile(
    r"(\d{1,2})\s*(?:years?|yrs?)(?:'|\u2019)?\s*(?:of\s+)?"
    r"(?:[\w/+-]+\s+){0,3}experience",
    re.IGNORECASE,
)
_EXP_OPEN_MAX = 99


def extract_experience_range(text: str) -> tuple[int, int] | None:
    if not text:
        return None
    match = _EXP_RANGE_RE.search(text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return (low, high) if low <= high else (high, low)
    match = _EXP_PLUS_RE.search(text) or _EXP_MIN_RE.search(text) or _EXP_SINGLE_RE.search(text)
    if match:
        return int(match.group(1)), _EXP_OPEN_MAX
    return None


def _text_column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series("", index=df.index, dtype="string")
    return df[name].fillna("").astype(str)


def apply_experience_filter(
    df: pd.DataFrame, experience: dict[str, Any]
) -> pd.DataFrame:
    if df.empty or not experience.get("enabled", False):
        return df.reset_index(drop=True)
    blobs = (
        _text_column(df, "title")
        + " | "
        + _text_column(df, "job_level")
        + " | "
        + _text_column(df, "description")
    )
    ranges = [extract_experience_range(text) for text in blobs]
    minimum = int(experience["min_years"])
    maximum = int(experience["max_years"])
    keep = [
        requirement is None
        or (requirement[0] <= maximum and requirement[1] >= minimum)
        for requirement in ranges
    ]
    return df[pd.Series(keep, index=df.index)].reset_index(drop=True)


def qualifies_scores(job: dict[str, Any], filters: dict[str, Any]) -> bool:
    evaluations: list[bool] = []
    match_rule = filters.get("match", {})
    ats_rule = filters.get("ats", {})
    if match_rule.get("enabled", False):
        evaluations.append(float(job.get("match_score", 0) or 0) >= float(match_rule["minimum"]))
    if ats_rule.get("enabled", False):
        evaluations.append(float(job.get("ats_score", 0) or 0) >= float(ats_rule["minimum"]))
    if not evaluations:
        return True
    if filters.get("score_logic", "either") == "both":
        return all(evaluations)
    return any(evaluations)


def apply_score_filter(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    if df.empty:
        return df.reset_index(drop=True)
    keep = [qualifies_scores(row, filters) for row in df.to_dict("records")]
    return df[pd.Series(keep, index=df.index)].reset_index(drop=True)


def rank_jobs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    ranked = df.copy()
    match_source = (
        ranked["match_score"]
        if "match_score" in ranked.columns
        else pd.Series(0.0, index=ranked.index)
    )
    ats_source = (
        ranked["ats_score"]
        if "ats_score" in ranked.columns
        else pd.Series(0.0, index=ranked.index)
    )
    match = pd.to_numeric(match_source, errors="coerce").fillna(0)
    ats = pd.to_numeric(ats_source, errors="coerce").fillna(0)
    ranked["_alert_rank"] = pd.concat([match, ats], axis=1).max(axis=1)
    ranked = ranked.sort_values(
        ["_alert_rank", "date_posted"] if "date_posted" in ranked.columns else ["_alert_rank"],
        ascending=False,
        na_position="last",
    )
    return ranked.drop(columns=["_alert_rank"]).reset_index(drop=True)
