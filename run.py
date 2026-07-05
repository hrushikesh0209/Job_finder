"""
Command-line interface - alternative to the Streamlit UI.

Examples:
    python run.py --keyword "Python Developer" --location "Remote"
    python run.py --keyword "Data Analyst" --location "Berlin" --cv my_cv.pdf
    python run.py --keyword "DevOps Engineer" --location "London" --sites linkedin indeed --hours 48 --max-jobs 30
"""

import argparse
import os
import sys

from scraper import search_jobs, SUPPORTED_SITES
from cv_analyzer import read_cv, score_cv_against_jobs, keyword_gap, extract_skills
from excel_exporter import export_to_excel


def main():
    p = argparse.ArgumentParser(description="Job Finder AI - CLI")
    p.add_argument("--keyword",   required=True, help='e.g. "Python Developer"')
    p.add_argument("--location",  required=True, help='e.g. "Remote" or "Berlin"')
    p.add_argument("--max-jobs",  type=int, default=20, dest="max_jobs")
    p.add_argument("--hours",     type=int, default=72,  help="Jobs posted within N hours")
    p.add_argument("--sites",     nargs="+", default=["linkedin", "indeed"],
                   choices=SUPPORTED_SITES)
    p.add_argument("--cv",        help="Path to your CV (.docx or .pdf)")
    p.add_argument("--output",    help="Output Excel path (auto-named if omitted)")
    p.add_argument("--remote",    action="store_true", help="Remote jobs only")
    args = p.parse_args()

    print(f"\n{'='*55}")
    print(f"  Searching: {args.keyword}  |  {args.location}")
    print(f"  Sites:     {', '.join(args.sites)}")
    print(f"  Max jobs:  {args.max_jobs}  |  within {args.hours}h")
    print(f"{'='*55}\n")

    df = search_jobs(
        keyword=args.keyword,
        location=args.location,
        max_results=args.max_jobs,
        hours_old=args.hours,
        sites=args.sites,
        remote_only=args.remote,
    )

    if df is None or df.empty:
        print("❌  No jobs found. Try different keywords, location, or boards.")
        sys.exit(1)

    print(f"✅  Found {len(df)} jobs\n")

    # ── CV match scoring ──────────────────────────────────────────────────────
    match_scores = None
    if args.cv:
        if not os.path.exists(args.cv):
            print(f"⚠️  CV file not found: {args.cv}")
        else:
            print(f"📄  Scoring CV: {args.cv}")
            cv_text = read_cv(args.cv)
            if cv_text:
                descriptions  = df["description"].fillna("").tolist()
                sim_scores    = score_cv_against_jobs(cv_text, descriptions)
                cv_skills     = extract_skills(cv_text)
                match_scores  = []
                for sim, desc in zip(sim_scores, descriptions):
                    kw = keyword_gap(cv_text, str(desc), cv_skills=cv_skills)
                    match_scores.append({
                        "tfidf_score":    sim,
                        "matched_skills": kw["matched_skills"],
                        "missing_skills": kw["missing_skills"],
                    })

                avg = sum(s["tfidf_score"] for s in match_scores) / len(match_scores)
                print(f"   Average match: {avg:.1f}%\n")

                # Top 5
                ranked = sorted(enumerate(match_scores), key=lambda x: -x[1]["tfidf_score"])
                print("  Top 5 matches:")
                for rank, (i, sc) in enumerate(ranked[:5], 1):
                    row = df.iloc[i]
                    print(f"   {rank}. {row.get('title','?')} @ {row.get('company','?')}"
                          f"  [{sc['tfidf_score']:.1f}%]")
                print()
            else:
                print("   Could not read CV text.\n")

    # ── Excel export ──────────────────────────────────────────────────────────
    out = args.output or (
        f"jobs_{args.keyword.replace(' ','_')}_{args.location.replace(' ','_')}.xlsx"
    )
    path = export_to_excel(df, match_scores, output_path=out)
    print(f"📊  Excel saved → {path}")
    print("\nDone! Open the Excel file to see results.\n")


if __name__ == "__main__":
    main()
