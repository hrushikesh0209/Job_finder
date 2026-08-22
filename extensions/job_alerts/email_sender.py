"""Safe HTML/plain-text digest rendering and Gmail SMTP delivery."""

from __future__ import annotations

import html
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Iterable
from urllib.parse import urlsplit


@dataclass(frozen=True)
class EmailSettings:
    username: str
    app_password: str
    recipient: str
    host: str = "smtp.gmail.com"
    port: int = 587


def _valid_email(value: str) -> bool:
    _, address = parseaddr(value)
    return bool(address and "@" in address and "\n" not in value and "\r" not in value)


def settings_from_env() -> EmailSettings:
    settings = EmailSettings(
        username=os.getenv("GMAIL_USER", "").strip(),
        app_password=os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip(),
        recipient=os.getenv("NOTIFY_EMAIL", "").strip(),
    )
    if not _valid_email(settings.username):
        raise ValueError("GMAIL_USER is missing or invalid")
    if not settings.app_password:
        raise ValueError("GMAIL_APP_PASSWORD is missing")
    if not _valid_email(settings.recipient):
        raise ValueError("NOTIFY_EMAIL is missing or invalid")
    return settings


def validated_job_url(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _safe_header(value: Any) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _score(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _salary(job: dict[str, Any]) -> str:
    text = str(job.get("salary_text") or "").strip()
    if text:
        return text
    low, high = job.get("min_amount"), job.get("max_amount")
    if low is None and high is None:
        return "Not listed"
    currency = str(job.get("currency") or "").strip()
    interval = str(job.get("interval") or "").strip()
    values = " - ".join(str(value) for value in (low, high) if value is not None)
    return " ".join(part for part in (currency, values, interval) if part)


def build_digest_message(
    profile: dict[str, Any],
    jobs: Iterable[dict[str, Any]],
    settings: EmailSettings,
) -> EmailMessage:
    job_list = list(jobs)
    label = _safe_header(profile.get("label") or profile.get("id") or "Job alert")
    message = EmailMessage()
    message["Subject"] = f"[Job Finder] {len(job_list)} new match(es) - {label}"
    message["From"] = settings.username
    message["To"] = settings.recipient

    plain = [f"{len(job_list)} new job match(es) for {label}", ""]
    cards: list[str] = []
    for index, job in enumerate(job_list, 1):
        title = _safe_header(job.get("title") or "Untitled role")
        company = _safe_header(job.get("company") or "Unknown company")
        location = _safe_header(job.get("location") or "Not listed")
        site = _safe_header(job.get("site") or "Unknown board")
        posted = _safe_header(job.get("date_posted") or "Not listed")
        salary = _safe_header(_salary(job))
        match_score = _score(job.get("match_score"))
        ats_score = _score(job.get("ats_score"))
        url = validated_job_url(job.get("job_url"))
        plain.extend(
            [
                f"{index}. {title} at {company}",
                f"Location: {location} | Board: {site} | Posted: {posted}",
                f"Salary: {salary} | Match: {match_score} | ATS: {ats_score}",
                f"Apply/View: {url or 'No safe link available'}",
                "",
            ]
        )
        link_html = (
            f'<a href="{html.escape(url, quote=True)}" style="display:inline-block;'
            'padding:10px 16px;background:#12664f;color:white;text-decoration:none;'
            'border-radius:6px;font-weight:bold">Apply / View Job</a>'
            if url
            else "<em>No safe apply link available</em>"
        )
        cards.append(
            '<div style="border:1px solid #d9dfdc;border-radius:10px;padding:16px;'
            'margin:0 0 14px;background:#ffffff">'
            f'<h2 style="font-size:18px;margin:0 0 4px">{html.escape(title)}</h2>'
            f'<div style="font-weight:bold;color:#12664f">{html.escape(company)}</div>'
            f'<p style="line-height:1.6;margin:10px 0">Location: {html.escape(location)}<br>'
            f'Board: {html.escape(site)} | Posted: {html.escape(posted)}<br>'
            f'Salary: {html.escape(salary)}<br>'
            f'Match: <strong>{match_score}</strong> | ATS: <strong>{ats_score}</strong></p>'
            f"{link_html}</div>"
        )

    message.set_content("\n".join(plain))
    message.add_alternative(
        '<!doctype html><html><body style="margin:0;background:#f3f6f4;'
        'font-family:Arial,sans-serif;color:#18221e"><div style="max-width:700px;'
        'margin:auto;padding:24px"><h1 style="margin-top:0">New job matches</h1>'
        f'<p>Alert: <strong>{html.escape(label)}</strong> &middot; '
        f'{len(job_list)} new result(s)</p>{"".join(cards)}'
        '<p style="font-size:12px;color:#637069">Generated by the isolated Job Finder '
        'GitHub Actions alert extension. Verify each listing before applying.</p>'
        "</div></body></html>",
        subtype="html",
    )
    return message


def build_test_message(settings: EmailSettings) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "[Job Finder] Gmail alert test"
    message["From"] = settings.username
    message["To"] = settings.recipient
    message.set_content(
        "The isolated GitHub Actions job alert extension can send email successfully."
    )
    return message


def send_message(message: EmailMessage, settings: EmailSettings) -> None:
    with smtplib.SMTP(settings.host, settings.port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(settings.username, settings.app_password)
        smtp.send_message(message)
