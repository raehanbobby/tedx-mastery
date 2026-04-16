#!/usr/bin/env python3
"""
TEDx Canada Speaker Call Scraper
=================================
Finds open calls for speakers at Canadian TEDx events.
Checks the official TED.com listings, known Canadian TEDx websites,
and runs targeted Google searches.

Outputs: CSV file + HTML report (openable in any browser or email client)
Optionally emails you the report via Gmail.

Run manually:  python tedx_canada_scraper.py
Schedule it:   see README.md for weekly/monthly automation options
"""

import requests
from bs4 import BeautifulSoup
import csv
import re
import smtplib
import time
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional

try:
    from googlesearch import search as google_search
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger(__name__)

# ==============================================================
#  CONFIGURATION  —  Edit this section to customise the scraper
# ==============================================================

CONFIG = {

    # --- Output files ---
    "output_csv":  "tedx_canada_results.csv",
    "output_html": "tedx_canada_report.html",

    # --- Email (optional) ---
    # Set email_enabled to True and fill in your details to receive
    # the report by email after every run.
    # Use a Gmail App Password (NOT your main Gmail password).
    # How to get one: myaccount.google.com → Security → App Passwords
    "email_enabled":  False,
    "email_from":     "",        # e.g. "you@gmail.com"
    "email_to":       "",        # e.g. "bobby@yourdomain.com"
    "email_password": "",        # Gmail App Password

    # --- Search queries (Google) ---
    # Add or remove queries to widen/narrow the search.
    "search_queries": [
        "TEDx Canada \"call for speakers\" 2025 OR 2026",
        "TEDx Ontario \"speaker application\" 2026",
        "TEDx \"British Columbia\" \"call for speakers\" 2026",
        "TEDx Quebec \"call for speakers\" 2026",
        "TEDx Alberta \"speaker application\" 2026",
        "TEDxToronto speaker application open",
        "TEDxVancouver speaker application open",
        "TEDx Canada speaker application open 2026",
        "TEDx Winnipeg speaker application 2026",
        "TEDx Ottawa speaker application 2026",
        "TEDx Calgary speaker application 2026",
    ],

    # --- Known Canadian TEDx sites to check directly ---
    # Add more as you discover them.
    "known_sites": [
        {"name": "TEDxToronto",          "url": "https://www.tedxtoronto.com",         "province": "Ontario"},
        {"name": "TEDxVancouver",         "url": "https://www.tedxvancouver.com",        "province": "British Columbia"},
        {"name": "TEDxMississauga",       "url": "https://www.tedxmississauga.com",      "province": "Ontario"},
        {"name": "TEDxWinnipeg",          "url": "https://www.tedxwinnipeg.ca",          "province": "Manitoba"},
        {"name": "TEDxSurrey",            "url": "https://www.tedxsurrey.ca",            "province": "British Columbia"},
        {"name": "TEDxCalgary",           "url": "https://www.tedxcalgary.ca",           "province": "Alberta"},
        {"name": "TEDxEdmonton",          "url": "https://www.tedxedmonton.com",         "province": "Alberta"},
        {"name": "TEDxOttawa",            "url": "https://www.tedxottawa.ca",            "province": "Ontario"},
        {"name": "TEDxHalifax",           "url": "https://www.tedxhalifax.com",          "province": "Nova Scotia"},
        {"name": "TEDxUofTScarborough",   "url": "https://www.ted.com/tedx/events/66772","province": "Ontario"},
        {"name": "TEDxMontreal",          "url": "https://www.tedxmontreal.com",         "province": "Quebec"},
        {"name": "TEDxKitchener",         "url": "https://www.tedxkitchener.com",        "province": "Ontario"},
        {"name": "TEDxRegina",            "url": "https://www.tedxregina.com",           "province": "Saskatchewan"},
        {"name": "TEDxSaskatoon",         "url": "https://www.tedxsaskatoon.com",        "province": "Saskatchewan"},
        {"name": "TEDxVictoria",          "url": "https://www.tedxvictoria.com",         "province": "British Columbia"},
        {"name": "TEDxKelowna",           "url": "https://www.tedxkelowna.com",          "province": "British Columbia"},
        {"name": "TEDxBrantford",         "url": "https://www.tedxbrantford.com",        "province": "Ontario"},
        {"name": "TEDxBurlington",        "url": "https://www.tedxburlington.com",       "province": "Ontario"},
    ],

    # --- Keywords that indicate a speaker call is open ---
    "speaker_keywords": [
        "call for speakers", "speaker application", "apply to speak",
        "apply to be a speaker", "speaker submissions", "speaker nominations",
        "become a speaker", "submit your idea", "applications are open",
        "applications now open", "now accepting", "apply now", "open call",
        "speaker portal", "speaker form", "applications open",
    ],

    # --- Polite delay between requests (seconds) ---
    "delay": 2,
}

# ==============================================================
#  DATA MODEL
# ==============================================================

@dataclass
class TEDxEvent:
    name:        str
    location:    str
    province:    str  = ""
    status:      str  = "unknown"   # open | likely_open | closed | unknown
    deadline:    str  = ""
    theme:       str  = ""
    event_date:  str  = ""
    description: str  = ""
    url:         str  = ""
    source:      str  = ""
    found_at:    str  = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

# ==============================================================
#  HELPERS
# ==============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

CANADIAN_TERMS = [
    "ontario", "british columbia", "alberta", "quebec", "manitoba",
    "saskatchewan", "nova scotia", "new brunswick", "newfoundland",
    "prince edward island", "yukon", "northwest territories", "nunavut",
    "canada", " bc ", " on ", " ab ", " qc ", " mb ",
    "toronto", "vancouver", "calgary", "edmonton", "ottawa", "winnipeg",
    "montreal", "halifax", "victoria", "kelowna", "surrey", "mississauga",
    "brampton", "markham", "richmond hill", "kitchener", "waterloo",
    "hamilton", "london ontario", "saskatoon", "regina",
]


def fetch(url: str) -> Optional[BeautifulSoup]:
    time.sleep(CONFIG["delay"])
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"  Could not fetch {url} — {e}")
        return None


def has_speaker_call(text: str) -> bool:
    t = text.lower()
    return any(kw in t for kw in CONFIG["speaker_keywords"])


def is_canadian(text: str) -> bool:
    t = text.lower()
    return any(term in t for term in CANADIAN_TERMS)


def extract_deadline(text: str) -> str:
    patterns = [
        r"(?:deadline|applications?\s+close[sd]?|apply\s+by|due)[:\s]+([A-Z][a-z]+ \d{1,2},?\s*202[56])",
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*202[56])",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_theme(text: str) -> str:
    patterns = [
        r'theme[:\s"\']+([^"\'\n.]{5,70})',
        r'"([A-Z][^"]{4,60})"',
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            c = m.group(1).strip().strip('"').strip("'")
            if 5 < len(c) < 80:
                return c
    return ""


def best_description(soup: BeautifulSoup) -> str:
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if len(t) > 60 and any(kw in t.lower() for kw in CONFIG["speaker_keywords"]):
            return t[:220]
    return ""


def deduplicate(events: List[TEDxEvent]) -> List[TEDxEvent]:
    seen, unique = set(), []
    for e in events:
        key = re.sub(r"\W+", "", e.name.lower())
        if key not in seen:
            seen.add(key)
            unique.append(e)
    return unique


# ==============================================================
#  SCRAPER 1 — TED.COM OFFICIAL EVENTS LISTING
# ==============================================================

def scrape_ted_dot_com() -> List[TEDxEvent]:
    log.info("[ 1/3 ] Scraping ted.com official events listing...")
    events, seen = [], set()

    searches = [
        "https://www.ted.com/tedx/events?q=canada",
        "https://www.ted.com/tedx/events?q=toronto",
        "https://www.ted.com/tedx/events?q=vancouver",
        "https://www.ted.com/tedx/events?q=ontario",
        "https://www.ted.com/tedx/events?q=alberta",
        "https://www.ted.com/tedx/events?q=british+columbia",
    ]

    for search_url in searches:
        soup = fetch(search_url)
        if not soup:
            continue

        for a in soup.find_all("a", href=re.compile(r"/tedx/events/\d+")):
            href = a["href"]
            full_url = f"https://www.ted.com{href}" if href.startswith("/") else href
            if full_url in seen:
                continue

            context = (a.get_text() + " " + (a.parent.get_text() if a.parent else ""))
            if not is_canadian(context):
                continue

            seen.add(full_url)
            name = a.get_text(strip=True) or "TEDx Event"

            event_soup = fetch(full_url)
            deadline, theme, desc, event_date = "", "", "", ""
            if event_soup:
                page_text = event_soup.get_text(" ", strip=True)
                deadline   = extract_deadline(page_text)
                theme      = extract_theme(page_text)
                desc       = best_description(event_soup)

            events.append(TEDxEvent(
                name=name, location="Canada",
                status="unknown", deadline=deadline,
                theme=theme, event_date=event_date,
                description=desc, url=full_url, source="ted.com"
            ))
            log.info(f"    ✓  {name}")

    log.info(f"    → {len(events)} events from ted.com")
    return events


# ==============================================================
#  SCRAPER 2 — KNOWN CANADIAN TEDX SITES
# ==============================================================

def scrape_known_sites() -> List[TEDxEvent]:
    log.info("[ 2/3 ] Checking known Canadian TEDx sites directly...")
    events = []

    # Sub-paths likely to contain speaker application info
    speaker_paths = [
        "/speakers", "/speaker-application", "/apply", "/call-for-speakers",
        "/speak", "/get-involved", "/application", "/speakers-2026",
        "/call-for-speakers-2026", "/speaker-2026", "/apply-to-speak",
        "/submit", "/speaker-portal",
    ]

    for site in CONFIG["known_sites"]:
        log.info(f"    Checking {site['name']}...")
        soup = fetch(site["url"])
        if not soup:
            continue

        page_text = soup.get_text(" ", strip=True)
        found_url = site["url"]
        found_soup = soup

        # 1. Check if main page already mentions speaker call
        if has_speaker_call(page_text):
            pass  # Already captured below

        else:
            # 2. Look for a speaker-related internal link
            found = False
            for a in soup.find_all("a", href=True):
                href = a["href"].lower()
                link_text = a.get_text(strip=True).lower()
                if any(kw in href or kw in link_text
                       for kw in ["speaker", "apply", "application", "speak"]):
                    raw_href = a["href"]
                    if raw_href.startswith("http"):
                        candidate = raw_href
                    elif raw_href.startswith("/"):
                        candidate = site["url"].rstrip("/") + raw_href
                    else:
                        continue
                    sub_soup = fetch(candidate)
                    if sub_soup and has_speaker_call(sub_soup.get_text(" ", strip=True)):
                        found_url  = candidate
                        found_soup = sub_soup
                        page_text  = sub_soup.get_text(" ", strip=True)
                        found = True
                        break

            # 3. Try common paths
            if not found:
                for path in speaker_paths:
                    candidate = site["url"].rstrip("/") + path
                    sub_soup = fetch(candidate)
                    if sub_soup and has_speaker_call(sub_soup.get_text(" ", strip=True)):
                        found_url  = candidate
                        found_soup = sub_soup
                        page_text  = sub_soup.get_text(" ", strip=True)
                        found = True
                        break

            if not found:
                log.info(f"       – No open call detected")
                continue

        deadline = extract_deadline(page_text)
        theme    = extract_theme(page_text)
        desc     = best_description(found_soup)

        events.append(TEDxEvent(
            name=site["name"],
            location=f"{site['province']}, Canada",
            province=site["province"],
            status="likely_open",
            deadline=deadline,
            theme=theme,
            description=desc,
            url=found_url,
            source=site["url"],
        ))
        log.info(f"       ✓  Speaker call found  →  {found_url}")

    log.info(f"    → {len(events)} events from known sites")
    return events


# ==============================================================
#  SCRAPER 3 — GOOGLE SEARCH
# ==============================================================

def scrape_via_google() -> List[TEDxEvent]:
    if not GOOGLE_AVAILABLE:
        log.warning(
            "[ 3/3 ] googlesearch-python not installed — skipping Google search.\n"
            "        Install it with:  pip install googlesearch-python"
        )
        return []

    log.info("[ 3/3 ] Running Google searches...")
    events, seen = [], set()

    for query in CONFIG["search_queries"]:
        log.info(f"    Searching: {query}")
        try:
            results = list(google_search(query, num_results=8, sleep_interval=3))
        except Exception as e:
            log.warning(f"    Google error: {e}")
            time.sleep(6)
            continue

        for url in results:
            if url in seen:
                continue
            if "tedx" not in url.lower() and "ted.com" not in url:
                continue
            seen.add(url)

            soup = fetch(url)
            if not soup:
                continue

            page_text = soup.get_text(" ", strip=True)

            if not (is_canadian(page_text) and has_speaker_call(page_text)):
                continue

            # Extract name from page title
            title_tag = soup.find("title")
            raw_name = title_tag.get_text(strip=True) if title_tag else url
            raw_name = re.sub(r"\s*[|\-–]\s*.+$", "", raw_name).strip()
            if not raw_name.lower().startswith("tedx"):
                raw_name = "TEDx — " + raw_name

            # Detect city
            location = "Canada"
            for city in ["Toronto", "Vancouver", "Calgary", "Edmonton", "Ottawa",
                         "Winnipeg", "Montréal", "Montreal", "Halifax", "Mississauga",
                         "Surrey", "Victoria", "Kelowna", "Saskatoon", "Regina",
                         "Markham", "Kitchener", "Hamilton", "London"]:
                if city.lower() in page_text.lower():
                    location = f"{city}, Canada"
                    break

            events.append(TEDxEvent(
                name=raw_name,
                location=location,
                status="likely_open",
                deadline=extract_deadline(page_text),
                theme=extract_theme(page_text),
                description=best_description(soup),
                url=url,
                source="google_search",
            ))
            log.info(f"       ✓  {raw_name}  ({location})")

    log.info(f"    → {len(events)} events from Google")
    return events


# ==============================================================
#  OUTPUT — CSV
# ==============================================================

def save_csv(events: List[TEDxEvent], path: str):
    fields = ["name","location","province","status","deadline",
              "theme","event_date","description","url","source","found_at"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            w.writerow(asdict(e))
    log.info(f"CSV saved  →  {path}")


# ==============================================================
#  OUTPUT — HTML REPORT
# ==============================================================

def build_html(events: List[TEDxEvent]) -> str:
    now   = datetime.now().strftime("%B %d, %Y")
    count = len(events)

    STATUS_STYLE = {
        "open":         ("#EAF3DE", "#27500A", "Open now"),
        "likely_open":  ("#EEEDFE", "#3C3489", "Likely open — verify"),
        "closed":       ("#FCEBEB", "#791F1F", "Closed"),
        "unknown":      ("#F1EFE8", "#5F5E5A", "Check status"),
    }

    if not events:
        body = ("<p style='color:#888;font-size:14px;'>"
                "No open Canadian TEDx speaker calls found this cycle. "
                "Check back next week.</p>")
    else:
        cards = []
        for e in events:
            bg, fg, label = STATUS_STYLE.get(e.status, STATUS_STYLE["unknown"])
            rows = ""
            if e.location:
                rows += f"<tr><td>Location</td><td>{e.location}</td></tr>"
            if e.deadline:
                rows += f"<tr><td>Deadline</td><td>{e.deadline}</td></tr>"
            if e.theme:
                rows += f"<tr><td>Theme</td><td>{e.theme}</td></tr>"
            if e.source:
                rows += f"<tr><td>Source</td><td>{e.source}</td></tr>"
            desc_html = (f"<p style='font-size:13px;color:#555;margin:10px 0 6px;'>"
                         f"{e.description}</p>") if e.description else ""

            cards.append(f"""
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;
            padding:16px 20px;margin-bottom:14px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              margin-bottom:10px;">
    <strong style="font-size:15px;color:#1a1a1a;">{e.name}</strong>
    <span style="font-size:11px;background:{bg};color:{fg};
                 padding:3px 10px;border-radius:10px;
                 white-space:nowrap;margin-left:10px;">{label}</span>
  </div>
  <table style="font-size:13px;color:#444;border-collapse:collapse;width:100%;">
    <colgroup><col style="width:90px;"></colgroup>
    {rows}
  </table>
  {desc_html}
  <a href="{e.url}" style="font-size:12px;color:#185FA5;
                            word-break:break-all;">{e.url}</a>
</div>""")
        body = "\n".join(cards)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TEDx Canada Speaker Calls — {now}</title>
  <style>
    td {{ padding: 3px 10px 3px 0; vertical-align: top; color: #666; }}
    td + td {{ color: #222; }}
  </style>
</head>
<body style="font-family:Arial,sans-serif;max-width:680px;
             margin:0 auto;padding:24px;background:#f5f5f5;">
  <div style="background:#fff;border-radius:12px;padding:28px;">
    <h1 style="font-size:22px;color:#1a1a1a;margin:0 0 4px;">
      TEDx Canada — Open Speaker Calls
    </h1>
    <p style="font-size:13px;color:#aaa;margin:0 0 24px;">
      {now} &nbsp;·&nbsp; {count} result{"s" if count != 1 else ""} found
    </p>
    {body}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0 14px;">
    <p style="font-size:11px;color:#bbb;">
      Generated by TEDx Canada Scraper &nbsp;·&nbsp;
      Always verify directly with organizers before applying &nbsp;·&nbsp;
      Built for Bobby Umar / DYPB
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
        log.warning(f"Email skipped — missing config: {missing}")
        return

    subject = f"TEDx Canada Speaker Calls — {datetime.now().strftime('%B %d, %Y')}"
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
#  MAIN
# ==============================================================

def run():
    log.info("━" * 55)
    log.info("  TEDx Canada Speaker Call Scraper  —  Starting")
    log.info("━" * 55)

    all_events = []
    all_events += scrape_ted_dot_com()
    all_events += scrape_known_sites()
    all_events += scrape_via_google()

    unique = deduplicate(all_events)
    log.info(f"\nTotal unique results: {len(unique)}")

    save_csv(unique, CONFIG["output_csv"])

    html = build_html(unique)
    with open(CONFIG["output_html"], "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"HTML report saved  →  {CONFIG['output_html']}")

    if CONFIG["email_enabled"]:
        send_email(html)

    # ── Console summary ──────────────────────────────────────
    print("\n" + "━" * 55)
    print(f"  {len(unique)} TEDx speaker call(s) found in Canada")
    print("━" * 55)
    for e in unique:
        print(f"\n  {e.name}")
        print(f"  Location  :  {e.location}")
        print(f"  Status    :  {e.status}")
        if e.deadline:   print(f"  Deadline  :  {e.deadline}")
        if e.theme:      print(f"  Theme     :  {e.theme}")
        print(f"  URL       :  {e.url}")
    print(f"\n  Saved  →  {CONFIG['output_csv']}")
    print(f"  Saved  →  {CONFIG['output_html']}")
    print("━" * 55)

    return unique


if __name__ == "__main__":
    run()
