"""
Job scraper — LinkedIn guest API + Indeed + country-specific boards.
No browser, no API key required.

Supported platforms:
  linkedin, indeed, naukri (India), seek (AU/NZ), jobstreet (SE Asia),
  bayt (Middle East), reed (UK), rozee (Pakistan),
  remoteok / remotive / jobicy (remote — open JSON APIs),
  arbeitnow (Germany/EU — open API), themuse (US/global — open API)

Performance:
  - All selected sites scraped in parallel (ThreadPoolExecutor)
  - LinkedIn descriptions fetched in parallel (configurable workers)
  - Exponential-backoff retry on transient HTTP errors
  - Per-site quota = full max_results; deduplicated at the end
"""

import os
import re
import json
import math
import time
import random
import logging
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
import pandas as pd

# Playwright — headless real browser; bypasses JS challenges & reCAPTCHA gates.
# Install: pip install playwright && playwright install chromium
try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger(__name__)

# lxml is ~5-10× faster than the stdlib parser for the large search pages and
# per-job description fetches; fall back silently when it isn't installed.
try:
    import lxml  # noqa: F401
    _BS_PARSER = "lxml"
except ImportError:
    _BS_PARSER = "html.parser"

SUPPORTED_SITES = [
    "linkedin", "indeed", "remoteok", "remotive", "jobicy", "arbeitnow",
    "themuse", "naukri", "seek", "jobstreet", "bayt", "reed", "rozee",
    "adzuna", "jooble",
]

# site key → the label written into the DataFrame's `site` column
SITE_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn",   "indeed": "Indeed",       "remoteok": "RemoteOK",
    "remotive": "Remotive",   "jobicy": "Jobicy",       "arbeitnow": "Arbeitnow",
    "themuse": "The Muse",    "naukri": "Naukri",       "seek": "Seek",
    "jobstreet": "JobStreet", "bayt": "Bayt",           "reed": "Reed",
    "rozee": "Rozee",         "adzuna": "Adzuna",       "jooble": "Jooble",
}

__all__ = ["search_jobs", "search_jobs_multi", "fetch_job_page_texts",
           "SUPPORTED_SITES", "SITE_LABELS"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    # No Accept-Encoding override: requests must advertise only codings it can
    # decode — claiming "br" without brotli installed yields undecodable bodies.
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
    "Upgrade-Insecure-Requests": "1",
}

# Country → JobStreet API site key
_JOBSTREET_COUNTRY_KEYS: dict[str, str] = {
    "Malaysia":    "MY-Main",
    "Philippines": "PH-Main",
    "Singapore":   "SG-Main",
    "Indonesia":   "ID-Main",
}

# Country → Bayt URL slug
_BAYT_COUNTRY_SLUGS: dict[str, str] = {
    "UAE":          "uae",
    "Saudi Arabia": "saudi-arabia",
    "Jordan":       "jordan",
    "Egypt":        "egypt",
    "Kuwait":       "kuwait",
    "Bahrain":      "bahrain",
    "Qatar":        "qatar",
    "Morocco":      "morocco",
}


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_with_retry(
    session: requests.Session,
    url: str,
    params: dict = None,
    max_attempts: int = 3,
    timeout: int = 15,
) -> Optional[requests.Response]:
    """GET with exponential-backoff retry on 429 / 5xx / connection errors.

    Waits are capped — these run inside the UI thread, so a stubborn 429 must
    fail fast rather than hang a search for minutes.
    """
    for attempt in range(max_attempts):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r
            if r.status_code == 429:
                wait = min(8 * (2 ** attempt), 15) + random.uniform(0, 2)
                logger.warning(f"Rate-limited (429) — retrying in {wait:.1f}s")
                time.sleep(wait)
            elif r.status_code in (500, 502, 503, 504):
                wait = min(4 * (2 ** attempt), 10)
                logger.warning(f"Server error {r.status_code} — retrying in {wait:.1f}s")
                time.sleep(wait)
            else:
                logger.warning(f"HTTP {r.status_code} from {url}")
                return None
        except requests.RequestException as e:
            wait = min(3 * (2 ** attempt), 10)
            logger.warning(f"Request error ({e}) — retrying in {wait:.1f}s")
            time.sleep(wait)
    return None


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    return re.sub(r"\s+", " ", text).strip()


def _json_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.headers["Accept"] = "application/json"
    return s


def _to_dataframe(jobs: list, site: str) -> pd.DataFrame:
    if not jobs:
        return pd.DataFrame()
    df = pd.DataFrame(jobs)
    df["site"] = site
    for col in ["min_amount", "max_amount", "currency", "interval", "salary_text"]:
        if col not in df.columns:
            df[col] = None
    return df


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Deduplicate primarily on job_url (the same role in two cities is two jobs);
    rows without a URL fall back to title|company. A second exact-triple pass
    catches the same posting found via different keywords/boards.
    """
    url = df["job_url"].fillna("").astype(str) if "job_url" in df.columns else pd.Series("", index=df.index)
    fallback = (
        df.get("title", pd.Series("", index=df.index)).fillna("").astype(str)
        + "|"
        + df.get("company", pd.Series("", index=df.index)).fillna("").astype(str)
    )
    key = url.where(url != "", fallback)
    df = df.loc[~key.duplicated()]
    return df.drop_duplicates(subset=["title", "company", "location"]).reset_index(drop=True)


# Per-board search URLs used when a scraper couldn't extract a direct link —
# every row must end up with a clickable URL that lands on/near the job.
_SITE_SEARCH_URLS: dict[str, str] = {
    "LinkedIn":  "https://www.linkedin.com/jobs/search/?keywords={q}",
    "Indeed":    "https://www.indeed.com/jobs?q={q}",
    "Naukri":    "https://www.naukri.com/jobs-search?k={q}",
    "Seek":      "https://www.seek.com.au/jobs?keywords={q}",
    "JobStreet": "https://www.jobstreet.com.my/jobs?keywords={q}",
    "Bayt":      "https://www.bayt.com/en/jobs/?text={q}",
    "Reed":      "https://www.reed.co.uk/jobs/search?keywords={q}",
    "Rozee":     "https://rozee.pk/job/jsearch/q/{q}",
}


def _ensure_job_urls(df: pd.DataFrame) -> pd.DataFrame:
    """Fill empty job_url cells with a board search link for title+company.
    Also rejects non-http(s) URLs — hrefs come from scraped pages, so a
    malicious posting could otherwise plant javascript:/data: links that end
    up on the UI Apply button and the Excel hyperlink."""
    if df.empty or "job_url" not in df.columns:
        return df

    def _fill(row):
        url = str(row.get("job_url") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            return url
        q    = quote_plus(f"{row.get('title', '')} {row.get('company', '')}".strip())
        tmpl = _SITE_SEARCH_URLS.get(str(row.get("site", "")))
        return tmpl.format(q=q) if tmpl else f"https://www.google.com/search?q={q}"

    df = df.copy()
    df["job_url"] = df.apply(_fill, axis=1)
    return df


def _interleave(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Round-robin rows across the groups in `col` (site or searched_keyword) so
    that truncating to max_results doesn't keep only whichever group finished
    first and crowd out the rest.
    """
    if df.empty or col not in df.columns or df[col].nunique() < 2:
        return df
    return (
        df.assign(_rr=df.groupby(col).cumcount())
          .sort_values("_rr", kind="stable")
          .drop(columns="_rr")
          .reset_index(drop=True)
    )


# ── Salary extraction from free-text descriptions ─────────────────────────────
# Most boards don't expose structured salary; many postings state it in prose.
# Amount must be ≥4 digits, thousands-separated, or k/LPA-suffixed — a bare
# "$5" or "2" must not match.
_SAL_CUR = r"(?:[$€£₹]|USD|EUR|GBP|INR|AUD|CAD|SGD|AED|PKR)"
_SAL_AMT = r"(?:\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?\s?[kK]|\d{4,7})"
_SALARY_RE = re.compile(
    rf"{_SAL_CUR}\s?{_SAL_AMT}(?:\s?(?:-|–|to)\s?{_SAL_CUR}?\s?{_SAL_AMT})?"
    rf"(?:\s?(?:per|/|a)\s?(?:year|annum|month|week|hour|yr|mo|hr))?"
    rf"|\b\d{{1,2}}(?:\.\d)?\s?(?:-|–|to)\s?\d{{1,2}}(?:\.\d)?\s?LPA\b"
    rf"|\b\d{{1,2}}(?:\.\d)?\s?LPA\b",
    re.IGNORECASE,
)


def _extract_salary_text(text: str) -> str:
    m = _SALARY_RE.search(text or "")
    return m.group(0).strip() if m else ""


def _fill_salary_text(df: pd.DataFrame) -> pd.DataFrame:
    """Fill empty salary_text cells from a salary statement found in the
    description, so the salary column/sort works beyond Remotive/Jobicy."""
    if df.empty or "description" not in df.columns:
        return df
    df = df.copy()
    if "salary_text" not in df.columns:
        df["salary_text"] = None
    cur  = df["salary_text"].fillna("").astype(str).str.strip()
    need = (cur == "") | (cur == "None")
    df.loc[need, "salary_text"] = [
        _extract_salary_text(d) or None
        for d in df.loc[need, "description"].fillna("")
    ]
    return df


def _filter_by_age(df: pd.DataFrame, hours_old: int) -> pd.DataFrame:
    """
    Drop rows whose date_posted is older than the cutoff. Rows without a date
    pass through — most boards don't expose posting dates, and dropping them
    would empty the results.
    """
    if df.empty or "date_posted" not in df.columns:
        return df
    cutoff = (datetime.now() - timedelta(hours=hours_old)).strftime("%Y-%m-%d")
    dates = df["date_posted"].fillna("").astype(str).str.slice(0, 10)
    return df[(dates == "") | (dates >= cutoff)].reset_index(drop=True)


def fetch_job_page_texts(urls: list, workers: int = 10, max_chars: int = 6000) -> list:
    """
    Fetch each job page and return its visible text, position-aligned with
    `urls` ('' on any failure). Used for on-the-fly ATS keyword scoring of
    boards whose cards carry no description (Bayt/Reed/Rozee/Indeed) — the
    caller extracts skills and DISCARDS the text; it is never stored.

    Single attempt + short timeout: this is best-effort enrichment and must
    not stall a search behind a blocking board.
    """
    tls = threading.local()

    def get_session() -> requests.Session:
        if getattr(tls, "session", None) is None:
            s = requests.Session()
            s.headers.update(_HEADERS)
            tls.session = s
        return tls.session

    def fetch_one(i: int, url: str):
        if not str(url or "").lower().startswith(("http://", "https://")):
            return i, ""
        r = _get_with_retry(get_session(), url, max_attempts=1, timeout=8)
        if r is None:
            return i, ""
        soup = BeautifulSoup(r.text, _BS_PARSER)
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        return i, text[:max_chars]

    results = [""] * len(urls)
    if not urls:
        return results
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(urls)))) as pool:
        futures = [pool.submit(fetch_one, i, u) for i, u in enumerate(urls)]
        for fut in as_completed(futures):
            try:
                i, text = fut.result()
                results[i] = text
            except Exception as e:
                logger.warning(f"Job-page text fetch failed: {e}")
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def search_jobs(
    keyword: str,
    location: str,
    max_results: int = 30,
    hours_old: int = 168,
    sites: list = None,
    remote_only: bool = False,
    fetch_full_descriptions: bool = True,
    desc_workers: int = 5,
    country: str = "",
    **_,
) -> pd.DataFrame:
    """
    Search jobs across multiple boards in parallel.

    Args:
        keyword:                 Job title / keywords.
        location:                Location string.
        max_results:             Total jobs to return after deduplication.
        hours_old:               Skip jobs older than this many hours.
        sites:                   Which boards to search.
        remote_only:             Keep only remote positions.
        fetch_full_descriptions: Fetch full description for each LinkedIn job.
        desc_workers:            Parallel threads for LinkedIn description fetching.
        country:                 Country name — used to pick JobStreet/Bayt sub-region.

    Returns:
        pd.DataFrame — empty (never None) when nothing is found.
    """
    if sites is None:
        sites = ["linkedin", "indeed"]

    jobstreet_key = _JOBSTREET_COUNTRY_KEYS.get(country, "MY-Main")
    bayt_slug     = _BAYT_COUNTRY_SLUGS.get(country, "international")

    scraper_map = {
        "linkedin":  lambda: _linkedin_search(
            keyword, location, max_results, hours_old,
            fetch_full_descriptions, desc_workers, remote_only,
        ),
        "indeed":    lambda: _indeed_search(keyword, location, max_results, hours_old),
        "remoteok":  lambda: _remoteok_search(keyword, location, max_results, hours_old),
        "remotive":  lambda: _remotive_search(keyword, location, max_results, hours_old),
        "jobicy":    lambda: _jobicy_search(keyword, location, max_results, hours_old),
        "arbeitnow": lambda: _arbeitnow_search(keyword, location, max_results, hours_old),
        "themuse":   lambda: _muse_search(keyword, location, max_results, hours_old),
        "naukri":    lambda: _naukri_search(keyword, location, max_results, hours_old),
        "seek":      lambda: _seek_search(keyword, location, max_results, hours_old),
        "jobstreet": lambda: _jobstreet_search(
            keyword, location, max_results, hours_old, jobstreet_key
        ),
        "bayt":      lambda: _bayt_search(keyword, location, max_results, hours_old, bayt_slug),
        "reed":      lambda: _reed_search(keyword, location, max_results, hours_old),
        "rozee":     lambda: _rozee_search(keyword, location, max_results, hours_old),
        "adzuna":    lambda: _adzuna_search(keyword, location, max_results, hours_old, country),
        "jooble":    lambda: _jooble_search(keyword, location, max_results, hours_old),
    }

    frames: list[pd.DataFrame] = []

    with ThreadPoolExecutor(max_workers=max(1, len(sites))) as pool:
        futures = {
            pool.submit(scraper_map[s]): s
            for s in sites if s in scraper_map
        }
        for fut in as_completed(futures):
            site = futures[fut]
            try:
                df = fut.result()
                if not df.empty:
                    frames.append(df)
            except Exception as e:
                logger.error(f"{site} scraper raised an exception: {e}")

    if not frames:
        logger.warning("All scrapers returned 0 results.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _filter_by_age(combined, hours_old)
    combined = _dedupe(combined)
    combined = _ensure_job_urls(combined)
    combined = _fill_salary_text(combined)

    if remote_only and "is_remote" in combined.columns:
        combined = combined[combined["is_remote"] == True].reset_index(drop=True)

    combined = _interleave(combined, "site")
    return combined.head(max_results).reset_index(drop=True)


def search_jobs_multi(
    keywords: list[str],
    location: str,
    max_results: int = 30,
    hours_old: int = 168,
    sites: list = None,
    remote_only: bool = False,
    fetch_full_descriptions: bool = True,
    desc_workers: int = 5,
    country: str = "",
) -> pd.DataFrame:
    """
    Search multiple job titles and merge the results.

    Each keyword gets an equal share of max_results. Two keyword searches
    run concurrently (capped to avoid rate-limiting LinkedIn/other boards).
    The description-fetch thread pool is divided evenly across keywords so
    the total parallel outbound requests stay reasonable.

    Returns a DataFrame with an extra `searched_keyword` column.
    """
    keywords = [k for k in keywords if k and k.strip()]
    if not keywords:
        return pd.DataFrame()

    per_kw = max(5, -(-max_results // len(keywords)))    # ceiling division
    kw_workers = max(2, desc_workers // max(1, len(keywords)))

    def _search_one(kw: str) -> pd.DataFrame:
        df = search_jobs(
            keyword=kw,
            location=location,
            max_results=per_kw,
            hours_old=hours_old,
            sites=sites,
            remote_only=remote_only,     # must reach LinkedIn's f_WT param
            fetch_full_descriptions=fetch_full_descriptions,
            desc_workers=kw_workers,
            country=country,
        )
        if not df.empty:
            df = df.copy()
            df["searched_keyword"] = kw
        return df

    frames: list[pd.DataFrame] = []

    # Cap at 2 concurrent keyword searches to stay polite to rate-limiters
    with ThreadPoolExecutor(max_workers=min(2, len(keywords))) as pool:
        futures = {pool.submit(_search_one, kw): kw for kw in keywords}
        for fut in as_completed(futures):
            kw = futures[fut]
            try:
                df = fut.result()
                if df is not None and not df.empty:
                    frames.append(df)
            except Exception as e:
                logger.error(f"search_jobs_multi: '{kw}' failed: {e}")

    if not frames:
        logger.warning("search_jobs_multi: all keywords returned 0 results.")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = _dedupe(combined)

    if remote_only and "is_remote" in combined.columns:
        combined = combined[combined["is_remote"] == True].reset_index(drop=True)

    combined = _interleave(combined, "searched_keyword")
    return combined.head(max_results).reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
# LinkedIn scraper
# ──────────────────────────────────────────────────────────────────────────────

_LI_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
_LI_JOB    = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"

_LI_CARD_SELECTORS = [
    ("div",  {"class": "base-card"}),
    ("div",  {"class": "job-search-card"}),
    ("li",   {"class": re.compile(r"jobs-search__results-list")}),
    ("div",  {"class": re.compile(r"base-card")}),
    ("li",   {"class": re.compile(r"result-card")}),
    ("div",  {"data-entity-urn": True}),
]

_LI_TITLE_SELS   = ["h3.base-search-card__title", "h3", "span[aria-hidden]"]
_LI_COMPANY_SELS = ["h4.base-search-card__subtitle", "h4", ".base-search-card__info h4"]
_LI_LOC_SELS     = ["span.job-search-card__location", ".job-search-card__location"]
_LI_LINK_SELS    = ["a.base-card__full-link", "a[href*='/jobs/view/']"]

_LI_JOB_ID_RE = re.compile(r"/(\d{7,19})(?:[/?]|$)")


def _linkedin_search(keyword, location, max_results, hours_old, fetch_desc,
                     desc_workers, remote_only=False):
    session = requests.Session()
    session.headers.update(_HEADERS)

    jobs   = []
    start  = 0
    cutoff = datetime.now() - timedelta(hours=hours_old)
    # The guest API returns ~10 cards per page regardless of the requested
    # count — paginate by observed card count, capped to stay polite.
    pages_cap = max(1, min(10, math.ceil(max_results / 10)))

    for page in range(pages_cap):
        if len(jobs) >= max_results:
            break

        params = {
            "keywords": keyword,
            "location": location,
            "start":    start,
            "count":    25,
            "f_TPR":    f"r{hours_old * 3600}",
        }
        if remote_only:
            params["f_WT"] = "2"   # LinkedIn workplace-type filter: remote
        r = _get_with_retry(session, _LI_SEARCH, params=params)
        if r is None or len(r.text) < 200:
            logger.warning("LinkedIn: empty or failed response")
            break

        soup  = BeautifulSoup(r.text, _BS_PARSER)
        cards = _li_find_cards(soup)

        if not cards:
            logger.warning(
                f"LinkedIn: 0 cards on page {page + 1} "
                f"(body={len(r.text)} chars). "
                "The site may be blocking requests or class names have changed."
            )
            break

        prev = len(jobs)
        for card in cards:
            job = _li_parse_card(card, cutoff)
            if job:
                jobs.append(job)
            if len(jobs) >= max_results:
                break

        if len(jobs) == prev and len(cards) > 0:
            logger.warning(
                f"LinkedIn: all {len(cards)} cards on page {page + 1} were "
                "dropped (older than the date window or unparseable) — stopping"
            )
            break

        start += len(cards)
        if len(cards) < 10:
            break

        time.sleep(random.uniform(1.2, 2.5))

    logger.info(f"LinkedIn: {len(jobs)} listings collected")

    if remote_only:
        # f_WT=2 already filtered server-side — don't let the downstream
        # text-based is_remote check throw these rows away.
        for j in jobs:
            j["is_remote"] = True

    if fetch_desc and jobs:
        jobs = _fetch_descriptions_parallel(jobs, desc_workers)

    return _to_dataframe(jobs, "LinkedIn")


def _fetch_descriptions_parallel(jobs: list, workers: int) -> list:
    # requests.Session is not thread-safe — give each worker its own.
    tls = threading.local()

    def get_session() -> requests.Session:
        if getattr(tls, "session", None) is None:
            s = requests.Session()
            s.headers.update(_HEADERS)
            tls.session = s
        return tls.session

    def fetch_one(idx_job):
        idx, job = idx_job
        if not job.get("job_id"):
            return idx, {}
        time.sleep(random.uniform(0.2, 0.6))  # polite delay inside the worker
        r = _get_with_retry(get_session(), _LI_JOB.format(job_id=job["job_id"]), max_attempts=2)
        if r is None:
            return idx, {}
        soup    = BeautifulSoup(r.text, _BS_PARSER)
        desc_el = soup.find("div", class_="show-more-less-html__markup") or \
                  soup.find("div", class_=re.compile(r"description__text"))
        desc    = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

        criteria: dict = {}
        for li in soup.find_all("li", class_=re.compile(r"description__job-criteria")):
            h = li.find(["h3", "dt"])
            v = li.find(["span", "dd"]) or li.find("span")
            if h and v:
                criteria[h.get_text(strip=True)] = v.get_text(strip=True)

        is_remote = (
            bool(job.get("is_remote"))   # keep the server-side f_WT flag
            or "remote" in desc.lower()
            or "remote" in criteria.get("Work type", "").lower()
        )
        return idx, {
            "description": desc,
            "job_type":    criteria.get("Employment type", ""),
            "job_level":   criteria.get("Seniority level", ""),
            "is_remote":   is_remote,
        }

    logger.info(f"Fetching {len(jobs)} descriptions with {workers} workers ...")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, ij): ij[0] for ij in enumerate(jobs)}
        for fut in as_completed(futures):
            try:
                idx, details = fut.result()
                if details:
                    jobs[idx].update(details)
            except Exception as e:
                logger.warning(f"Description fetch failed: {e}")

    return jobs


def _li_find_cards(soup: BeautifulSoup) -> list:
    for tag, attrs in _LI_CARD_SELECTORS:
        cards = soup.find_all(tag, attrs)
        if cards:
            return cards
    return []


def _li_sel_first(tag, selectors: list):
    for sel in selectors:
        el = tag.select_one(sel)
        if el:
            return el
    return None


def _li_parse_card(card, cutoff: datetime):
    title_el   = _li_sel_first(card, _LI_TITLE_SELS)
    company_el = _li_sel_first(card, _LI_COMPANY_SELS)
    loc_el     = _li_sel_first(card, _LI_LOC_SELS)
    time_el    = card.find("time")
    link_el    = _li_sel_first(card, _LI_LINK_SELS)

    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        return None

    link = job_id = ""
    if link_el:
        link = link_el.get("href", "").split("?")[0]
        m = _LI_JOB_ID_RE.search(link)
        if m:
            job_id = m.group(1)

    posted_str = ""
    if time_el:
        posted_str = time_el.get("datetime", "")
        if posted_str:
            try:
                # Date-granularity comparison only: the card timestamp is
                # date-only (midnight), so comparing against an intra-day
                # cutoff silently drops every job posted "today" when the
                # search window is < 24h. f_TPR already filters by hour
                # server-side; this is just a safety net.
                if datetime.strptime(posted_str[:10], "%Y-%m-%d").date() < cutoff.date():
                    return None
            except ValueError:
                pass

    return {
        "title":       title,
        "company":     company_el.get_text(strip=True) if company_el else "",
        "location":    loc_el.get_text(strip=True)     if loc_el     else "",
        "date_posted": posted_str[:10],
        "job_url":     link,
        "job_id":      job_id,
        "description": "",
        "job_type":    "",
        "job_level":   "",
        "is_remote":   False,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Indeed scraper
# ──────────────────────────────────────────────────────────────────────────────

_INDEED_TITLE_SELS   = ["span[id^='jobTitle']", "h2.jobTitle span", "h2 span[title]", "h2"]
_INDEED_COMPANY_SELS = ["[data-testid='company-name']", "span.companyName", ".companyName"]
_INDEED_LOC_SELS     = ["[data-testid='text-location']", "div.companyLocation", ".companyLocation"]


def _indeed_playwright_jobs(keyword: str, location: str, max_results: int, hours_old: int) -> list:
    """
    Scrape Indeed.com using headless Playwright Chromium.
    Bypasses Cloudflare JS challenge that defeats curl_cffi.
    """
    from urllib.parse import quote as _quote
    age_days = max(1, min(hours_old // 24, 30))
    jobs: list = []

    with _sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )
        # Block images/fonts to speed up page loads
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}", lambda r: r.abort())
        pg = ctx.new_page()
        # Hide automation flag
        pg.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        start = 0
        while len(jobs) < max_results:
            url = (
                f"https://www.indeed.com/jobs"
                f"?q={_quote(keyword)}&l={_quote(location)}"
                f"&fromage={age_days}&start={start}"
            )
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=30_000)
                pg.wait_for_selector("[data-jk], .job_seen_beacon", timeout=12_000)
            except Exception as e:
                logger.warning(f"Indeed Playwright: page load failed — {e}")
                break

            html = pg.content()
            soup = BeautifulSoup(html, _BS_PARSER)

            cards = soup.select("div[data-jk]") or soup.select("div.job_seen_beacon")
            if not cards:
                logger.warning("Indeed Playwright: no job cards found on page")
                break

            prev = len(jobs)
            for card in cards:
                title_el   = _sel_first(card, _INDEED_TITLE_SELS)
                company_el = _sel_first(card, _INDEED_COMPANY_SELS)
                loc_el     = _sel_first(card, _INDEED_LOC_SELS)

                title = title_el.get_text(strip=True) if title_el else ""
                if not title or title.lower() in ("new", ""):
                    continue

                # data-jk may sit on the card div OR on the title anchor
                jk = card.get("data-jk", "")
                if not jk:
                    a_jk = card.select_one("a[data-jk]")
                    jk = a_jk.get("data-jk", "") if a_jk else ""
                if jk:
                    job_url = f"https://www.indeed.com/viewjob?jk={jk}"
                else:
                    a = card.select_one("a[href*='viewjob'], a[href*='/rc/clk'], h2 a[href]")
                    href = a.get("href", "") if a else ""
                    job_url = ("https://www.indeed.com" + href) if href.startswith("/") else href

                jobs.append({
                    "title":       title,
                    "company":     company_el.get_text(strip=True) if company_el else "",
                    "location":    loc_el.get_text(strip=True) if loc_el else location,
                    "date_posted": "",
                    "job_url":     job_url,
                    "job_id":      jk,
                    "description": "",
                    "job_type":    "",
                    "job_level":   "",
                    "is_remote":   False,
                })
                if len(jobs) >= max_results:
                    break

            if len(jobs) == prev:
                break

            next_btn = (
                soup.select_one("a[data-testid='pagination-page-next']")
                or soup.select_one("a[aria-label='Next Page']")
                or soup.select_one("a[aria-label='Next']")
            )
            if not next_btn:
                break

            start += len(cards)
            time.sleep(random.uniform(2.5, 4.0))

        browser.close()

    return jobs


def _indeed_search(keyword, location, max_results, hours_old):
    """
    Fetch Indeed jobs via headless Playwright Chromium — the only method that
    passes Indeed's Cloudflare JS challenge. The old RSS feed is discontinued
    and TLS impersonation (curl_cffi) still gets the "Security Check" page.
    Install:  pip install playwright && playwright install chromium
    """
    if not _PLAYWRIGHT_AVAILABLE:
        logger.warning(
            "Indeed: Playwright not installed — Indeed's Cloudflare JS challenge "
            "blocks plain HTTP requests, so this board is skipped.  "
            "Install: pip install playwright && playwright install chromium"
        )
        return _to_dataframe([], "Indeed")

    logger.info("Indeed: using Playwright headless browser (bypasses JS challenge)")
    jobs = _indeed_playwright_jobs(keyword, location, max_results, hours_old)
    logger.info(f"Indeed: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Indeed")


def _sel_first(tag, selectors: list):
    for sel in selectors:
        el = tag.select_one(sel)
        if el:
            return el
    return None


# ──────────────────────────────────────────────────────────────────────────────
# RemoteOK scraper  (global remote jobs — free public JSON API, no auth needed)
# ──────────────────────────────────────────────────────────────────────────────

_REMOTEOK_API = "https://remoteok.com/api"


def _remoteok_search(keyword, location, max_results, hours_old):
    """
    RemoteOK open JSON API — no Cloudflare, no auth, no API key required.
    Tag-filtered results naturally span 30-90 days regardless of hours_old,
    so we skip the strict date cutoff and just return the freshest N jobs.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers["Accept"] = "application/json"

    # RemoteOK tag search — try full keyword slug first (e.g. "machine-learning"),
    # fall back to first word if that returns no results (e.g. "python").
    full_tag  = _slugify(keyword)
    first_tag = _slugify(keyword.split()[0]) if keyword.strip() else full_tag

    r = _get_with_retry(session, _REMOTEOK_API, params={"tag": full_tag})
    if r is None:
        logger.warning("RemoteOK: request failed")
        return _to_dataframe([], "RemoteOK")

    # If the full slug returned only the metadata row (no jobs), retry with first word
    try:
        _probe = r.json()
        if isinstance(_probe, list) and len(_probe) < 2 and full_tag != first_tag:
            r2 = _get_with_retry(session, _REMOTEOK_API, params={"tag": first_tag})
            if r2 is not None:
                r = r2
    except Exception:
        pass

    if r is None:
        logger.warning("RemoteOK: request failed")
        return _to_dataframe([], "RemoteOK")

    try:
        data = r.json()
    except Exception:
        logger.warning("RemoteOK: JSON parse error")
        return _to_dataframe([], "RemoteOK")

    # index 0 = legal/metadata notice — skip it
    if not isinstance(data, list) or len(data) < 2:
        logger.info("RemoteOK: no results for this tag")
        return _to_dataframe([], "RemoteOK")

    # RemoteOK returns jobs sorted newest-first already.
    # We skip strict hours_old filtering because tag pools span 30-90 days
    # and a hard 7-day cutoff would return almost nothing.
    jobs: list = []

    for item in data[1:]:
        if not isinstance(item, dict):
            continue
        title = item.get("position", "")
        if not title:
            continue

        epoch = item.get("epoch", 0)
        date_posted = ""
        if epoch:
            try:
                date_posted = datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d")
            except Exception:
                pass

        desc_raw = item.get("description", "") or ""
        desc = re.sub(r"<[^>]+>", " ", desc_raw)
        desc = re.sub(r"\s+", " ", desc).strip()

        jobs.append({
            "title":       title,
            "company":     item.get("company", ""),
            "location":    item.get("location", "Remote") or "Remote",
            "date_posted": date_posted,
            "job_url":     item.get("url", ""),
            "job_id":      str(item.get("id", "")),
            "description": desc[:800],
            "job_type":    "Full-time",
            "job_level":   "",
            "is_remote":   True,
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"RemoteOK: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "RemoteOK")


# ──────────────────────────────────────────────────────────────────────────────
# Remotive scraper  (global remote jobs — open JSON API, keyword search, no key)
# ──────────────────────────────────────────────────────────────────────────────

_REMOTIVE_API = "https://remotive.com/api/remote-jobs"


def _remotive_search(keyword, location, max_results, hours_old):
    session = _json_session()
    r = _get_with_retry(
        session, _REMOTIVE_API,
        params={"search": keyword, "limit": max(max_results, 20)},
    )
    if r is None:
        logger.warning("Remotive: request failed")
        return _to_dataframe([], "Remotive")

    try:
        items = r.json().get("jobs", [])
    except Exception:
        logger.warning("Remotive: JSON parse error")
        return _to_dataframe([], "Remotive")

    jobs: list = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        jobs.append({
            "title":       title,
            "company":     item.get("company_name", ""),
            "location":    item.get("candidate_required_location", "Remote") or "Remote",
            "date_posted": str(item.get("publication_date", ""))[:10],
            "job_url":     item.get("url", ""),
            "job_id":      str(item.get("id", "")),
            "description": _strip_html(item.get("description", ""))[:800],
            "job_type":    str(item.get("job_type", "")).replace("_", " ").title(),
            "job_level":   "",
            "is_remote":   True,
            "salary_text": item.get("salary", "") or "",
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"Remotive: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Remotive")


# ──────────────────────────────────────────────────────────────────────────────
# Jobicy scraper  (global remote jobs — open JSON API with region filter, no key)
# ──────────────────────────────────────────────────────────────────────────────

_JOBICY_API = "https://jobicy.com/api/v2/remote-jobs"

# Our location strings → Jobicy geo keys
_JOBICY_GEO: dict[str, str] = {
    "worldwide":      "anywhere",
    "united states":  "usa",
    "european union": "europe",
    "asia":           "apac",
    "latin america":  "latam",
    "united kingdom": "uk",
    "canada":         "canada",
}


def _jobicy_search(keyword, location, max_results, hours_old):
    session = _json_session()
    params = {"count": min(max(max_results, 20), 50), "tag": keyword}
    geo = _JOBICY_GEO.get((location or "").strip().lower(), "")
    if geo and geo != "anywhere":
        params["geo"] = geo

    r = _get_with_retry(session, _JOBICY_API, params=params)
    if r is None:
        logger.warning("Jobicy: request failed")
        return _to_dataframe([], "Jobicy")

    try:
        items = r.json().get("jobs", [])
    except Exception:
        logger.warning("Jobicy: JSON parse error")
        return _to_dataframe([], "Jobicy")
    if not isinstance(items, list):
        items = []

    jobs: list = []
    for item in items:
        title = item.get("jobTitle", "")
        if not title:
            continue

        jt = item.get("jobType", "")
        job_type = ", ".join(jt) if isinstance(jt, list) else str(jt or "")

        lo, hi = item.get("annualSalaryMin"), item.get("annualSalaryMax")
        curr   = item.get("salaryCurrency", "") or ""
        salary_text = ""
        if lo or hi:
            rng = " – ".join(str(int(v)) for v in (lo, hi) if v)
            salary_text = f"{curr} {rng}/yr".strip()

        jobs.append({
            "title":       title,
            "company":     item.get("companyName", ""),
            "location":    item.get("jobGeo", "Remote") or "Remote",
            "date_posted": str(item.get("pubDate", ""))[:10],
            "job_url":     item.get("url", ""),
            "job_id":      str(item.get("id", "")),
            "description": _strip_html(item.get("jobDescription", "") or item.get("jobExcerpt", ""))[:800],
            "job_type":    job_type,
            "job_level":   item.get("jobLevel", "") or "",
            "is_remote":   True,
            "salary_text": salary_text,
            "min_amount":  lo,
            "max_amount":  hi,
            "currency":    curr,
            "interval":    "yearly" if (lo or hi) else None,
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"Jobicy: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Jobicy")


# ──────────────────────────────────────────────────────────────────────────────
# Arbeitnow scraper  (Germany / EU — open JSON API feed, no key)
# ──────────────────────────────────────────────────────────────────────────────

_ARBEITNOW_API = "https://www.arbeitnow.com/api/job-board-api"


def _arbeitnow_search(keyword, location, max_results, hours_old):
    """
    Arbeitnow exposes a paginated feed without a search parameter, so the
    keyword is matched client-side: every word must appear in title+tags+desc.
    """
    session = _json_session()
    kw_words = [w for w in keyword.lower().split() if len(w) > 2]

    jobs: list = []
    page = 1
    while len(jobs) < max_results and page <= 5:
        r = _get_with_retry(session, _ARBEITNOW_API, params={"page": page})
        if r is None:
            break
        try:
            items = r.json().get("data", [])
        except Exception:
            logger.warning("Arbeitnow: JSON parse error")
            break
        if not items:
            break

        for item in items:
            title = item.get("title", "")
            if not title:
                continue
            desc = _strip_html(item.get("description", ""))
            hay  = " ".join([
                title,
                " ".join(item.get("tags", []) or []),
                desc[:600],
            ]).lower()
            if kw_words and not all(w in hay for w in kw_words):
                continue

            date_posted = ""
            try:
                date_posted = datetime.fromtimestamp(int(item.get("created_at", 0))).strftime("%Y-%m-%d")
            except Exception:
                pass

            jobs.append({
                "title":       title,
                "company":     item.get("company_name", ""),
                "location":    item.get("location", "") or "Germany",
                "date_posted": date_posted,
                "job_url":     item.get("url", ""),
                "job_id":      item.get("slug", ""),
                "description": desc[:800],
                "job_type":    ", ".join(item.get("job_types", []) or []),
                "job_level":   "",
                "is_remote":   bool(item.get("remote")),
            })
            if len(jobs) >= max_results:
                break

        page += 1
        time.sleep(random.uniform(0.3, 0.8))

    logger.info(f"Arbeitnow: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Arbeitnow")


# ──────────────────────────────────────────────────────────────────────────────
# The Muse scraper  (US / global — open JSON API, no key)
# ──────────────────────────────────────────────────────────────────────────────

_MUSE_API = "https://www.themuse.com/api/public/jobs"


def _muse_location_ok(job_locs: list, location: str) -> bool:
    if not location:
        return True
    loc_l = location.lower()
    city  = location.split(",")[0].strip().lower()
    for jl in job_locs:
        jll = jl.lower()
        if "remote" in jll or (city and city in jll) or jll.endswith(loc_l):
            return True
    # Entire-country US search: Muse lists US locations as "City, ST"
    if loc_l == "united states":
        return any(re.search(r", [a-z]{2}$", jl.lower()) for jl in job_locs)
    return False


def _muse_search(keyword, location, max_results, hours_old):
    """
    The Muse API has no free-text search, so pages are scanned and matched
    client-side: every keyword word must appear in the job name + description.
    """
    session  = _json_session()
    kw_words = [w for w in keyword.lower().split() if len(w) > 2]

    jobs: list = []
    page = 0
    while len(jobs) < max_results and page < 4:
        r = _get_with_retry(session, _MUSE_API, params={"page": page})
        if r is None:
            break
        try:
            data = r.json()
        except Exception:
            logger.warning("The Muse: JSON parse error")
            break
        items = data.get("results", [])
        if not items:
            break

        for item in items:
            title = item.get("name", "")
            if not title:
                continue
            contents = _strip_html(item.get("contents", ""))
            hay = (title + " " + contents[:1500]).lower()
            if kw_words and not all(w in hay for w in kw_words):
                continue

            job_locs = [l.get("name", "") for l in item.get("locations", []) or []]
            if not _muse_location_ok(job_locs, location):
                continue

            levels = [l.get("name", "") for l in item.get("levels", []) or []]
            jobs.append({
                "title":       title,
                "company":     (item.get("company") or {}).get("name", ""),
                "location":    "; ".join(job_locs[:3]),
                "date_posted": str(item.get("publication_date", ""))[:10],
                "job_url":     (item.get("refs") or {}).get("landing_page", ""),
                "job_id":      str(item.get("id", "")),
                "description": contents[:800],
                "job_type":    "",
                "job_level":   ", ".join(levels),
                "is_remote":   any("remote" in jl.lower() for jl in job_locs),
            })
            if len(jobs) >= max_results:
                break

        if page + 1 >= int(data.get("page_count", 1)):
            break
        page += 1
        time.sleep(random.uniform(0.3, 0.8))

    logger.info(f"The Muse: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "The Muse")


# ──────────────────────────────────────────────────────────────────────────────
# Naukri.com scraper  (India)
# ──────────────────────────────────────────────────────────────────────────────

def _naukri_playwright_jobs(keyword: str, location: str, max_results: int, hours_old: int) -> list:
    """
    Scrape Naukri.com using headless Playwright Chromium.
    Required because Naukri's JSON API enforces reCAPTCHA (406) and the HTML
    page is a Next.js app that hydrates job cards entirely client-side.
    """
    jobs: list = []
    kw_slug  = _slugify(keyword)
    # Naukri URLs use only the city — strip any ", Country" suffix
    city_only = location.split(",")[0].strip() if location else ""
    loc_slug  = _slugify(city_only) if city_only else "india"

    with _sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        ctx = browser.new_context(
            user_agent=_HEADERS["User-Agent"],
            locale="en-IN",
            viewport={"width": 1280, "height": 900},
        )
        ctx.route("**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf}", lambda r: r.abort())
        pg = ctx.new_page()
        pg.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = 1
        while len(jobs) < max_results:
            # Naukri SEO URL pattern: /python-jobs-in-bengaluru or /python-jobs-in-bengaluru-2
            suffix = f"-{page}" if page > 1 else ""
            url = f"https://www.naukri.com/{kw_slug}-jobs-in-{loc_slug}{suffix}"

            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Wait for React hydration to populate job tuples
                pg.wait_for_selector(
                    "article.jobTupleHeader, .srp-jobtuple-wrapper, article[data-job-id]",
                    timeout=15_000,
                )
            except Exception as e:
                logger.warning(f"Naukri Playwright: page load failed — {e}")
                break

            html = pg.content()
            soup = BeautifulSoup(html, _BS_PARSER)

            cards = (
                soup.select("article.jobTupleHeader")
                or soup.select(".srp-jobtuple-wrapper")
                or soup.select("article[data-job-id]")
                or soup.select(".cust-job-tuple")
            )
            if not cards:
                logger.warning("Naukri Playwright: 0 cards — page structure may differ")
                break

            prev = len(jobs)
            for card in cards:
                title_el   = (card.select_one("a.title")
                              or card.select_one(".row1 a")
                              or card.select_one("h2 a"))
                company_el = (card.select_one("a.comp-name")
                              or card.select_one(".comp-name"))
                loc_el     = (card.select_one(".locWdth")
                              or card.select_one("li.loc")
                              or card.select_one(".location"))
                exp_el     = (card.select_one(".expwdth")
                              or card.select_one("li.experience"))
                skills_el  = (card.select_one(".tags-gt")
                              or card.select_one(".skill-container"))

                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue

                href    = title_el.get("href", "") if title_el else ""
                job_url = href if href.startswith("http") else (
                    "https://www.naukri.com" + href if href else ""
                )
                job_id = card.get("data-job-id", "")
                skills = skills_el.get_text(separator=", ", strip=True) if skills_el else ""

                jobs.append({
                    "title":       title,
                    "company":     company_el.get_text(strip=True) if company_el else "",
                    "location":    loc_el.get_text(strip=True) if loc_el else location,
                    "date_posted": "",
                    "job_url":     job_url,
                    "job_id":      job_id,
                    "description": skills,
                    "job_type":    "",
                    "job_level":   exp_el.get_text(strip=True) if exp_el else "",
                    "is_remote":   False,
                })
                if len(jobs) >= max_results:
                    break

            if len(jobs) == prev:
                break

            next_btn = (
                soup.select_one("a[aria-label='Next']")
                or soup.select_one(".pagination-next a")
                or soup.select_one("button[aria-label='Next page']")
            )
            if not next_btn:
                break
            page += 1
            time.sleep(random.uniform(2.5, 4.0))

        browser.close()

    return jobs


def _naukri_search(keyword, location, max_results, hours_old):
    if _PLAYWRIGHT_AVAILABLE:
        logger.info("Naukri: using Playwright headless browser (bypasses reCAPTCHA gate)")
        jobs = _naukri_playwright_jobs(keyword, location, max_results, hours_old)
        logger.info(f"Naukri: {len(jobs)} listings collected")
        return _to_dataframe(jobs, "Naukri")

    logger.warning(
        "Naukri: Playwright not installed — Naukri enforces reCAPTCHA on its API "
        "and hydrates jobs client-side (Next.js). Plain requests always return 0 results.  "
        "Install: pip install playwright && playwright install chromium"
    )
    return _to_dataframe([], "Naukri")


# ──────────────────────────────────────────────────────────────────────────────
# Seek.com.au scraper  (Australia / New Zealand)
# ──────────────────────────────────────────────────────────────────────────────

def _seek_search(keyword, location, max_results, hours_old):
    return _seek_style_search(
        keyword, location, max_results, hours_old,
        base_domain="https://www.seek.com.au",
        site_key="AU-Main",
        label="Seek",
    )


# ──────────────────────────────────────────────────────────────────────────────
# JobStreet scraper  (Malaysia / Philippines / Singapore / Indonesia)
# ──────────────────────────────────────────────────────────────────────────────

_JOBSTREET_DOMAINS: dict[str, str] = {
    "MY-Main": "https://www.jobstreet.com.my",
    "PH-Main": "https://www.jobstreet.com.ph",
    "SG-Main": "https://sg.jobstreet.com",
    "ID-Main": "https://www.jobstreet.co.id",
}


def _jobstreet_search(keyword, location, max_results, hours_old, site_key="MY-Main"):
    domain = _JOBSTREET_DOMAINS.get(site_key, "https://www.jobstreet.com.my")
    return _seek_style_search(
        keyword, location, max_results, hours_old,
        base_domain=domain,
        site_key=site_key,
        label="JobStreet",
    )


def _seek_style_search(keyword, location, max_results, hours_old,
                       base_domain, site_key, label):
    """
    Try Seek/JobStreet private JSON API first; fall back to HTML + JSON-LD
    if the API returns a non-JSON response (happens when they add auth gates).
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers.update({
        "Referer":        base_domain + "/",
        "Accept":         "application/json, text/plain, */*",
        "X-Seek-Site":    site_key.split("-")[0],
    })

    api_url = f"{base_domain}/api/chalice-search/v4/search"
    jobs: list = []
    page = 1
    api_failed = False

    while len(jobs) < max_results:
        if api_failed:
            break

        params = {
            "siteKey":  site_key,
            "where":    location,
            "keywords": keyword,
            "pageSize": 20,
            "page":     page,
        }
        r = _get_with_retry(session, api_url, params=params)
        if r is None:
            logger.warning(f"{label}: API request failed — trying HTML fallback")
            api_failed = True
            break

        try:
            data = r.json()
        except Exception:
            logger.warning(f"{label}: API returned non-JSON — trying HTML fallback")
            api_failed = True
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            title = item.get("title", "")
            if not title:
                continue
            company  = (item.get("advertiser") or {}).get("description", "")
            loc      = item.get("location", location)
            job_id   = str(item.get("id", ""))
            job_url  = f"{base_domain}/job/{job_id}" if job_id else ""
            date_str = str(item.get("listingDate", ""))[:10]
            work_arr = str(item.get("workArrangement", "")).lower()
            jobs.append({
                "title":       title,
                "company":     company,
                "location":    loc,
                "date_posted": date_str,
                "job_url":     job_url,
                "job_id":      job_id,
                "description": item.get("teaser", ""),
                "job_type":    item.get("workType", ""),
                "job_level":   "",
                "is_remote":   "remote" in work_arr,
            })
            if len(jobs) >= max_results:
                break

        total_pages = data.get("totalPages", 1)
        if page >= total_pages or len(items) < 20:
            break
        page += 1
        time.sleep(random.uniform(1.0, 2.0))

    # ── HTML + JSON-LD fallback ───────────────────────────────────────────────
    if api_failed and len(jobs) < max_results:
        logger.info(f"{label}: using HTML + JSON-LD fallback")
        html_jobs = _seek_html_fallback(
            keyword, location, max_results, session, base_domain, label
        )
        jobs.extend(html_jobs)

    logger.info(f"{label} ({site_key}): {len(jobs)} listings collected")
    return _to_dataframe(jobs, label)


def _seek_html_fallback(keyword, location, max_results,
                        session: requests.Session, base_domain, label) -> list:
    """
    Fetch Seek/JobStreet HTML search pages and extract JSON-LD JobPosting objects
    embedded by the server.  Less data than the API but works when the API is gated.
    """
    session.headers["Accept"] = (
        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    )
    kw_slug = _slugify(keyword)
    jobs: list = []
    page = 1

    while len(jobs) < max_results:
        url    = f"{base_domain}/jobs/{kw_slug}"
        params = {"where": location, "page": page} if page > 1 else {"where": location}

        r = _get_with_retry(session, url, params=params)
        if r is None:
            break

        soup = BeautifulSoup(r.text, _BS_PARSER)

        # Extract all JSON-LD blocks — Seek embeds JobPosting structured data
        found_any = False
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                blob = json.loads(script.string or "")
            except Exception:
                continue
            # blob can be a single object or a list
            items = blob if isinstance(blob, list) else [blob]
            for item in items:
                if item.get("@type") != "JobPosting":
                    continue
                job = _parse_jsonld_jobposting(item, base_domain)
                if job:
                    jobs.append(job)
                    found_any = True
                if len(jobs) >= max_results:
                    break
            if len(jobs) >= max_results:
                break

        if not found_any:
            logger.warning(f"{label} HTML fallback: no JSON-LD found on page {page}")
            break

        next_btn = (soup.select_one("a[aria-label='Next page']")
                    or soup.select_one("a[rel='next']"))
        if not next_btn:
            break
        page += 1
        time.sleep(random.uniform(1.5, 2.5))

    return jobs


def _parse_jsonld_jobposting(data: dict, base_domain: str) -> Optional[dict]:
    title = data.get("title", "")
    if not title:
        return None
    org     = data.get("hiringOrganization") or {}
    company = org.get("name", "") if isinstance(org, dict) else ""
    jl      = data.get("jobLocation") or {}
    # jobLocation may be a list of locations — take the first entry
    if isinstance(jl, list):
        jl = jl[0] if jl else {}
    addr    = (jl.get("address") or {}) if isinstance(jl, dict) else {}
    loc     = ", ".join(filter(None, [
        addr.get("addressLocality", ""),
        addr.get("addressRegion", ""),
        addr.get("addressCountry", ""),
    ]))
    desc_raw = data.get("description", "")
    desc     = re.sub(r"<[^>]+>", " ", desc_raw)
    desc     = re.sub(r"\s+", " ", desc).strip()
    return {
        "title":       title,
        "company":     company,
        "location":    loc,
        "date_posted": str(data.get("datePosted", ""))[:10],
        "job_url":     data.get("url", "") or data.get("@id", ""),
        "job_id":      "",
        "description": desc[:800],
        "job_type":    data.get("employmentType", ""),
        "job_level":   "",
        "is_remote":   data.get("jobLocationType", "") == "TELECOMMUTE",
    }


# ──────────────────────────────────────────────────────────────────────────────
# Bayt.com scraper  (Middle East)
# ──────────────────────────────────────────────────────────────────────────────

def _bayt_search(keyword, location, max_results, hours_old, country_slug="international"):
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers["Referer"] = "https://www.bayt.com/"

    keyword_slug = _slugify(keyword)
    jobs: list   = []
    page = 1

    while len(jobs) < max_results:
        if country_slug == "international":
            base_url = f"https://www.bayt.com/en/international/jobs/{keyword_slug}-jobs/"
        else:
            base_url = f"https://www.bayt.com/en/{country_slug}/{keyword_slug}-jobs/"

        url = base_url if page == 1 else f"{base_url}?page={page}"

        r = _get_with_retry(session, url)
        if r is None:
            logger.warning("Bayt: request failed (possibly blocked)")
            break

        soup  = BeautifulSoup(r.text, _BS_PARSER)
        cards = (
            soup.find_all("li", {"data-js-job": True})
            or soup.select("div.jb-job-list-item")
            or soup.select("li.has-pointer-d")
        )

        if not cards:
            logger.warning("Bayt: 0 cards found — may be blocked or HTML changed")
            break

        for card in cards:
            title_el   = card.select_one("h2 a") or card.select_one("h2")
            company_el = (card.select_one("[data-automation-id='job-company']")
                          or card.select_one(".jb-company"))
            loc_el     = (card.select_one("[data-automation-id='job-location']")
                          or card.select_one(".jb-location"))
            link_el    = card.select_one("a[href*='/jobs/']") or card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            href    = link_el.get("href", "") if link_el else ""
            job_url = ("https://www.bayt.com" + href) if href.startswith("/") else href

            jobs.append({
                "title":       title,
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True) if loc_el else location,
                "date_posted": "",
                "job_url":     job_url,
                "job_id":      "",
                "description": "",
                "job_type":    "",
                "job_level":   "",
                "is_remote":   False,
            })
            if len(jobs) >= max_results:
                break

        next_btn = (soup.select_one("a[data-automation-id='paginator-next']")
                    or soup.select_one("a.pager-next")
                    or soup.select_one("a[aria-label='Next']"))
        if not next_btn:
            break
        page += 1
        time.sleep(random.uniform(2.0, 3.5))

    logger.info(f"Bayt: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Bayt")


# ──────────────────────────────────────────────────────────────────────────────
# Adzuna scraper  (global — official JSON API, free key required)
# ──────────────────────────────────────────────────────────────────────────────

_ADZUNA_COUNTRY_CODES: dict[str, str] = {
    "United Kingdom": "gb", "United States": "us", "Australia": "au",
    "Austria": "at", "Belgium": "be", "Brazil": "br", "Canada": "ca",
    "Switzerland": "ch", "Germany": "de", "Spain": "es", "France": "fr",
    "India": "in", "Italy": "it", "Mexico": "mx", "Netherlands": "nl",
    "New Zealand": "nz", "Poland": "pl", "Singapore": "sg", "South Africa": "za",
}


def _adzuna_search(keyword, location, max_results, hours_old, country=""):
    """Official Adzuna API — clean JSON with structured salary, no scraping.
    Needs free credentials from developer.adzuna.com:
    set ADZUNA_APP_ID and ADZUNA_APP_KEY env vars."""
    app_id  = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not (app_id and app_key):
        logger.warning(
            "Adzuna: skipped — set ADZUNA_APP_ID and ADZUNA_APP_KEY "
            "(free key at developer.adzuna.com)"
        )
        return _to_dataframe([], "Adzuna")

    cc = _ADZUNA_COUNTRY_CODES.get(country, "us")
    # When searching the entire country, the country code already scopes it.
    where = "" if (location or "").strip().lower() in ("", country.strip().lower(), "worldwide") \
            else location.split(",")[0].strip()

    session = _json_session()
    params = {
        "app_id": app_id, "app_key": app_key,
        "what": keyword, "results_per_page": min(max_results, 50),
        "max_days_old": max(1, hours_old // 24),
        "content-type": "application/json",
    }
    if where:
        params["where"] = where

    r = _get_with_retry(session, f"https://api.adzuna.com/v1/api/jobs/{cc}/search/1", params=params)
    if r is None:
        logger.warning("Adzuna: request failed")
        return _to_dataframe([], "Adzuna")
    try:
        items = r.json().get("results", [])
    except Exception:
        logger.warning("Adzuna: JSON parse error")
        return _to_dataframe([], "Adzuna")

    jobs: list = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        title = _strip_html(title)  # Adzuna wraps matches in <strong>
        lo, hi = item.get("salary_min"), item.get("salary_max")
        jobs.append({
            "title":       title,
            "company":     (item.get("company") or {}).get("display_name", ""),
            "location":    (item.get("location") or {}).get("display_name", location),
            "date_posted": str(item.get("created", ""))[:10],
            "job_url":     item.get("redirect_url", ""),
            "job_id":      str(item.get("id", "")),
            "description": _strip_html(item.get("description", ""))[:800],
            "job_type":    str(item.get("contract_time", "") or "").replace("_", " ").title(),
            "job_level":   "",
            "is_remote":   "remote" in str(item.get("location", "")).lower(),
            "min_amount":  lo,
            "max_amount":  hi,
            "currency":    "",
            "interval":    "yearly" if (lo or hi) else None,
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"Adzuna ({cc}): {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Adzuna")


# ──────────────────────────────────────────────────────────────────────────────
# Jooble scraper  (global aggregator — official JSON API, free key required)
# ──────────────────────────────────────────────────────────────────────────────

def _jooble_search(keyword, location, max_results, hours_old):
    """Official Jooble API — free key at jooble.org/api/about.
    Set the JOOBLE_API_KEY env var."""
    key = os.getenv("JOOBLE_API_KEY")
    if not key:
        logger.warning(
            "Jooble: skipped — set JOOBLE_API_KEY (free key at jooble.org/api/about)"
        )
        return _to_dataframe([], "Jooble")

    try:
        r = requests.post(
            f"https://jooble.org/api/{key}",
            json={"keywords": keyword, "location": location or "", "page": 1},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            logger.warning(f"Jooble: HTTP {r.status_code}")
            return _to_dataframe([], "Jooble")
        items = r.json().get("jobs", [])
    except Exception as e:
        logger.warning(f"Jooble: request failed — {e}")
        return _to_dataframe([], "Jooble")

    jobs: list = []
    for item in items:
        title = item.get("title", "")
        if not title:
            continue
        jobs.append({
            "title":       _strip_html(title),
            "company":     item.get("company", ""),
            "location":    item.get("location", location),
            "date_posted": str(item.get("updated", ""))[:10],
            "job_url":     item.get("link", ""),
            "job_id":      str(item.get("id", "")),
            "description": _strip_html(item.get("snippet", ""))[:800],
            "job_type":    item.get("type", "") or "",
            "job_level":   "",
            "is_remote":   "remote" in str(item.get("location", "")).lower(),
            "salary_text": str(item.get("salary", "") or "") or None,
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"Jooble: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Jooble")


# ──────────────────────────────────────────────────────────────────────────────
# Reed.co.uk scraper  (United Kingdom)
# ──────────────────────────────────────────────────────────────────────────────

def _reed_api_search(keyword, location, max_results, hours_old, api_key) -> pd.DataFrame:
    """Reed's official JSON API (reed.co.uk/developers) — far more reliable
    than scraping its HTML, which frequently blocks automated requests."""
    loc = location.split(",")[0].strip() if location and "," in location else ""
    try:
        r = requests.get(
            "https://www.reed.co.uk/api/1.0/search",
            params={"keywords": keyword, "locationName": loc,
                    "resultsToTake": min(max_results, 100)},
            auth=(api_key, ""),
            headers=_HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            logger.warning(f"Reed API: HTTP {r.status_code} — falling back to HTML")
            return pd.DataFrame()
        items = r.json().get("results", [])
    except Exception as e:
        logger.warning(f"Reed API: request failed ({e}) — falling back to HTML")
        return pd.DataFrame()

    jobs: list = []
    for item in items:
        title = item.get("jobTitle", "")
        if not title:
            continue
        date_posted = ""
        raw_date = str(item.get("date", ""))   # dd/mm/yyyy
        try:
            date_posted = datetime.strptime(raw_date, "%d/%m/%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
        lo, hi = item.get("minimumSalary"), item.get("maximumSalary")
        jobs.append({
            "title":       title,
            "company":     item.get("employerName", ""),
            "location":    item.get("locationName", location),
            "date_posted": date_posted,
            "job_url":     item.get("jobUrl", ""),
            "job_id":      str(item.get("jobId", "")),
            "description": _strip_html(item.get("jobDescription", ""))[:800],
            "job_type":    "",
            "job_level":   "",
            "is_remote":   False,
            "min_amount":  lo,
            "max_amount":  hi,
            "currency":    item.get("currency", "") or "GBP",
            "interval":    "yearly" if (lo or hi) else None,
        })
        if len(jobs) >= max_results:
            break

    logger.info(f"Reed API: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Reed")


def _reed_search(keyword, location, max_results, hours_old):
    # Official API first when a key is configured (free at reed.co.uk/developers)
    api_key = os.getenv("REED_API_KEY")
    if api_key:
        df = _reed_api_search(keyword, location, max_results, hours_old, api_key)
        if not df.empty:
            return df

    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers["Referer"] = "https://www.reed.co.uk/"

    kw_slug = _slugify(keyword)
    # Reed URLs use only the city name. A location without a comma is an
    # entire-country search ("United Kingdom") — Reed has no slug for that,
    # so use the country-wide /jobs/<kw>-jobs URL instead.
    if location and "," in location:
        loc_slug = _slugify(location.split(",")[0].strip())
        base_url = f"https://www.reed.co.uk/jobs/{kw_slug}-jobs-in-{loc_slug}"
    else:
        base_url = f"https://www.reed.co.uk/jobs/{kw_slug}-jobs"
    jobs: list = []
    page = 1

    while len(jobs) < max_results:
        url    = base_url
        params = {"pageno": page} if page > 1 else None

        r = _get_with_retry(session, url, params=params)
        if r is None:
            logger.warning("Reed: request failed")
            break

        soup  = BeautifulSoup(r.text, _BS_PARSER)
        cards = (
            soup.select("article.job-block-2")
            or soup.select("[data-qa='job-result']")
            or soup.select("article[data-jobid]")
            or soup.select("div[data-qa='job-card']")
        )

        if not cards:
            logger.warning("Reed: 0 cards found — site may be blocking requests")
            break

        for card in cards:
            title_el = (card.select_one("a[data-linktype='job-link']")
                        or card.select_one("h3.title a")
                        or card.select_one("h3 a"))
            company_el = (card.select_one("[data-qa='job-card-company']")
                          or card.select_one(".recruited-by"))
            loc_el     = (card.select_one("[data-qa='job-card-location']")
                          or card.select_one(".job-metadata__item--location"))
            link_el    = card.select_one("a[href*='/jobs/']")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            href    = link_el.get("href", "") if link_el else ""
            job_url = ("https://www.reed.co.uk" + href) if href.startswith("/") else href

            jobs.append({
                "title":       title,
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True) if loc_el else location,
                "date_posted": "",
                "job_url":     job_url,
                "job_id":      "",
                "description": "",
                "job_type":    "",
                "job_level":   "",
                "is_remote":   False,
            })
            if len(jobs) >= max_results:
                break

        next_btn = (soup.select_one("a[aria-label='Next page']")
                    or soup.select_one(".pagination-next")
                    or soup.select_one("a[rel='next']"))
        if not next_btn:
            break
        page += 1
        time.sleep(random.uniform(1.5, 3.0))

    logger.info(f"Reed: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Reed")


# ──────────────────────────────────────────────────────────────────────────────
# Rozee.pk scraper  (Pakistan)
# ──────────────────────────────────────────────────────────────────────────────

_ROZEE_URL = "https://rozee.pk/all-jobs.html"


def _rozee_search(keyword, location, max_results, hours_old):
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.headers["Referer"] = "https://rozee.pk/"

    jobs: list = []
    page = 1

    while len(jobs) < max_results:
        params = {"q": keyword, "l": location, "fpn": page}
        r = _get_with_retry(session, _ROZEE_URL, params=params)
        if r is None:
            logger.warning("Rozee: request failed")
            break

        soup  = BeautifulSoup(r.text, _BS_PARSER)
        cards = (
            soup.select("div[id^='job-']")
            or soup.select("li.job-item")
            or soup.select("div.job-card")
            or soup.select("div.position-title")
        )

        if not cards:
            logger.warning("Rozee: 0 cards found — HTML structure may have changed")
            break

        for card in cards:
            title_el   = card.select_one("h2 a") or card.select_one("a.position-title")
            company_el = (card.select_one(".company-name")
                          or card.select_one(".employer-name"))
            loc_el     = (card.select_one(".job-location")
                          or card.select_one(".location"))
            link_el    = card.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            href    = link_el.get("href", "") if link_el else ""
            job_url = ("https://rozee.pk" + href) if href.startswith("/") else href

            jobs.append({
                "title":       title,
                "company":     company_el.get_text(strip=True) if company_el else "",
                "location":    loc_el.get_text(strip=True) if loc_el else location,
                "date_posted": "",
                "job_url":     job_url,
                "job_id":      "",
                "description": "",
                "job_type":    "",
                "job_level":   "",
                "is_remote":   False,
            })
            if len(jobs) >= max_results:
                break

        next_btn = (soup.select_one("a.next")
                    or soup.select_one("[aria-label='Next']")
                    or soup.select_one("a[rel='next']"))
        if not next_btn:
            break
        page += 1
        time.sleep(random.uniform(1.5, 2.5))

    logger.info(f"Rozee: {len(jobs)} listings collected")
    return _to_dataframe(jobs, "Rozee")
