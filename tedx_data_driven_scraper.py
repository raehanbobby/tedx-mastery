#!/usr/bin/env python3
"""
TEDx Data-Driven Speaker Call Scraper
=======================================
Powered by your uploaded Global TEDx Events spreadsheet.
Instead of a hardcoded list of ~100 sites, this scraper works from
2,000+ real events pulled directly from your database.

Run all regions:
    python tedx_data_driven_scraper.py

Run specific region:
    python tedx_data_driven_scraper.py --region Canada
    python tedx_data_driven_scraper.py --region "United States"

Run 2026 events only:
    python tedx_data_driven_scraper.py --year 2026
"""

import argparse
import csv
import re
import smtplib
import time
import logging
import requests
import pandas as pd
from bs4 import BeautifulSoup
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ==============================================================
#  CONFIGURATION
# ==============================================================

CONFIG = {
    # Path to your uploaded events spreadsheet
    # Update this if you move the file.
    "events_file": "global_tedx_events_2025_2026.csv",

    # Output files
    "output_csv":  "tedx_speaker_calls_found.csv",
    "output_html": "tedx_speaker_calls_report.html",

    # Email (optional)
    "email_enabled":  False,
    "email_from":     "",
    "email_to":       "",
    "email_password": "",

    # How many events to check per run
    # Increase for thoroughness, decrease for speed
    "max_events_to_check": 200,

    # Politeness delay between requests
    "delay": 1.5,

    # Only check events dated after this (YYYY-MM-DD)
    "events_after": "2025-01-01",
}

SPEAKER_KEYWORDS = [
    "call for speakers", "speaker application", "apply to speak",
    "apply to be a speaker", "become a speaker", "speaker submissions",
    "applications are open", "applications now open", "now accepting",
    "apply now", "open call", "speaker portal", "speaker form",
    "submit your idea", "speaker nomination",
]

SPEAKER_PATHS = [
    "/speakers", "/speaker-application", "/apply", "/call-for-speakers",
    "/speak", "/get-involved", "/application", "/speaker-2026",
    "/call-for-speakers-2026", "/apply-to-speak", "/nominate",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ==============================================================
#  DATA MODEL
# ==============================================================

@dataclass
class SpeakerCall:
    event_name:  str
    city:        str
    country:     str
    event_date:  str
    theme:       str  = ""
    status:      str  = "likely_open"
    deadline:    str  = ""
    description: str  = ""
    speaker_url: str  = ""
    source_url:  str  = ""
    found_at:    str  = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

# ==============================================================
#  HELPERS
# ==============================================================

def fetch(url: str) -> Optional[BeautifulSoup]:
    time.sleep(CONFIG["delay"])
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.debug(f"  Could not fetch {url} — {e}")
        return None


def has_speaker_call(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SPEAKER_KEYWORDS)


def extract_deadline(text: str) -> str:
    patterns = [
        r"(?:deadline|applications?\s+close[sd]?|apply\s+by|due)[:\s]+"
        r"([A-Z][a-z]+ \d{1,2},?\s*202[56])",
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*202[56])",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def best_description(soup: BeautifulSoup) -> str:
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if len(t) > 60 and any(kw in t.lower() for kw in SPEAKER_KEYWORDS):
            return t[:220]
    return ""


def guess_website(name: str) -> str:
    slug = re.sub(r'[^a-zA-Z0-9]', '', str(name)).lower()
    return f"https://www.{slug}.com"


def check_event(row: dict) -> Optional[SpeakerCall]:
    """Check one event for an open speaker call. Returns SpeakerCall or None."""
    name    = str(row.get("Event Name", "")).strip()
    city    = str(row.get("City", "")).strip()
    country = str(row.get("Country", "")).strip()
    date    = str(row.get("Event Date", "")).strip()
    theme   = str(row.get("Theme", "")).strip()
    website = str(row.get("Website", "")).strip()
    ted_lnk = str(row.get("TED.com Link", "")).strip()

    if not name:
        return None

    # Determine base URL to check
    base_url = website if (website and not website.startswith("nan")) else guess_website(name)

    # Also check ted.com event page if available
    urls_to_try = [base_url]
    if ted_lnk and ted_lnk.startswith("http"):
        urls_to_try.append(ted_lnk)

    found_url  = None
    found_soup = None
    page_text  = ""

    for url in urls_to_try:
        soup = fetch(url)
        if not soup:
            continue
        pt = soup.get_text(" ", strip=True)
        if has_speaker_call(pt):
            found_url  = url
            found_soup = soup
            page_text  = pt
            break

        # Try common speaker sub-paths on the main site
        if url == base_url:
            for path in SPEAKER_PATHS:
                candidate = url.rstrip("/") + path
                sub = fetch(candidate)
                if sub and has_speaker_call(sub.get_text(" ", strip=True)):
                    found_url  = candidate
                    found_soup = sub
                    page_text  = sub.get_text(" ", strip=True)
                    break
            if found_url:
                break

    if not found_url:
        return None

    return SpeakerCall(
        event_name=name,
        city=city,
        country=country,
        event_date=date,
        theme=theme if theme not in ("nan","") else "",
        status="likely_open",
        deadline=extract_deadline(page_text),
        description=best_description(found_soup),
        speaker_url=found_url,
        source_url=base_url,
    )


# ==============================================================
#  MAIN SCRAPER
# ==============================================================

def load_events(region: Optional[str] = None, year: Optional[int] = None) -> pd.DataFrame:
    try:
        df = pd.read_csv(CONFIG["events_file"])
    except FileNotFoundError:
        log.error(
            f"Events file not found: {CONFIG['events_file']}\n"
            "Make sure global_tedx_events_2025_2026.csv is in the same folder."
        )
        return pd.DataFrame()

    df["Event Date"] = pd.to_datetime(df["Event Date"], errors="coerce")
    df = df[df["Event Date"] >= CONFIG["events_after"]]

    if region:
        df = df[df["Country"].str.lower() == region.lower()]
        if len(df) == 0:
            # Try partial match
            df_all = pd.read_csv(CONFIG["events_file"])
            df_all["Event Date"] = pd.to_datetime(df_all["Event Date"], errors="coerce")
            df_all = df_all[df_all["Event Date"] >= CONFIG["events_after"]]
            df = df_all[df_all["Country"].str.lower().str.contains(region.lower(), na=False)]

    if year:
        df = df[df["Event Date"].dt.year == year]

    # Sort by date — soonest first
    df = df.sort_values("Event Date")

    # Limit
    return df.head(CONFIG["max_events_to_check"])


def run(region: Optional[str] = None, year: Optional[int] = None):
    log.info("━" * 60)
    log.info("  TEDx Data-Driven Speaker Call Scraper  —  Starting")
    if region: log.info(f"  Region filter : {region}")
    if year:   log.info(f"  Year filter   : {year}")
    log.info("━" * 60)

    df = load_events(region, year)
    if df.empty:
        log.error("No events loaded. Check your CSV file and filters.")
        return []

    log.info(f"Checking {len(df)} events from your database...")
    found: List[SpeakerCall] = []

    for i, (_, row) in enumerate(df.iterrows(), 1):
        name    = row.get("Event Name", "")
        country = row.get("Country", "")
        date    = row.get("Event Date", "")
        log.info(f"  [{i:03d}/{len(df)}]  {name}  |  {country}  |  {str(date)[:10]}")

        result = check_event(row.to_dict())
        if result:
            found.append(result)
            log.info(f"           ✓  Speaker call found  →  {result.speaker_url}")

    log.info(f"\nTotal speaker calls found: {len(found)}")

    # Save CSV
    fields = ["event_name","city","country","event_date","theme","status",
              "deadline","description","speaker_url","source_url","found_at"]
    with open(CONFIG["output_csv"], "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in found:
            w.writerow(asdict(r))
    log.info(f"CSV saved  →  {CONFIG['output_csv']}")

    # Build HTML
    html = build_html(found, region, year)
    with open(CONFIG["output_html"], "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"HTML saved →  {CONFIG['output_html']}")

    if CONFIG["email_enabled"]:
        send_email(html)

    # Console summary
    print("\n" + "━" * 60)
    print(f"  {len(found)} open TEDx speaker call(s) found")
    print("━" * 60)
    for r in found:
        print(f"\n  {r.event_name}  |  {r.city}, {r.country}")
        print(f"  Event date : {r.event_date}")
        if r.deadline:   print(f"  Deadline   : {r.deadline}")
        if r.theme:      print(f"  Theme      : {r.theme}")
        print(f"  Apply at   : {r.speaker_url}")
    print(f"\n  Saved  →  {CONFIG['output_csv']}")
    print(f"  Saved  →  {CONFIG['output_html']}")
    print("━" * 60)
    return found


# ==============================================================
#  HTML REPORT
# ==============================================================

def build_html(results: List[SpeakerCall], region, year) -> str:
    now = datetime.now().strftime("%B %d, %Y")
    subtitle_parts = []
    if region: subtitle_parts.append(f"Region: {region}")
    if year:   subtitle_parts.append(f"Year: {year}")
    subtitle = " · ".join(subtitle_parts) if subtitle_parts else "All regions"

    if not results:
        body = ("<p style='color:#888;font-size:14px;'>"
                "No open speaker calls detected in this batch. Try a different region or year.</p>")
    else:
        # Group by country
        by_country: dict = {}
        for r in results:
            by_country.setdefault(r.country, []).append(r)

        cards = ""
        for country, events in sorted(by_country.items()):
            cards += f"""
<div style='margin-bottom:28px;'>
  <div style='background:#EEEDFE;border-radius:8px;padding:6px 14px;
              display:inline-block;margin-bottom:12px;'>
    <strong style='font-size:13px;color:#3C3489;'>
      {country} &nbsp;·&nbsp; {len(events)} result{'s' if len(events)!=1 else ''}
    </strong>
  </div>"""
            for e in events:
                rows = ""
                if e.city:       rows += f"<tr><td>City</td><td>{e.city}</td></tr>"
                if e.event_date: rows += f"<tr><td>Event date</td><td>{e.event_date}</td></tr>"
                if e.deadline:   rows += f"<tr><td>Deadline</td><td>{e.deadline}</td></tr>"
                if e.theme:      rows += f"<tr><td>Theme</td><td>{e.theme}</td></tr>"
                desc = (f"<p style='font-size:13px;color:#555;margin:8px 0 6px;'>"
                        f"{e.description}</p>") if e.description else ""
                cards += f"""
  <div style='background:#fff;border:1px solid #e0e0e0;border-radius:10px;
              padding:14px 18px;margin-bottom:10px;'>
    <div style='display:flex;justify-content:space-between;
                align-items:flex-start;margin-bottom:8px;'>
      <strong style='font-size:14px;color:#1a1a1a;'>{e.event_name}</strong>
      <span style='font-size:11px;background:#EEEDFE;color:#3C3489;
                   padding:3px 9px;border-radius:10px;
                   white-space:nowrap;margin-left:8px;'>Likely open</span>
    </div>
    <table style='font-size:12px;color:#444;border-collapse:collapse;width:100%;'>
      <colgroup><col style='width:90px;'></colgroup>
      {rows}
    </table>
    {desc}
    <a href='{e.speaker_url}' style='font-size:11px;color:#185FA5;
                                      word-break:break-all;'>{e.speaker_url}</a>
  </div>"""
            cards += "</div>"
        body = cards

    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <title>TEDx Speaker Calls — {now}</title>
  <style>
    td {{ padding: 3px 10px 3px 0; vertical-align: top; color: #666; }}
    td + td {{ color: #222; }}
  </style>
</head>
<body style='font-family:Arial,sans-serif;max-width:700px;
             margin:0 auto;padding:24px;background:#f5f5f5;'>
  <div style='background:#fff;border-radius:12px;padding:28px;'>
    <h1 style='font-size:22px;color:#1a1a1a;margin:0 0 4px;'>
      TEDx Open Speaker Calls
    </h1>
    <p style='font-size:13px;color:#aaa;margin:0 0 24px;'>
      {now} &nbsp;·&nbsp; {subtitle} &nbsp;·&nbsp;
      {len(results)} result{'s' if len(results)!=1 else ''} found
    </p>
    {body}
    <hr style='border:none;border-top:1px solid #eee;margin:24px 0 14px;'>
    <p style='font-size:11px;color:#bbb;'>
      Built for Bobby Umar / DYPB &nbsp;·&nbsp;
      Powered by your Global TEDx Events database &nbsp;·&nbsp;
      Always verify with organizers before applying
    </p>
  </div>
</body>
</html>"""


# ==============================================================
#  EMAIL
# ==============================================================

def send_email(html: str):
    if not CONFIG["email_enabled"]:
        return
    missing = [k for k in ("email_from","email_to","email_password") if not CONFIG[k]]
    if missing:
        log.warning(f"Email skipped — missing: {missing}")
        return
    subject = f"TEDx Speaker Calls — {datetime.now().strftime('%B %d, %Y')}"
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = CONFIG["email_from"]
    msg["To"]      = CONFIG["email_to"]
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(CONFIG["email_from"], CONFIG["email_password"])
            srv.sendmail(CONFIG["email_from"], CONFIG["email_to"], msg.as_string())
        log.info(f"Email sent to {CONFIG['email_to']}")
    except Exception as e:
        log.error(f"Email failed: {e}")


# ==============================================================
#  CLI
# ==============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TEDx Data-Driven Speaker Call Scraper")
    parser.add_argument("--region", type=str, default=None,
                        help="Country to filter by, e.g. 'Canada' or 'United States'")
    parser.add_argument("--year",   type=int, default=None,
                        help="Year to filter by, e.g. 2026")
    args = parser.parse_args()
    run(region=args.region, year=args.year)
