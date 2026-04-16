#!/usr/bin/env python3
"""
TEDx Global Speaker Call Scraper
==================================
Finds open calls for speakers at TEDx events worldwide.
Covers: Canada, USA, UK, Australia, Europe, Asia, Latin America,
        Middle East, Africa, and more.

Outputs: CSV file + HTML report
Optionally emails you the report via Gmail.

Run manually:     python tedx_global_scraper.py
Run for a region: python tedx_global_scraper.py --regions "USA,UK"
Schedule it:      see README_GLOBAL.md for automation options
"""

import argparse
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
#  CONFIGURATION
# ==============================================================

CONFIG = {

    # --- Output files ---
    "output_csv":  "tedx_global_results.csv",
    "output_html": "tedx_global_report.html",

    # --- Email (optional) ---
    "email_enabled":  True,
    "email_from":     "raehanbobby@mg.networkanytime.com",
    "email_to":       "raehanbobby@gmail.com",
    "email_password": "57Ananda14!!",

    # --- Politeness delay between requests (seconds) ---
    "delay": 2,

    # --- Max Google results per query ---
    "google_results_per_query": 8,
}

# ==============================================================
#  REGIONS
#  Each region has: search queries + known TEDx sites to check
# ==============================================================

REGIONS = {

    # ──────────────────────────────────────────────────────────
    "Canada": {
        "terms": [
            "ontario","british columbia","alberta","quebec","manitoba",
            "saskatchewan","nova scotia","canada","toronto","vancouver",
            "calgary","edmonton","ottawa","winnipeg","montreal","halifax",
            "mississauga","surrey","markham","kitchener","victoria",
        ],
        "queries": [
            "TEDx Canada \"call for speakers\" 2025 OR 2026",
            "TEDx Ontario \"speaker application\" 2026",
            "TEDx \"British Columbia\" \"call for speakers\" 2026",
            "TEDx Quebec Alberta Manitoba \"call for speakers\" 2026",
            "TEDxToronto TEDxVancouver speaker application open 2026",
        ],
        "sites": [
            {"name": "TEDxToronto",        "url": "https://www.tedxtoronto.com",        "location": "Toronto, Canada"},
            {"name": "TEDxVancouver",       "url": "https://www.tedxvancouver.com",       "location": "Vancouver, Canada"},
            {"name": "TEDxMississauga",     "url": "https://www.tedxmississauga.com",     "location": "Mississauga, Canada"},
            {"name": "TEDxWinnipeg",        "url": "https://www.tedxwinnipeg.ca",         "location": "Winnipeg, Canada"},
            {"name": "TEDxSurrey",          "url": "https://www.tedxsurrey.ca",           "location": "Surrey, Canada"},
            {"name": "TEDxCalgary",         "url": "https://www.tedxcalgary.ca",          "location": "Calgary, Canada"},
            {"name": "TEDxEdmonton",        "url": "https://www.tedxedmonton.com",        "location": "Edmonton, Canada"},
            {"name": "TEDxOttawa",          "url": "https://www.tedxottawa.ca",           "location": "Ottawa, Canada"},
            {"name": "TEDxHalifax",         "url": "https://www.tedxhalifax.com",         "location": "Halifax, Canada"},
            {"name": "TEDxMontreal",        "url": "https://www.tedxmontreal.com",        "location": "Montreal, Canada"},
            {"name": "TEDxVictoria",        "url": "https://www.tedxvictoria.com",        "location": "Victoria, Canada"},
            {"name": "TEDxKelowna",         "url": "https://www.tedxkelowna.com",         "location": "Kelowna, Canada"},
            {"name": "TEDxKitchener",       "url": "https://www.tedxkitchener.com",       "location": "Kitchener, Canada"},
            {"name": "TEDxBurlington",      "url": "https://www.tedxburlington.com",      "location": "Burlington, Canada"},
            {"name": "TEDxRegina",          "url": "https://www.tedxregina.com",          "location": "Regina, Canada"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "USA": {
        "terms": [
            "united states","u.s.","usa"," new york"," los angeles",
            "chicago","houston","phoenix","philadelphia","san antonio",
            "san diego","dallas","san jose","austin","seattle","denver",
            "boston","nashville","atlanta","miami","portland","minneapolis",
            "california","texas","florida","illinois","new york state",
            "ohio","georgia","north carolina","michigan","virginia",
            "washington state","arizona","massachusetts","tennessee","indiana",
        ],
        "queries": [
            "TEDx USA \"call for speakers\" 2026",
            "TEDx \"New York\" \"speaker application\" 2026 open",
            "TEDx California \"call for speakers\" 2026",
            "TEDx Texas Illinois Florida \"call for speakers\" 2026",
            "TEDx Chicago Boston Seattle \"speaker application\" 2026",
            "TEDx Atlanta Miami Nashville \"call for speakers\" 2026",
            "TEDx \"Pacific Northwest\" \"call for speakers\" 2026",
            "TEDx university college \"call for speakers\" 2026 USA",
        ],
        "sites": [
            {"name": "TEDxNewYork",         "url": "https://www.tedxnewyork.com",         "location": "New York, USA"},
            {"name": "TEDxMidAtlantic",     "url": "https://www.tedxmidatlantic.com",     "location": "Washington DC, USA"},
            {"name": "TEDxChicago",         "url": "https://www.tedxchicago.com",         "location": "Chicago, USA"},
            {"name": "TEDxSanFrancisco",    "url": "https://www.tedxsanfrancisco.com",    "location": "San Francisco, USA"},
            {"name": "TEDxAtlanta",         "url": "https://www.tedxatlanta.com",         "location": "Atlanta, USA"},
            {"name": "TEDxBoston",          "url": "https://www.tedxboston.org",          "location": "Boston, USA"},
            {"name": "TEDxMiami",           "url": "https://www.tedxmiami.com",           "location": "Miami, USA"},
            {"name": "TEDxNashville",       "url": "https://www.tedxnashville.com",       "location": "Nashville, USA"},
            {"name": "TEDxSeattle",         "url": "https://www.tedxseattle.com",         "location": "Seattle, USA"},
            {"name": "TEDxDenver",          "url": "https://www.tedxdenver.com",          "location": "Denver, USA"},
            {"name": "TEDxPortland",        "url": "https://www.tedxportland.com",        "location": "Portland, USA"},
            {"name": "TEDxAustin",          "url": "https://www.tedxaustin.com",          "location": "Austin, USA"},
            {"name": "TEDxHouston",         "url": "https://www.tedxhouston.com",         "location": "Houston, USA"},
            {"name": "TEDxPhiladelphia",    "url": "https://www.tedxphiladelphia.com",    "location": "Philadelphia, USA"},
            {"name": "TEDxLosAngeles",      "url": "https://www.tedxlosangeles.com",      "location": "Los Angeles, USA"},
            {"name": "TEDxMinneapolis",     "url": "https://www.tedxminneapolis.com",     "location": "Minneapolis, USA"},
            {"name": "TEDxPittsburgh",      "url": "https://www.tedxpittsburgh.com",      "location": "Pittsburgh, USA"},
            {"name": "TEDxSanDiego",        "url": "https://www.tedxsandiego.com",        "location": "San Diego, USA"},
            {"name": "TEDxColumbus",        "url": "https://www.tedxcolumbus.com",        "location": "Columbus, USA"},
            {"name": "TEDxRaleigh",         "url": "https://www.tedxraleigh.com",         "location": "Raleigh, USA"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "UK": {
        "terms": [
            "united kingdom","england","scotland","wales","northern ireland",
            "london","manchester","birmingham","leeds","glasgow","liverpool",
            "bristol","sheffield","edinburgh","cardiff","belfast",
            "brighton","cambridge","oxford","newcastle",
        ],
        "queries": [
            "TEDx UK \"call for speakers\" 2025 OR 2026",
            "TEDx London Manchester Birmingham \"speaker application\" 2026",
            "TEDx Scotland Wales \"call for speakers\" 2026",
            "TEDx \"United Kingdom\" speaker application open 2026",
            "TEDx Edinburgh Bristol Leeds \"call for speakers\" 2026",
        ],
        "sites": [
            {"name": "TEDxLondon",          "url": "https://www.tedxlondon.com",          "location": "London, UK"},
            {"name": "TEDxManchester",      "url": "https://www.tedxmanchester.com",      "location": "Manchester, UK"},
            {"name": "TEDxBirmingham",      "url": "https://www.tedxbirmingham.com",      "location": "Birmingham, UK"},
            {"name": "TEDxGlasgow",         "url": "https://www.tedxglasgow.com",         "location": "Glasgow, UK"},
            {"name": "TEDxEdinburgh",       "url": "https://www.tedxedinburgh.com",       "location": "Edinburgh, UK"},
            {"name": "TEDxBristol",         "url": "https://www.tedxbristol.com",         "location": "Bristol, UK"},
            {"name": "TEDxLeeds",           "url": "https://www.tedxleeds.com",           "location": "Leeds, UK"},
            {"name": "TEDxCardiff",         "url": "https://www.tedxcardiff.com",         "location": "Cardiff, UK"},
            {"name": "TEDxOxford",          "url": "https://www.tedxoxford.com",          "location": "Oxford, UK"},
            {"name": "TEDxCambridge",       "url": "https://www.tedxcambridge.com",       "location": "Cambridge, UK"},
            {"name": "TEDxBrighton",        "url": "https://www.tedxbrighton.com",        "location": "Brighton, UK"},
            {"name": "TEDxNorthernQuarter", "url": "https://www.tedxnorthernquarter.com", "location": "Manchester, UK"},
            {"name": "TEDxRailwayVillage",  "url": "https://www.tedxrailwayvillage.com",  "location": "Swindon, UK"},
            {"name": "TEDxButeStreet",      "url": "https://www.tedxbutestreet.com",      "location": "Cardiff, UK"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "Australia": {
        "terms": [
            "australia","sydney","melbourne","brisbane","perth","adelaide",
            "canberra","hobart","darwin","queensland","new south wales",
            "victoria australia","western australia","south australia",
        ],
        "queries": [
            "TEDx Australia \"call for speakers\" 2025 OR 2026",
            "TEDx Sydney Melbourne Brisbane \"speaker application\" 2026",
            "TEDx Perth Adelaide Canberra \"call for speakers\" 2026",
            "TEDx Australia speaker application open 2026",
        ],
        "sites": [
            {"name": "TEDxSydney",          "url": "https://www.tedxsydney.com",          "location": "Sydney, Australia"},
            {"name": "TEDxMelbourne",       "url": "https://www.tedxmelbourne.com",       "location": "Melbourne, Australia"},
            {"name": "TEDxBrisbane",        "url": "https://www.tedxbrisbane.com",        "location": "Brisbane, Australia"},
            {"name": "TEDxPerth",           "url": "https://www.tedxperth.com",           "location": "Perth, Australia"},
            {"name": "TEDxAdelaide",        "url": "https://www.tedxadelaide.com",        "location": "Adelaide, Australia"},
            {"name": "TEDxCanberra",        "url": "https://www.tedxcanberra.com",        "location": "Canberra, Australia"},
            {"name": "TEDxGoldCoast",       "url": "https://www.tedxgoldcoast.com",       "location": "Gold Coast, Australia"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "Europe": {
        "terms": [
            "germany","france","netherlands","spain","italy","sweden",
            "switzerland","belgium","austria","denmark","norway","finland",
            "poland","portugal","czech republic","berlin","paris","amsterdam",
            "barcelona","madrid","rome","milan","stockholm","zurich",
            "brussels","vienna","copenhagen","oslo","helsinki","warsaw",
        ],
        "queries": [
            "TEDx Germany France Netherlands \"call for speakers\" 2026",
            "TEDx Berlin Paris Amsterdam \"speaker application\" 2026",
            "TEDx Spain Italy Sweden \"call for speakers\" 2026",
            "TEDx Switzerland Belgium Austria \"speaker application\" 2026",
            "TEDx Europe \"call for speakers\" 2026 open application",
            "TEDx Scandinavia Denmark Norway Finland \"call for speakers\" 2026",
        ],
        "sites": [
            {"name": "TEDxBerlin",          "url": "https://www.tedxberlin.de",           "location": "Berlin, Germany"},
            {"name": "TEDxParis",           "url": "https://www.tedxparis.com",           "location": "Paris, France"},
            {"name": "TEDxAmsterdam",       "url": "https://www.tedxamsterdam.com",       "location": "Amsterdam, Netherlands"},
            {"name": "TEDxBarcelona",       "url": "https://www.tedxbarcelona.com",       "location": "Barcelona, Spain"},
            {"name": "TEDxMadrid",          "url": "https://www.tedxmadrid.com",          "location": "Madrid, Spain"},
            {"name": "TEDxRome",            "url": "https://www.tedxrome.com",            "location": "Rome, Italy"},
            {"name": "TEDxMilan",           "url": "https://www.tedxmilan.com",           "location": "Milan, Italy"},
            {"name": "TEDxStockholm",       "url": "https://www.tedxstockholm.com",       "location": "Stockholm, Sweden"},
            {"name": "TEDxZurich",          "url": "https://www.tedxzurich.com",          "location": "Zurich, Switzerland"},
            {"name": "TEDxBrussels",        "url": "https://www.tedxbrussels.eu",         "location": "Brussels, Belgium"},
            {"name": "TEDxVienna",          "url": "https://www.tedxvienna.at",           "location": "Vienna, Austria"},
            {"name": "TEDxCopenhagen",      "url": "https://www.tedxcopenhagen.dk",       "location": "Copenhagen, Denmark"},
            {"name": "TEDxWarsaw",          "url": "https://www.tedxwarsaw.com",          "location": "Warsaw, Poland"},
            {"name": "TEDxLisbon",          "url": "https://www.tedxlisbon.com",          "location": "Lisbon, Portugal"},
            {"name": "TEDxHSRW",            "url": "https://www.tedxhsrw.com",            "location": "Kleve, Germany"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "Asia": {
        "terms": [
            "india","japan","singapore","hong kong","south korea","china",
            "indonesia","philippines","malaysia","thailand","vietnam",
            "taiwan","bangladesh","pakistan","mumbai","delhi","bangalore",
            "tokyo","osaka","singapore","seoul","jakarta","manila",
            "kuala lumpur","bangkok","ho chi minh","taipei","dhaka",
        ],
        "queries": [
            "TEDx India \"call for speakers\" 2026",
            "TEDx Japan Singapore \"speaker application\" 2026",
            "TEDx \"South Korea\" Philippines Malaysia \"call for speakers\" 2026",
            "TEDx Mumbai Delhi Bangalore \"call for speakers\" 2026",
            "TEDx Tokyo Seoul Jakarta \"call for speakers\" 2026",
            "TEDx Asia Pacific \"speaker application\" open 2026",
        ],
        "sites": [
            {"name": "TEDxGateway (Mumbai)",  "url": "https://www.tedxgateway.com",       "location": "Mumbai, India"},
            {"name": "TEDxDelhi",             "url": "https://www.tedxdelhi.com",          "location": "Delhi, India"},
            {"name": "TEDxBangalore",         "url": "https://www.tedxbangalore.com",      "location": "Bangalore, India"},
            {"name": "TEDxTokyo",             "url": "https://www.tedxtokyo.com",          "location": "Tokyo, Japan"},
            {"name": "TEDxSingapore",         "url": "https://www.tedxsingapore.sg",       "location": "Singapore"},
            {"name": "TEDxSeoul",             "url": "https://www.tedxseoul.com",          "location": "Seoul, South Korea"},
            {"name": "TEDxKualaLumpur",       "url": "https://www.tedxkualalumpur.com",    "location": "Kuala Lumpur, Malaysia"},
            {"name": "TEDxJakarta",           "url": "https://www.tedxjakarta.com",        "location": "Jakarta, Indonesia"},
            {"name": "TEDxManila",            "url": "https://www.tedxmanila.com",         "location": "Manila, Philippines"},
            {"name": "TEDxBangkok",           "url": "https://www.tedxbangkok.com",        "location": "Bangkok, Thailand"},
            {"name": "TEDxTaipei",            "url": "https://www.tedxtaipei.com",         "location": "Taipei, Taiwan"},
            {"name": "TEDxHongKong",          "url": "https://www.tedxhongkong.com",       "location": "Hong Kong"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "MiddleEast": {
        "terms": [
            "dubai","abu dhabi","uae","united arab emirates","saudi arabia",
            "israel","qatar","bahrain","kuwait","jordan","lebanon","egypt",
            "riyadh","doha","tel aviv","cairo","amman","beirut",
        ],
        "queries": [
            "TEDx Dubai UAE \"call for speakers\" 2026",
            "TEDx \"Middle East\" \"call for speakers\" 2026",
            "TEDx Saudi Arabia Qatar Israel \"speaker application\" 2026",
            "TEDx Cairo Amman Beirut \"call for speakers\" 2026",
        ],
        "sites": [
            {"name": "TEDxDubai",           "url": "https://www.tedxdubai.com",           "location": "Dubai, UAE"},
            {"name": "TEDxAbuDhabi",        "url": "https://www.tedxabudhabi.ae",         "location": "Abu Dhabi, UAE"},
            {"name": "TEDxDoha",            "url": "https://www.tedxdoha.com",            "location": "Doha, Qatar"},
            {"name": "TEDxTelAviv",         "url": "https://www.tedxtelaviv.com",         "location": "Tel Aviv, Israel"},
            {"name": "TEDxCairo",           "url": "https://www.tedxcairo.com",           "location": "Cairo, Egypt"},
            {"name": "TEDxAmman",           "url": "https://www.tedxamman.com",           "location": "Amman, Jordan"},
            {"name": "TEDxRiyadh",          "url": "https://www.tedxriyadh.com",          "location": "Riyadh, Saudi Arabia"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "LatinAmerica": {
        "terms": [
            "brazil","mexico","argentina","colombia","chile","peru",
            "venezuela","ecuador","uruguay","paraguay","bolivia",
            "sao paulo","buenos aires","bogota","lima","santiago",
            "mexico city","caracas","quito","montevideo",
        ],
        "queries": [
            "TEDx Brazil Mexico Argentina \"call for speakers\" 2026",
            "TEDx \"Latin America\" \"call for speakers\" 2026",
            "TEDx Colombia Chile Peru \"speaker application\" 2026",
            "TEDx \"São Paulo\" \"Buenos Aires\" \"call for speakers\" 2026",
        ],
        "sites": [
            {"name": "TEDxSaoPaulo",        "url": "https://www.tedxsaopaulo.com.br",     "location": "São Paulo, Brazil"},
            {"name": "TEDxBuenosAires",     "url": "https://www.tedxbuenosaires.com",     "location": "Buenos Aires, Argentina"},
            {"name": "TEDxBogota",          "url": "https://www.tedxbogota.com",          "location": "Bogotá, Colombia"},
            {"name": "TEDxLima",            "url": "https://www.tedxlima.com",            "location": "Lima, Peru"},
            {"name": "TEDxSantiago",        "url": "https://www.tedxsantiago.com",        "location": "Santiago, Chile"},
            {"name": "TEDxMexicoCity",      "url": "https://www.tedxmexicocity.mx",       "location": "Mexico City, Mexico"},
            {"name": "TEDxMontevideo",      "url": "https://www.tedxmontevideo.com",      "location": "Montevideo, Uruguay"},
        ],
    },

    # ──────────────────────────────────────────────────────────
    "Africa": {
        "terms": [
            "south africa","nigeria","kenya","ghana","ethiopia","tanzania",
            "rwanda","uganda","senegal","cameroon","johannesburg","cape town",
            "lagos","nairobi","accra","addis ababa","kigali","kampala",
            "dakar","dar es salaam",
        ],
        "queries": [
            "TEDx Africa \"call for speakers\" 2026",
            "TEDx \"South Africa\" Kenya Nigeria \"speaker application\" 2026",
            "TEDx Johannesburg Nairobi Lagos \"call for speakers\" 2026",
            "TEDx Rwanda Ghana Ethiopia \"call for speakers\" 2026",
        ],
        "sites": [
            {"name": "TEDxJohannesburg",    "url": "https://www.tedxjohannesburg.co.za",  "location": "Johannesburg, South Africa"},
            {"name": "TEDxCapeTown",        "url": "https://www.tedxcapetown.org",        "location": "Cape Town, South Africa"},
            {"name": "TEDxLagos",           "url": "https://www.tedxlagos.com",           "location": "Lagos, Nigeria"},
            {"name": "TEDxNairobi",         "url": "https://www.tedxnairobi.com",         "location": "Nairobi, Kenya"},
            {"name": "TEDxAccra",           "url": "https://www.tedxaccra.com",           "location": "Accra, Ghana"},
            {"name": "TEDxKigali",          "url": "https://www.tedxkigali.com",          "location": "Kigali, Rwanda"},
            {"name": "TEDxAddisAbaba",      "url": "https://www.tedxaddisababa.com",      "location": "Addis Ababa, Ethiopia"},
        ],
    },
}

ALL_REGION_NAMES = list(REGIONS.keys())

# ==============================================================
#  DATA MODEL
# ==============================================================

@dataclass
class TEDxEvent:
    name:        str
    location:    str
    region:      str  = ""
    status:      str  = "unknown"
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
    "Accept-Language": "en-US,en;q=0.9",
}

SPEAKER_KEYWORDS = [
    "call for speakers", "speaker application", "apply to speak",
    "apply to be a speaker", "speaker submissions", "speaker nominations",
    "become a speaker", "submit your idea", "applications are open",
    "applications now open", "now accepting", "apply now", "open call",
    "speaker portal", "speaker form", "applications open",
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
    return any(kw in t for kw in SPEAKER_KEYWORDS)


def region_match(text: str, region_data: dict) -> bool:
    t = text.lower()
    return any(term in t for term in region_data["terms"])


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
        if len(t) > 60 and any(kw in t.lower() for kw in SPEAKER_KEYWORDS):
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

def scrape_ted_dot_com(active_regions: List[str]) -> List[TEDxEvent]:
    log.info("[ 1/3 ] Scraping ted.com official events listing...")
    events, seen = [], set()

    # Build search terms from all active regions
    all_terms = set()
    for rname in active_regions:
        rdata = REGIONS[rname]
        for term in rdata["terms"][:6]:   # top 6 per region
            all_terms.add(term.strip())

    search_urls = [
        f"https://www.ted.com/tedx/events?q={t.replace(' ', '+')}"
        for t in list(all_terms)[:20]     # max 20 ted.com fetches
    ]

    for search_url in search_urls:
        soup = fetch(search_url)
        if not soup:
            continue

        for a in soup.find_all("a", href=re.compile(r"/tedx/events/\d+")):
            href = a["href"]
            full_url = f"https://www.ted.com{href}" if href.startswith("/") else href
            if full_url in seen:
                continue

            context = (a.get_text() + " " +
                       (a.parent.get_text() if a.parent else ""))

            matched_region = next(
                (rname for rname in active_regions
                 if region_match(context, REGIONS[rname])),
                None
            )
            if not matched_region:
                continue

            seen.add(full_url)
            name = a.get_text(strip=True) or "TEDx Event"

            event_soup = fetch(full_url)
            deadline = theme = desc = ""
            if event_soup:
                pt = event_soup.get_text(" ", strip=True)
                deadline = extract_deadline(pt)
                theme    = extract_theme(pt)
                desc     = best_description(event_soup)

            events.append(TEDxEvent(
                name=name, location="", region=matched_region,
                status="unknown", deadline=deadline, theme=theme,
                description=desc, url=full_url, source="ted.com"
            ))
            log.info(f"    ✓  [{matched_region}]  {name}")

    log.info(f"    → {len(events)} events from ted.com")
    return events


# ==============================================================
#  SCRAPER 2 — KNOWN SITES PER REGION
# ==============================================================

SPEAKER_PATHS = [
    "/speakers", "/speaker-application", "/apply", "/call-for-speakers",
    "/speak", "/get-involved", "/application", "/speakers-2026",
    "/call-for-speakers-2026", "/speaker-2026", "/apply-to-speak",
    "/submit", "/speaker-portal", "/nominate",
]


def scrape_known_sites(active_regions: List[str]) -> List[TEDxEvent]:
    log.info("[ 2/3 ] Checking known TEDx sites for all active regions...")
    events = []

    for rname in active_regions:
        rdata  = REGIONS[rname]
        sites  = rdata.get("sites", [])
        log.info(f"  Region: {rname} — {len(sites)} sites to check")

        for site in sites:
            log.info(f"    Checking {site['name']}...")
            soup = fetch(site["url"])
            if not soup:
                continue

            page_text  = soup.get_text(" ", strip=True)
            found_url  = site["url"]
            found_soup = soup

            if not has_speaker_call(page_text):
                # Look for speaker link on page
                resolved = False
                for a in soup.find_all("a", href=True):
                    href_l    = a["href"].lower()
                    link_text = a.get_text(strip=True).lower()
                    if any(kw in href_l or kw in link_text
                           for kw in ["speaker", "apply", "application", "speak"]):
                        raw_href = a["href"]
                        candidate = (raw_href if raw_href.startswith("http")
                                     else site["url"].rstrip("/") + raw_href
                                     if raw_href.startswith("/") else None)
                        if candidate:
                            sub = fetch(candidate)
                            if sub and has_speaker_call(sub.get_text(" ", strip=True)):
                                found_url = candidate
                                found_soup = sub
                                page_text  = sub.get_text(" ", strip=True)
                                resolved   = True
                                break

                if not resolved:
                    for path in SPEAKER_PATHS:
                        candidate = site["url"].rstrip("/") + path
                        sub = fetch(candidate)
                        if sub and has_speaker_call(sub.get_text(" ", strip=True)):
                            found_url = candidate
                            found_soup = sub
                            page_text  = sub.get_text(" ", strip=True)
                            resolved   = True
                            break

                if not resolved:
                    log.info(f"       – No open call detected")
                    continue

            events.append(TEDxEvent(
                name=site["name"],
                location=site.get("location", ""),
                region=rname,
                status="likely_open",
                deadline=extract_deadline(page_text),
                theme=extract_theme(page_text),
                description=best_description(found_soup),
                url=found_url,
                source=site["url"],
            ))
            log.info(f"       ✓  Speaker call found  →  {found_url}")

    log.info(f"    → {len(events)} events from known sites")
    return events


# ==============================================================
#  SCRAPER 3 — GOOGLE SEARCH
# ==============================================================

def scrape_via_google(active_regions: List[str]) -> List[TEDxEvent]:
    if not GOOGLE_AVAILABLE:
        log.warning(
            "[ 3/3 ] googlesearch-python not installed — skipping Google search.\n"
            "        Install with:  pip install googlesearch-python"
        )
        return []

    log.info("[ 3/3 ] Running Google searches for all active regions...")
    events, seen = [], set()

    for rname in active_regions:
        rdata   = REGIONS[rname]
        queries = rdata.get("queries", [])
        log.info(f"  Region: {rname} — {len(queries)} queries")

        for query in queries:
            log.info(f"    Searching: {query}")
            try:
                results = list(google_search(
                    query,
                    num_results=CONFIG["google_results_per_query"],
                    sleep_interval=3
                ))
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

                if not (region_match(page_text, rdata) and
                        has_speaker_call(page_text)):
                    continue

                title_tag = soup.find("title")
                raw_name  = title_tag.get_text(strip=True) if title_tag else url
                raw_name  = re.sub(r"\s*[|\-–]\s*.+$", "", raw_name).strip()
                if not raw_name.lower().startswith("tedx"):
                    raw_name = "TEDx — " + raw_name

                events.append(TEDxEvent(
                    name=raw_name,
                    location=rname,
                    region=rname,
                    status="likely_open",
                    deadline=extract_deadline(page_text),
                    theme=extract_theme(page_text),
                    description=best_description(soup),
                    url=url,
                    source="google_search",
                ))
                log.info(f"       ✓  {raw_name}")

    log.info(f"    → {len(events)} events via Google")
    return events


# ==============================================================
#  OUTPUT — CSV
# ==============================================================

def save_csv(events: List[TEDxEvent], path: str):
    fields = ["name","location","region","status","deadline","theme",
              "event_date","description","url","source","found_at"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            w.writerow(asdict(e))
    log.info(f"CSV saved  →  {path}")


# ==============================================================
#  OUTPUT — HTML REPORT
# ==============================================================

STATUS_STYLE = {
    "open":        ("#EAF3DE", "#27500A", "Open now"),
    "likely_open": ("#EEEDFE", "#3C3489", "Likely open — verify"),
    "closed":      ("#FCEBEB", "#791F1F", "Closed"),
    "unknown":     ("#F1EFE8", "#5F5E5A", "Check status"),
}

REGION_COLORS = {
    "Canada":      "#E6F1FB",
    "USA":         "#EAF3DE",
    "UK":          "#EEEDFE",
    "Australia":   "#FAEEDA",
    "Europe":      "#FAECE7",
    "Asia":        "#FBEAF0",
    "MiddleEast":  "#F1EFE8",
    "LatinAmerica":"#EAF3DE",
    "Africa":      "#FAEEDA",
}


def build_html(events: List[TEDxEvent], active_regions: List[str]) -> str:
    now   = datetime.now().strftime("%B %d, %Y")
    count = len(events)

    # Group by region
    by_region = {r: [] for r in active_regions}
    for e in events:
        by_region.setdefault(e.region, []).append(e)

    sections = ""
    for rname in active_regions:
        region_events = by_region.get(rname, [])
        if not region_events:
            continue

        rcolor = REGION_COLORS.get(rname, "#F1EFE8")
        cards  = ""
        for e in region_events:
            bg, fg, label = STATUS_STYLE.get(e.status, STATUS_STYLE["unknown"])
            rows = ""
            if e.location: rows += f"<tr><td>Location</td><td>{e.location}</td></tr>"
            if e.deadline: rows += f"<tr><td>Deadline</td><td>{e.deadline}</td></tr>"
            if e.theme:    rows += f"<tr><td>Theme</td><td>{e.theme}</td></tr>"
            if e.source:   rows += f"<tr><td>Source</td><td>{e.source}</td></tr>"
            desc_html = (f"<p style='font-size:13px;color:#555;margin:10px 0 6px;'>"
                         f"{e.description}</p>") if e.description else ""

            cards += f"""
<div style="background:#fff;border:1px solid #e0e0e0;border-radius:10px;
            padding:14px 18px;margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              margin-bottom:8px;">
    <strong style="font-size:14px;color:#1a1a1a;">{e.name}</strong>
    <span style="font-size:11px;background:{bg};color:{fg};
                 padding:3px 9px;border-radius:10px;
                 white-space:nowrap;margin-left:8px;">{label}</span>
  </div>
  <table style="font-size:12px;color:#444;border-collapse:collapse;width:100%;">
    <colgroup><col style="width:80px;"></colgroup>
    {rows}
  </table>
  {desc_html}
  <a href="{e.url}" style="font-size:11px;color:#185FA5;
                            word-break:break-all;">{e.url}</a>
</div>"""

        sections += f"""
<div style="margin-bottom:28px;">
  <div style="background:{rcolor};border-radius:8px;padding:8px 14px;
              margin-bottom:12px;display:inline-block;">
    <strong style="font-size:13px;color:#333;">
      {rname} &nbsp;·&nbsp; {len(region_events)} result{"s" if len(region_events)!=1 else ""}
    </strong>
  </div>
  {cards}
</div>"""

    if not sections:
        sections = ("<p style='color:#888;font-size:14px;'>"
                    "No open TEDx speaker calls found this cycle.</p>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>TEDx Global Speaker Calls — {now}</title>
  <style>
    td {{ padding: 3px 10px 3px 0; vertical-align: top; color: #666; }}
    td + td {{ color: #222; }}
  </style>
</head>
<body style="font-family:Arial,sans-serif;max-width:700px;
             margin:0 auto;padding:24px;background:#f5f5f5;">
  <div style="background:#fff;border-radius:12px;padding:28px;">
    <h1 style="font-size:22px;color:#1a1a1a;margin:0 0 4px;">
      TEDx Global — Open Speaker Calls
    </h1>
    <p style="font-size:13px;color:#aaa;margin:0 0 8px;">
      {now} &nbsp;·&nbsp; {count} result{"s" if count!=1 else ""} across
      {len(active_regions)} region{"s" if len(active_regions)!=1 else ""}
    </p>
    <p style="font-size:12px;color:#bbb;margin:0 0 28px;">
      Regions: {" · ".join(active_regions)}
    </p>
    {sections}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0 14px;">
    <p style="font-size:11px;color:#bbb;">
      Generated by TEDx Global Scraper &nbsp;·&nbsp;
      Always verify directly with organizers before applying &nbsp;·&nbsp;
      Built for Bobby Umar / DYPB
    </p>
  </div>
</body>
</html>"""


# ==============================================================
#  EMAIL
# ==============================================================

def send_email(html: str, active_regions: List[str]):
    if not CONFIG["email_enabled"]:
        return
    missing = [k for k in ("email_from","email_to","email_password") if not CONFIG[k]]
    if missing:
        log.warning(f"Email skipped — missing config: {missing}")
        return

    regions_str = ", ".join(active_regions)
    subject = (f"TEDx Speaker Calls ({regions_str}) — "
               f"{datetime.now().strftime('%B %d, %Y')}")
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

def run(active_regions: Optional[List[str]] = None):
    if active_regions is None:
        active_regions = ALL_REGION_NAMES

    # Validate
    invalid = [r for r in active_regions if r not in REGIONS]
    if invalid:
        log.error(f"Unknown regions: {invalid}")
        log.error(f"Valid options: {ALL_REGION_NAMES}")
        return []

    log.info("━" * 60)
    log.info("  TEDx Global Speaker Call Scraper  —  Starting")
    log.info(f"  Regions: {', '.join(active_regions)}")
    log.info("━" * 60)

    all_events  = []
    all_events += scrape_ted_dot_com(active_regions)
    all_events += scrape_known_sites(active_regions)
    all_events += scrape_via_google(active_regions)

    unique = deduplicate(all_events)
    log.info(f"\nTotal unique results: {len(unique)}")

    save_csv(unique, CONFIG["output_csv"])

    html = build_html(unique, active_regions)
    with open(CONFIG["output_html"], "w", encoding="utf-8") as f:
        f.write(html)
    log.info(f"HTML report saved  →  {CONFIG['output_html']}")

    if CONFIG["email_enabled"]:
        send_email(html, active_regions)

    # ── Console summary ──────────────────────────────────────
    print("\n" + "━" * 60)
    print(f"  {len(unique)} TEDx speaker call(s) found globally")
    print("━" * 60)
    for rname in active_regions:
        region_events = [e for e in unique if e.region == rname]
        if region_events:
            print(f"\n  ── {rname} ({len(region_events)}) ──")
            for e in region_events:
                print(f"    {e.name}  |  {e.location}")
                if e.deadline: print(f"      Deadline : {e.deadline}")
                print(f"      URL      : {e.url}")
    print(f"\n  Saved  →  {CONFIG['output_csv']}")
    print(f"  Saved  →  {CONFIG['output_html']}")
    print("━" * 60)
    return unique


# ==============================================================
#  CLI  —  python tedx_global_scraper.py --regions "USA,UK"
# ==============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="TEDx Global Speaker Call Scraper"
    )
    parser.add_argument(
        "--regions",
        type=str,
        default=None,
        help=(f"Comma-separated list of regions to search. "
              f"Options: {', '.join(ALL_REGION_NAMES)}. "
              f"Default: all regions.")
    )
    args = parser.parse_args()

    regions = (
        [r.strip() for r in args.regions.split(",")]
        if args.regions else ALL_REGION_NAMES
    )

    run(regions)
