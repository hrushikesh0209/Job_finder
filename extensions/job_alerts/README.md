# GitHub Actions Job Alerts

This is an isolated extension for the existing Job Finder portal. It imports
the public `search_jobs_multi`, `fetch_job_page_texts`, `score_cv_against_jobs`,
and `extract_skills` functions, but does not import Streamlit or write any of
the portal's JSON state files.

## Privacy Boundary

`config.json` is committed to a public repository. Job titles, locations,
boards, schedules, and thresholds in that file are public. Never put an email
address, CV text, password, token, or API key in it.

Private values belong in GitHub repository secrets:

- `GMAIL_USER`: Gmail address that sends alerts
- `GMAIL_APP_PASSWORD`: 16-character Gmail app password, not the account password
- `NOTIFY_EMAIL`: destination email address
- `JOBFINDER_CV_GZIP_BASE64`: compressed CV text prepared by this extension
- Optional board keys: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `JOOBLE_API_KEY`,
  and `REED_API_KEY`

## Configure Profiles

Edit `config.json`. Profiles are disabled by default. Set `enabled` to `true`
only after the secrets and workflow permissions are configured.

Supported schedules:

```json
{"kind": "interval", "hours": 3}
```

`hours` may be `1`, `3`, `6`, or `12`. A daily schedule uses local time from
the top-level timezone:

```json
{"kind": "daily", "time": "08:30"}
```

When both score filters are enabled, `score_logic` can be `either` or `both`.
With both score filters disabled, every job passing the search and experience
criteria qualifies.

To copy a portal search into this public config without changing the original:

```powershell
.\venv\Scripts\python.exe -m extensions.job_alerts import-search --name "1st seach"
```

The imported profile stays disabled. Review `config.json`, then commit and push
it for GitHub Actions to see the change.

## GitHub Setup

1. Enable repository **Settings > Actions > General > Workflow permissions >
   Read and write permissions**. The workflow uses write access only for the
   dedicated `alerts-state` branch.
2. Add the email secrets without printing them in workflow logs:

```powershell
gh secret set GMAIL_USER
gh secret set GMAIL_APP_PASSWORD
gh secret set NOTIFY_EMAIL
```

3. Prepare the CV secret. This extracts text locally and sends the compressed
   value to `gh` over standard input:

```powershell
.\venv\Scripts\python.exe -m extensions.job_alerts prepare-cv --file .\resume.pdf
```

4. Commit the extension and workflow to `main`.
5. Open **Actions > Scheduled Job Alerts > Run workflow**. Start with
   `dry-run`, then use `test-email`, and finally `due`.

Gmail app passwords require two-step verification. Some managed, school, or
Advanced Protection accounts do not offer app passwords.

## Local Commands

Install extension-only dependencies when needed:

```powershell
.\venv\Scripts\python.exe -m pip install -r extensions\job_alerts\requirements.txt
```

Run without sending or changing delivery state:

```powershell
.\venv\Scripts\python.exe -m extensions.job_alerts run-due --dry-run
.\venv\Scripts\python.exe -m extensions.job_alerts run-profile --id 1st-seach --dry-run
```

Send a test email after setting the three Gmail environment variables:

```powershell
.\venv\Scripts\python.exe -m extensions.job_alerts test-email
```

## State and Delivery

The workflow creates `alerts-state` automatically. It contains only profile
IDs, job hashes, timestamps, result counts, and status/error text. It never
contains CV text, email addresses, job descriptions, or credentials.

Jobs are recorded only after Gmail accepts the digest. A rare workflow failure
after SMTP succeeds but before the state push can produce one duplicate digest.
No email is sent when there are no new qualifying jobs.

GitHub-hosted runners use shared data-center IPs, so individual boards may
block or rate-limit searches. Indeed and Naukri install Playwright conditionally
and remain best-effort. Scheduled workflows in inactive public repositories can
be disabled by GitHub after 60 days and may occasionally start late.

## Tests

```powershell
.\venv\Scripts\python.exe -m unittest discover -s extensions\job_alerts\tests -v
```
