#!/usr/bin/env python3
"""
TEDx Master Database Updater
==============================
This is the engine that keeps your TEDx Mastery Program list
perpetually fresh and growing.

Every time it runs it:
  1. Loads your existing master database
  2. Scrapes new events from ted.com + Google
  3. Merges new events in (no duplicates)
  4. Checks for open speaker calls across all events
  5. Saves an updated master Excel file (client-ready, formatted)
  6. Saves a "what's new this week" summary CSV
  7. Emails you a digest (optional)

Run weekly:   python tedx_master_updater.py
First run:    python tedx_master_updater.py --seed global_tedx_events_2025_2026.csv

Deploy free on GitHub Actions — see README_GLOBAL.md for the workflow file.
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
from openpyxl import Workbook, load_workbook
from openpyxl.styles import (Font, PatternFill, Alignment, Border, Side,
                              GradientFill)
from openpyxl.utils import get_column_letter
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path
from typing import Optional

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
    # The master database file — grows with every run
    "master_db":      "TEDx_Mastery_Master_Database.xlsx",

    # CSV fallback (always kept in sync alongside the Excel)
    "master_csv":     "TEDx_Mastery_Master_Database.csv",

    # New-this-week summary
    "new_events_csv": "tedx_new_events_this_week.csv",

    # Email digest
    "email_enabled":  False,
    "email_from":     "",
    "email_to":       "",
    "email_password": "",

    # Scraping behaviour
    "delay":            1.5,
    "max_new_to_check": 100,   # how many newly added events to check for speaker calls

    # ted.com search terms to discover new events
    "ted_search_terms": [
        "canada", "united states", "united kingdom", "australia",
        "germany", "france", "india", "brazil", "south africa",
        "singapore", "japan", "uae", "mexico", "netherlands",
    ],
}

SPEAKER_KEYWORDS = [
    "call for speakers", "speaker application", "apply to speak",
    "become a speaker", "applications are open", "applications now open",
    "now accepting", "apply now", "open call", "speaker portal",
    "speaker form", "submit your idea",
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
}

DB_COLUMNS = [
    "Event Name", "City", "State/Region", "Country", "Event Date",
    "Website", "Theme", "Speaker Call Status", "Application URL",
    "Application Deadline", "Description", "# Past Events",
    "Last Checked", "Date Added",
]

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
        log.debug(f"  Fetch failed: {url} — {e}")
        return None


def has_speaker_call(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in SPEAKER_KEYWORDS)


def extract_deadline(text: str) -> str:
    patterns = [
        r"(?:deadline|applications?\s+close[sd]?|apply\s+by|due)[:\s]+"
        r"([A-Z][a-z]+ \d{1,2},?\s*202[567])",
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*202[567])",
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


def clean_name(x) -> str:
    if pd.isna(x) or x is None:
        return ""
    return re.sub(r"[\u00ad]+", "", str(x)).strip()


def guess_website(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
    return f"https://www.{slug}.com"


def event_key(name: str, city: str) -> str:
    """Normalised key for deduplication."""
    combined = clean_name(name) + str(city)
    return re.sub(r"\W+", "", combined).lower()


# ==============================================================
#  LOAD / INITIALISE MASTER DATABASE
# ==============================================================

def load_master_db() -> pd.DataFrame:
    """Load the master database CSV, or create an empty one."""
    path = CONFIG["master_csv"]
    if Path(path).exists():
        df = pd.read_csv(path, dtype=str)
        df["Event Date"] = pd.to_datetime(df["Event Date"], errors="coerce")
        log.info(f"Loaded master DB: {len(df)} existing events")
        return df
    else:
        log.info("No master DB found — starting fresh")
        return pd.DataFrame(columns=DB_COLUMNS)


def seed_from_csv(df_master: pd.DataFrame, seed_path: str) -> pd.DataFrame:
    """Import a seed CSV (e.g. global_tedx_events_2025_2026.csv) into master."""
    if not Path(seed_path).exists():
        log.warning(f"Seed file not found: {seed_path}")
        return df_master

    seed = pd.read_csv(seed_path, dtype=str)
    seed["Event Date"] = pd.to_datetime(seed["Event Date"], errors="coerce")
    now = datetime.now().strftime("%Y-%m-%d")

    existing_keys = set(
        event_key(r.get("Event Name",""), r.get("City",""))
        for _, r in df_master.iterrows()
    )

    added = 0
    new_rows = []
    for _, row in seed.iterrows():
        name = clean_name(row.get("Event Name", ""))
        city = str(row.get("City", ""))
        if not name:
            continue
        key = event_key(name, city)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        added += 1
        new_rows.append({
            "Event Name":          name,
            "City":                city,
            "State/Region":        str(row.get("State/Region", "")),
            "Country":             str(row.get("Country", "")),
            "Event Date":          row.get("Event Date", pd.NaT),
            "Website":             str(row.get("Website", "")),
            "Theme":               clean_name(row.get("Theme", "")),
            "Speaker Call Status": "unchecked",
            "Application URL":     "",
            "Application Deadline":"",
            "Description":         "",
            "# Past Events":       str(row.get("# Past Events", "")),
            "Last Checked":        "",
            "Date Added":          now,
        })

    if new_rows:
        df_master = pd.concat(
            [df_master, pd.DataFrame(new_rows)],
            ignore_index=True
        )

    log.info(f"Seeded {added} new events from {seed_path}")
    return df_master


# ==============================================================
#  DISCOVER NEW EVENTS FROM TED.COM
# ==============================================================

def discover_new_events(df_master: pd.DataFrame) -> pd.DataFrame:
    """Scrape ted.com for events not yet in the master database."""
    log.info("Discovering new events from ted.com...")

    existing_keys = set(
        event_key(r.get("Event Name",""), r.get("City",""))
        for _, r in df_master.iterrows()
    )

    now = datetime.now().strftime("%Y-%m-%d")
    new_rows = []
    seen_urls = set()

    for term in CONFIG["ted_search_terms"]:
        url = f"https://www.ted.com/tedx/events?q={term.replace(' ','+')}"
        soup = fetch(url)
        if not soup:
            continue

        for a in soup.find_all("a", href=re.compile(r"/tedx/events/\d+")):
            href = a["href"]
            full_url = f"https://www.ted.com{href}" if href.startswith("/") else href
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            ev_soup = fetch(full_url)
            if not ev_soup:
                continue

            page_text = ev_soup.get_text(" ", strip=True)
            name_tag  = ev_soup.find("h1") or ev_soup.find("title")
            raw_name  = name_tag.get_text(strip=True) if name_tag else a.get_text(strip=True)
            raw_name  = re.sub(r"\s*[|\-–]\s*.+$", "", raw_name).strip()
            name      = clean_name(raw_name)

            city_match = re.search(r"([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z][a-z]+(?: [A-Z][a-z]+)*)", page_text)
            city    = city_match.group(1) if city_match else ""
            country = city_match.group(2) if city_match else ""

            key = event_key(name, city)
            if key in existing_keys or not name:
                continue

            existing_keys.add(key)
            new_rows.append({
                "Event Name":          name,
                "City":                city,
                "State/Region":        "",
                "Country":             country,
                "Event Date":          pd.NaT,
                "Website":             full_url,
                "Theme":               "",
                "Speaker Call Status": "unchecked",
                "Application URL":     "",
                "Application Deadline":"",
                "Description":         "",
                "# Past Events":       "",
                "Last Checked":        "",
                "Date Added":          now,
            })

    if new_rows:
        df_master = pd.concat(
            [df_master, pd.DataFrame(new_rows)],
            ignore_index=True
        )
        log.info(f"  Discovered {len(new_rows)} new events from ted.com")
    else:
        log.info("  No new events discovered from ted.com this cycle")

    return df_master


# ==============================================================
#  CHECK FOR OPEN SPEAKER CALLS
# ==============================================================

def check_speaker_calls(df_master: pd.DataFrame) -> pd.DataFrame:
    """
    Check unchecked (or not-recently-checked) events for open speaker calls.
    Updates Speaker Call Status, Application URL, Deadline, Description.
    """
    log.info("Checking for open speaker calls...")

    # Prioritise: unchecked first, then checked >14 days ago
    now      = datetime.now()
    two_weeks_ago = (now - pd.Timedelta(days=14)).strftime("%Y-%m-%d")

    to_check = df_master[
        (df_master["Speaker Call Status"] == "unchecked") |
        (df_master["Last Checked"] < two_weeks_ago) |
        (df_master["Last Checked"].isna()) |
        (df_master["Last Checked"] == "")
    ].head(CONFIG["max_new_to_check"])

    log.info(f"  Events to check this cycle: {len(to_check)}")
    found_count = 0

    for idx in to_check.index:
        row    = df_master.loc[idx]
        name   = str(row.get("Event Name", ""))
        website= str(row.get("Website", ""))

        base_url = (website if website and website not in ("nan","")
                    else guess_website(name))

        log.info(f"    Checking: {name}")

        found_url  = None
        found_soup = None
        page_text  = ""

        # 1. Try the base URL
        soup = fetch(base_url)
        if soup:
            pt = soup.get_text(" ", strip=True)
            if has_speaker_call(pt):
                found_url, found_soup, page_text = base_url, soup, pt
            else:
                # 2. Look for internal speaker link
                for a in soup.find_all("a", href=True):
                    href_l    = a["href"].lower()
                    link_text = a.get_text(strip=True).lower()
                    if any(kw in href_l or kw in link_text
                           for kw in ["speaker","apply","application","speak"]):
                        raw = a["href"]
                        candidate = (raw if raw.startswith("http")
                                     else base_url.rstrip("/") + raw
                                     if raw.startswith("/") else None)
                        if candidate:
                            sub = fetch(candidate)
                            if sub and has_speaker_call(sub.get_text(" ", strip=True)):
                                found_url  = candidate
                                found_soup = sub
                                page_text  = sub.get_text(" ", strip=True)
                                break

                # 3. Try common paths
                if not found_url:
                    for path in SPEAKER_PATHS:
                        candidate = base_url.rstrip("/") + path
                        sub = fetch(candidate)
                        if sub and has_speaker_call(sub.get_text(" ", strip=True)):
                            found_url  = candidate
                            found_soup = sub
                            page_text  = sub.get_text(" ", strip=True)
                            break

        # Update the row
        checked_at = now.strftime("%Y-%m-%d")
        if found_url:
            deadline = extract_deadline(page_text)
            desc     = best_description(found_soup) if found_soup else ""
            df_master.at[idx, "Speaker Call Status"]   = "open"
            df_master.at[idx, "Application URL"]       = found_url
            df_master.at[idx, "Application Deadline"]  = deadline
            df_master.at[idx, "Description"]           = desc
            df_master.at[idx, "Last Checked"]          = checked_at
            found_count += 1
            log.info(f"      ✓  Open call found: {found_url}")
        else:
            df_master.at[idx, "Speaker Call Status"] = "not_found"
            df_master.at[idx, "Last Checked"]        = checked_at

    log.info(f"  Open speaker calls found this cycle: {found_count}")
    return df_master


# ==============================================================
#  SAVE MASTER DATABASE (CSV + FORMATTED EXCEL)
# ==============================================================

def save_master_db(df: pd.DataFrame):
    """Save master CSV (always) and formatted Excel (client-ready)."""

    # Sort: open calls first, then by date
    status_order = {"open": 0, "unchecked": 1, "not_found": 2}
    df["_sort_status"] = df["Speaker Call Status"].map(status_order).fillna(3)
    df["_sort_date"]   = pd.to_datetime(df["Event Date"], errors="coerce")
    df = df.sort_values(["_sort_status", "_sort_date"]).drop(
        columns=["_sort_status", "_sort_date"], errors="ignore"
    )

    # ── CSV ─────────────────────────────────────────────────
    df.to_csv(CONFIG["master_csv"], index=False)
    log.info(f"Master CSV saved  →  {CONFIG['master_csv']}")

    # ── Excel ───────────────────────────────────────────────
    wb = Workbook()

    # ── Sheet 1: All Events ─────────────────────────────────
    ws_all = wb.active
    ws_all.title = "All Events"
    _write_sheet(ws_all, df, "TEDx Master Database — All Events")

    # ── Sheet 2: Open Speaker Calls ─────────────────────────
    df_open = df[df["Speaker Call Status"] == "open"].copy()
    ws_open = wb.create_sheet("Open Speaker Calls")
    _write_sheet(ws_open, df_open, "TEDx Open Speaker Calls", highlight=True)

    # ── Sheet 3: 2026 Events ────────────────────────────────
    df_2026 = df[pd.to_datetime(df["Event Date"], errors="coerce").dt.year == 2026].copy()
    ws_2026 = wb.create_sheet("2026 Events")
    _write_sheet(ws_2026, df_2026, "TEDx 2026 Events")

    # ── Sheet 4: Canada Focus ───────────────────────────────
    df_ca = df[df["Country"].str.lower().str.contains("canada", na=False)].copy()
    ws_ca = wb.create_sheet("Canada")
    _write_sheet(ws_ca, df_ca, "TEDx Canada Events 2025–2026")

    # ── Sheet 5: Stats dashboard ────────────────────────────
    ws_stats = wb.create_sheet("Stats")
    _write_stats(ws_stats, df)

    wb.save(CONFIG["master_db"])
    log.info(f"Master Excel saved →  {CONFIG['master_db']}")


def _header_style():
    return {
        "font":      Font(name="Arial", bold=True, size=10, color="FFFFFF"),
        "fill":      PatternFill("solid", fgColor="3C3489"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "border":    Border(
            bottom=Side(style="thin", color="FFFFFF"),
            right=Side(style="thin", color="5050A0"),
        ),
    }


STATUS_COLORS = {
    "open":      "EAF3DE",  # green
    "unchecked": "EEEDFE",  # purple tint
    "not_found": "F5F5F5",  # light gray
}

COL_WIDTHS = {
    "Event Name": 34, "City": 16, "State/Region": 14, "Country": 16,
    "Event Date": 14, "Website": 32, "Theme": 22,
    "Speaker Call Status": 16, "Application URL": 36,
    "Application Deadline": 20, "Description": 44,
    "# Past Events": 12, "Last Checked": 14, "Date Added": 14,
}


def _write_sheet(ws, df: pd.DataFrame, title: str, highlight: bool = False):
    from openpyxl.styles import Font as F, PatternFill as PF, Alignment as A

    # Title row
    ws.append([title])
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1, end_column=len(DB_COLUMNS))
    title_cell = ws.cell(1, 1)
    title_cell.font      = F(name="Arial", bold=True, size=13, color="3C3489")
    title_cell.alignment = A(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 22

    # Sub-title with count + date
    ws.append([f"{len(df)} events  ·  Updated {datetime.now().strftime('%B %d, %Y')}"])
    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2, end_column=len(DB_COLUMNS))
    ws.cell(2, 1).font = F(name="Arial", size=9, color="888888")
    ws.row_dimensions[2].height = 16

    ws.append([])  # blank row

    # Header row
    hs = _header_style()
    ws.append(DB_COLUMNS)
    for col_idx, col_name in enumerate(DB_COLUMNS, 1):
        cell = ws.cell(4, col_idx)
        cell.font      = hs["font"]
        cell.fill      = hs["fill"]
        cell.alignment = hs["alignment"]
        cell.border    = hs["border"]
        ws.column_dimensions[get_column_letter(col_idx)].width = COL_WIDTHS.get(col_name, 16)
    ws.row_dimensions[4].height = 28

    # Data rows
    for row_num, (_, row) in enumerate(df.iterrows(), 5):
        status = str(row.get("Speaker Call Status", ""))
        bg     = STATUS_COLORS.get(status, "FFFFFF")

        for col_idx, col_name in enumerate(DB_COLUMNS, 1):
            val = row.get(col_name, "")
            if pd.isna(val):
                val = ""
            elif col_name == "Event Date" and hasattr(val, "strftime"):
                val = val.strftime("%Y-%m-%d")
            else:
                val = str(val) if val else ""

            cell             = ws.cell(row_num, col_idx, val)
            cell.font        = F(name="Arial", size=9)
            cell.fill        = PF("solid", fgColor=bg)
            cell.alignment   = A(vertical="center", wrap_text=(col_name == "Description"))

            if col_name in ("Website", "Application URL") and val.startswith("http"):
                cell.hyperlink = val
                cell.font      = F(name="Arial", size=9, color="185FA5", underline="single")

            if col_name == "Speaker Call Status" and status == "open":
                cell.font = F(name="Arial", size=9, bold=True, color="27500A")

        ws.row_dimensions[row_num].height = 18

    # Freeze header
    ws.freeze_panes = ws.cell(5, 1)


def _write_stats(ws, df: pd.DataFrame):
    from openpyxl.styles import Font as F, PatternFill as PF, Alignment as A

    ws["A1"] = "TEDx Mastery Database — Stats"
    ws["A1"].font = F(name="Arial", bold=True, size=13, color="3C3489")
    ws["A2"] = f"Updated {datetime.now().strftime('%B %d, %Y')}"
    ws["A2"].font = F(name="Arial", size=9, color="888888")

    stats = [
        ("", ""),
        ("Total events in database",  len(df)),
        ("Open speaker calls",        len(df[df["Speaker Call Status"] == "open"])),
        ("Unchecked (pending)",        len(df[df["Speaker Call Status"] == "unchecked"])),
        ("", ""),
        ("Events in 2025",            len(df[pd.to_datetime(df["Event Date"], errors="coerce").dt.year == 2025])),
        ("Events in 2026",            len(df[pd.to_datetime(df["Event Date"], errors="coerce").dt.year == 2026])),
        ("", ""),
        ("Canada",                    len(df[df["Country"].str.lower().str.contains("canada", na=False)])),
        ("United States",             len(df[df["Country"].str.lower().str.contains("united states", na=False)])),
        ("United Kingdom",            len(df[df["Country"].str.lower().str.contains("united kingdom", na=False)])),
        ("Australia",                 len(df[df["Country"].str.lower().str.contains("australia", na=False)])),
        ("", ""),
        ("Last updated",              datetime.now().strftime("%Y-%m-%d %H:%M")),
    ]

    for r_idx, (label, val) in enumerate(stats, 4):
        ws.cell(r_idx, 1, label).font = F(name="Arial", size=10, bold=bool(label))
        ws.cell(r_idx, 2, val).font   = F(name="Arial", size=10)
        if isinstance(val, int) and val > 0:
            ws.cell(r_idx, 2).font = F(name="Arial", size=10, bold=True, color="3C3489")

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 16


# ==============================================================
#  NEW-THIS-WEEK SUMMARY
# ==============================================================

def save_new_events_summary(df_master: pd.DataFrame):
    """Save a CSV of events added or updated this week."""
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")

    new_this_week = df_master[
        (df_master["Date Added"] >= week_ago) |
        (df_master["Speaker Call Status"] == "open")
    ].copy()

    new_this_week.to_csv(CONFIG["new_events_csv"], index=False)
    log.info(f"New this week: {len(new_this_week)} events  →  {CONFIG['new_events_csv']}")
    return new_this_week


# ==============================================================
#  EMAIL DIGEST
# ==============================================================

def send_digest(df_master: pd.DataFrame, new_this_week: pd.DataFrame):
    if not CONFIG["email_enabled"]:
        return
    missing = [k for k in ("email_from","email_to","email_password") if not CONFIG[k]]
    if missing:
        log.warning(f"Email skipped — missing: {missing}")
        return

    open_calls = df_master[df_master["Speaker Call Status"] == "open"]
    now_str    = datetime.now().strftime("%B %d, %Y")

    cards = ""
    for _, e in open_calls.iterrows():
        deadline_row = (f"<tr><td style='color:#666'>Deadline</td>"
                        f"<td>{e['Application Deadline']}</td></tr>"
                        if e.get("Application Deadline") else "")
        theme_row = (f"<tr><td style='color:#666'>Theme</td>"
                     f"<td>{e['Theme']}</td></tr>"
                     if e.get("Theme") else "")
        cards += f"""
<div style='background:#fff;border:1px solid #ddd;border-radius:10px;
            padding:14px 18px;margin-bottom:12px;'>
  <div style='display:flex;justify-content:space-between;margin-bottom:8px;'>
    <strong style='font-size:14px;'>{e['Event Name']}</strong>
    <span style='font-size:11px;background:#EAF3DE;color:#27500A;
                 padding:3px 9px;border-radius:10px;'>Open now</span>
  </div>
  <table style='font-size:12px;width:100%;border-collapse:collapse;'>
    <tr><td style='color:#666;width:80px;'>Location</td>
        <td>{e.get('City','')}, {e.get('Country','')}</td></tr>
    {deadline_row}{theme_row}
  </table>
  <a href='{e.get("Application URL","")}' style='font-size:11px;color:#185FA5;'>
    {e.get("Application URL","")}
  </a>
</div>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'></head>
<body style='font-family:Arial,sans-serif;max-width:680px;
             margin:0 auto;padding:24px;background:#f5f5f5;'>
  <div style='background:#fff;border-radius:12px;padding:24px;'>
    <h1 style='font-size:20px;color:#3C3489;margin:0 0 4px;'>
      TEDx Mastery — Weekly Speaker Call Update
    </h1>
    <p style='font-size:12px;color:#aaa;margin:0 0 20px;'>
      {now_str} &nbsp;·&nbsp; {len(open_calls)} open calls &nbsp;·&nbsp;
      {len(new_this_week)} new events added &nbsp;·&nbsp;
      {len(df_master)} total in database
    </p>
    {cards if cards else "<p style='color:#888;'>No open calls detected this cycle.</p>"}
    <hr style='border:none;border-top:1px solid #eee;margin:20px 0 12px;'>
    <p style='font-size:10px;color:#ccc;'>
      TEDx Mastery Program &nbsp;·&nbsp; Bobby Umar / DYPB &nbsp;·&nbsp;
      Always verify with organizers before applying
    </p>
  </div>
</body></html>"""

    subject = f"TEDx Mastery Update — {len(open_calls)} Open Calls — {now_str}"
    msg     = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = CONFIG["email_from"]
    msg["To"]      = CONFIG["email_to"]
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(CONFIG["email_from"], CONFIG["email_password"])
            srv.sendmail(CONFIG["email_from"], CONFIG["email_to"], msg.as_string())
        log.info(f"Digest sent to {CONFIG['email_to']}")
    except Exception as e:
        log.error(f"Email failed: {e}")


# ==============================================================
#  MAIN
# ==============================================================

def run(seed_path: Optional[str] = None):
    log.info("━" * 60)
    log.info("  TEDx Mastery Master Database Updater  —  Starting")
    log.info("━" * 60)

    # 1. Load existing database
    df = load_master_db()

    # 2. Seed from CSV on first run (or when explicitly passed)
    if seed_path:
        df = seed_from_csv(df, seed_path)

    # 3. Discover new events from ted.com
    df = discover_new_events(df)

    # 4. Check for open speaker calls
    df = check_speaker_calls(df)

    # 5. Save everything
    save_master_db(df)

    # 6. New-this-week summary
    new_this_week = save_new_events_summary(df)

    # 7. Email digest
    if CONFIG["email_enabled"]:
        send_digest(df, new_this_week)

    # 8. Push open calls to GHL (if webhook configured)
    try:
        from ghl_webhook import send_to_ghl
        send_to_ghl(df)
    except ImportError:
        log.debug("ghl_webhook.py not found — skipping GHL push")
    except Exception as e:
        log.warning(f"GHL push skipped: {e}")

    # ── Console summary ──────────────────────────────────────
    open_calls = df[df["Speaker Call Status"] == "open"]
    print("\n" + "━" * 60)
    print(f"  DATABASE STATS")
    print(f"  Total events    :  {len(df)}")
    print(f"  Open calls      :  {len(open_calls)}")
    print(f"  New this week   :  {len(new_this_week)}")
    print("━" * 60)
    if not open_calls.empty:
        print("\n  OPEN SPEAKER CALLS:")
        for _, r in open_calls.iterrows():
            print(f"\n  {r['Event Name']}  |  {r.get('City','')}, {r.get('Country','')}")
            if r.get("Application Deadline"):
                print(f"    Deadline : {r['Application Deadline']}")
            print(f"    Apply at : {r.get('Application URL','')}")
    print(f"\n  Master Excel  →  {CONFIG['master_db']}")
    print(f"  Master CSV    →  {CONFIG['master_csv']}")
    print(f"  New this week →  {CONFIG['new_events_csv']}")
    print("━" * 60)

    return df


# ==============================================================
#  CLI
# ==============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TEDx Mastery Master Database Updater"
    )
    parser.add_argument(
        "--seed", type=str, default=None,
        help="Path to a seed CSV (e.g. global_tedx_events_2025_2026.csv). "
             "Only needed on first run or when importing a new batch."
    )
    args = parser.parse_args()
    run(seed_path=args.seed)
