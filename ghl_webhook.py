#!/usr/bin/env python3
"""
GHL Webhook Integration — TEDx Mastery Program
================================================
Sends open TEDx speaker calls directly into Go High Level
as contacts, opportunities, or workflow triggers.

Works two ways:
  1. Drop-in module — import and call from tedx_master_updater.py
  2. Standalone — run directly to push existing results to GHL
         python ghl_webhook.py --csv tedx_speaker_calls_found.csv

Setup (one time in GHL):
  1. GHL → Automation → Workflows → New Workflow
  2. Trigger: "Inbound Webhook"
  3. Copy the webhook URL GHL gives you
  4. Paste it into WEBHOOK_URL below (or set as env var GHL_WEBHOOK_URL)
  5. Map the fields in your GHL workflow however you want
     (create a contact, add to pipeline, send SMS, fire an email, etc.)

That's it. Every time the scraper finds an open call, it fires a POST
to that URL and your GHL workflow takes over.
"""

import os
import json
import time
import logging
import argparse
import requests
import pandas as pd
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# ==============================================================
#  CONFIGURATION  —  paste your GHL webhook URL here
# ==============================================================

# Option A: hardcode it here
WEBHOOK_URL = ""   # e.g. "https://services.leadconnectorhq.com/hooks/abc123..."

# Option B: set as environment variable GHL_WEBHOOK_URL
# (recommended for GitHub Actions — add it as a repo secret)

# If both are set, the environment variable takes priority.

CONFIG = {
    # Seconds to wait between webhook posts (be polite to GHL's servers)
    "delay_between_posts": 1.0,

    # Retry failed posts this many times before giving up
    "max_retries": 3,

    # Only send events with these statuses
    "send_statuses": ["open"],

    # Tag applied to every contact/opportunity created via this integration
    "ghl_tag": "TEDx Mastery — Scraper",

    # Source label visible in GHL contact/opp records
    "ghl_source": "TEDx Mastery Scraper",
}

# ==============================================================
#  PAYLOAD BUILDER
# ==============================================================

def build_payload(event: dict) -> dict:
    """
    Build the JSON payload sent to GHL for each open TEDx event.

    GHL Inbound Webhook workflows can read any field from this dict.
    Map them to GHL custom fields, contact properties, or pipeline
    stages inside your GHL workflow builder.

    Field names here become the variable names in GHL's workflow editor.
    Rename them to match whatever your GHL workflow expects.
    """
    return {
        # ── Core event info ──────────────────────────────────
        "event_name":         str(event.get("Event Name", "")),
        "city":               str(event.get("City", "")),
        "state_region":       str(event.get("State/Region", "")),
        "country":            str(event.get("Country", "")),
        "event_date":         str(event.get("Event Date", "")),
        "theme":              str(event.get("Theme", "")),

        # ── Speaker call specifics ───────────────────────────
        "speaker_call_status":   str(event.get("Speaker Call Status", "open")),
        "application_url":       str(event.get("Application URL", "")),
        "application_deadline":  str(event.get("Application Deadline", "")),
        "description":           str(event.get("Description", "")),

        # ── GHL metadata ────────────────────────────────────
        "tag":                CONFIG["ghl_tag"],
        "source":             CONFIG["ghl_source"],
        "sent_at":            datetime.now().isoformat(),

        # ── Convenience fields for GHL workflow logic ────────
        # Use these to trigger conditional branches in GHL
        "has_deadline":       bool(event.get("Application Deadline")),
        "is_canada":          "canada" in str(event.get("Country","")).lower(),
        "is_usa":             "united states" in str(event.get("Country","")).lower(),
        "is_uk":              "united kingdom" in str(event.get("Country","")).lower(),

        # ── Pre-built message strings ────────────────────────
        # Plug these directly into GHL email/SMS templates
        "short_summary":      _short_summary(event),
        "full_summary":       _full_summary(event),
        "sms_alert":          _sms_alert(event),
    }


def _short_summary(event: dict) -> str:
    name     = event.get("Event Name", "")
    location = f"{event.get('City','')}, {event.get('Country','')}".strip(", ")
    deadline = event.get("Application Deadline", "")
    url      = event.get("Application URL", "")
    parts    = [f"{name} ({location})"]
    if deadline:
        parts.append(f"Deadline: {deadline}")
    if url:
        parts.append(url)
    return " · ".join(parts)


def _full_summary(event: dict) -> str:
    name     = event.get("Event Name", "")
    location = f"{event.get('City','')}, {event.get('Country','')}".strip(", ")
    date     = event.get("Event Date", "")
    theme    = event.get("Theme", "")
    deadline = event.get("Application Deadline", "")
    desc     = event.get("Description", "")
    url      = event.get("Application URL", "")

    lines = [
        f"TEDx Speaker Call: {name}",
        f"Location: {location}",
    ]
    if date:     lines.append(f"Event date: {date}")
    if theme:    lines.append(f"Theme: {theme}")
    if deadline: lines.append(f"Application deadline: {deadline}")
    if desc:     lines.append(f"Details: {desc}")
    if url:      lines.append(f"Apply here: {url}")
    return "\n".join(lines)


def _sms_alert(event: dict) -> str:
    name     = event.get("Event Name", "")
    location = f"{event.get('City','')}, {event.get('Country','')}".strip(", ")
    deadline = event.get("Application Deadline", "")
    url      = event.get("Application URL", "")
    msg      = f"New TEDx call: {name} ({location})"
    if deadline:
        msg += f" — Deadline: {deadline}"
    if url:
        msg += f"\nApply: {url}"
    return msg


# ==============================================================
#  WEBHOOK SENDER
# ==============================================================

def get_webhook_url() -> str:
    """Get webhook URL from env var (preferred) or hardcoded config."""
    url = os.environ.get("GHL_WEBHOOK_URL", "").strip() or WEBHOOK_URL.strip()
    if not url:
        raise ValueError(
            "GHL webhook URL not set.\n"
            "Option A: set WEBHOOK_URL in ghl_webhook.py\n"
            "Option B: set environment variable GHL_WEBHOOK_URL"
        )
    return url


def post_event(event: dict, webhook_url: str) -> bool:
    """
    POST a single event to the GHL webhook.
    Returns True on success, False on failure.
    """
    payload = build_payload(event)
    headers = {
        "Content-Type":  "application/json",
        "User-Agent":    "TEDxMasteryScraper/1.0",
    }

    for attempt in range(1, CONFIG["max_retries"] + 1):
        try:
            resp = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 201, 202):
                log.info(f"  ✓  GHL webhook sent: {payload['event_name']}")
                return True
            else:
                log.warning(
                    f"  GHL returned {resp.status_code} for {payload['event_name']} "
                    f"(attempt {attempt}/{CONFIG['max_retries']}): {resp.text[:120]}"
                )
        except requests.RequestException as e:
            log.warning(
                f"  Webhook POST failed for {payload['event_name']} "
                f"(attempt {attempt}/{CONFIG['max_retries']}): {e}"
            )

        if attempt < CONFIG["max_retries"]:
            time.sleep(2 ** attempt)   # exponential back-off: 2s, 4s

    return False


def send_to_ghl(
    df: pd.DataFrame,
    statuses: Optional[list] = None,
    webhook_url: Optional[str] = None,
) -> dict:
    """
    Send all events matching `statuses` to GHL.

    Args:
        df:          DataFrame with event data (from master updater)
        statuses:    List of Speaker Call Status values to send.
                     Defaults to CONFIG["send_statuses"] = ["open"]
        webhook_url: Override the configured webhook URL.

    Returns:
        dict with keys "sent", "failed", "skipped"
    """
    if statuses is None:
        statuses = CONFIG["send_statuses"]

    try:
        url = webhook_url or get_webhook_url()
    except ValueError as e:
        log.error(str(e))
        return {"sent": 0, "failed": 0, "skipped": len(df)}

    to_send = df[df["Speaker Call Status"].isin(statuses)]
    log.info(f"Sending {len(to_send)} events to GHL...")

    sent = failed = 0
    for _, row in to_send.iterrows():
        success = post_event(row.to_dict(), url)
        if success:
            sent += 1
        else:
            failed += 1
        time.sleep(CONFIG["delay_between_posts"])

    skipped = len(df) - len(to_send)
    log.info(f"GHL webhook results: {sent} sent, {failed} failed, {skipped} skipped")
    return {"sent": sent, "failed": failed, "skipped": skipped}


# ==============================================================
#  STANDALONE MODE  —  push an existing CSV to GHL
# ==============================================================

def run_standalone(csv_path: str, webhook_url: Optional[str] = None):
    log.info("━" * 55)
    log.info("  GHL Webhook Push  —  Standalone Mode")
    log.info("━" * 55)

    if not pd.io.common.file_exists(csv_path):
        log.error(f"File not found: {csv_path}")
        return

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    log.info(f"Loaded {len(df)} rows from {csv_path}")

    results = send_to_ghl(df, webhook_url=webhook_url)

    print("\n" + "━" * 55)
    print(f"  GHL Push Complete")
    print(f"  Sent    : {results['sent']}")
    print(f"  Failed  : {results['failed']}")
    print(f"  Skipped : {results['skipped']}")
    print("━" * 55)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(
        description="Push TEDx open speaker calls to Go High Level"
    )
    parser.add_argument(
        "--csv", type=str,
        default="TEDx_Mastery_Master_Database.csv",
        help="Path to CSV file to push (default: TEDx_Mastery_Master_Database.csv)"
    )
    parser.add_argument(
        "--url", type=str, default=None,
        help="GHL webhook URL (overrides config and env var)"
    )
    args = parser.parse_args()
    run_standalone(args.csv, webhook_url=args.url)
