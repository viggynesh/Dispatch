#!/usr/bin/env python3
"""
data_pipeline.py — Scrapes real emergency resource data using Browser Use,
standardizes it with Claude, and saves to scraped_resources.json.

Usage:  python data_pipeline.py
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import anthropic
from browser_use import Agent, ChatAnthropic

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OUTPUT_FILE = Path(__file__).parent / "scraped_resources.json"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("data_pipeline")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    sys.exit("ANTHROPIC_API_KEY not set in environment / .env")

# The LLM that drives the browser agent (vision-capable model needed)
BROWSER_LLM = ChatAnthropic(
    model="claude-sonnet-4-20250514",
    api_key=ANTHROPIC_API_KEY,
    max_tokens=8192,
)

# Claude client for structured extraction
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Resource schema description sent to the extraction model
SCHEMA_DESCRIPTION = """\
Each resource must be a JSON object with exactly these fields:
{
  "id": "<type_prefix><3-digit-number>",   // e.g. "s001", "t001", "m001"
  "type": "shelter" | "transport" | "medical",
  "name": "<string>",
  "capacity": <int>,              // estimated total capacity (use best guess)
  "available_capacity": <int>,    // estimated available (use capacity if unknown)
  "lat": <float>,                 // latitude  (Altadena area ≈ 34.18, -118.13)
  "lng": <float>,                 // longitude
  "details": "<string>",          // useful info: amenities, restrictions, hours
  "contact": "<string>",          // phone or website; "unknown" if not found
  "status": "available"
}
"""

# ---------------------------------------------------------------------------
# Scrape tasks
# ---------------------------------------------------------------------------

SCRAPE_TASKS = [
    {
        "label": "211LA Shelters",
        "resource_type": "shelter",
        "task": (
            "Go to https://www.211la.org . "
            "Search for 'emergency shelters' near 'Altadena CA 91001'. "
            "Extract every shelter result you can find on the page: "
            "name, address, phone number, any details about capacity or "
            "amenities. Return ALL the raw text of the results."
        ),
    },
    {
        "label": "Red Cross Shelters",
        "resource_type": "shelter",
        "task": (
            "Go to https://www.redcross.org/get-help/disaster-relief-and-recovery-services/find-an-open-shelter.html . "
            "Look for any open shelters listed, especially near Southern California / Los Angeles / Altadena. "
            "Extract every shelter result: name, address, capacity, phone, details. "
            "If there is a search box, search for 'Altadena' or '91001' or 'Los Angeles'. "
            "Return ALL the raw text of the results you find."
        ),
    },
    {
        "label": "211LA Transport / Volunteer",
        "resource_type": "transport",
        "task": (
            "Go to https://www.211la.org . "
            "Search for 'emergency transportation' near '91001'. "
            "Extract every result: organization name, address, phone, "
            "services offered, hours. "
            "Return ALL the raw text of the results."
        ),
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def scrape_one(task_def: dict) -> str | None:
    """Run a single Browser Use agent and return the raw extracted text."""
    label = task_def["label"]
    log.info("Starting scrape: %s", label)
    try:
        agent = Agent(
            task=task_def["task"],
            llm=BROWSER_LLM,
            use_vision=True,
            max_failures=3,
        )
        history = await agent.run(max_steps=15)
        raw = history.final_result()
        if raw:
            log.info("Scrape '%s' returned %d chars", label, len(raw))
        else:
            log.warning("Scrape '%s' returned no result", label)
        return raw
    except Exception:
        log.exception("Scrape '%s' failed", label)
        return None


def standardize_with_claude(
    raw_text: str, resource_type: str, id_prefix: str, start_id: int
) -> list[dict]:
    """Send raw scraped text to Claude Haiku to extract structured resources."""
    if not raw_text or not raw_text.strip():
        return []

    prompt = f"""\
You are a data-extraction assistant for a disaster-relief coordination system.

Below is raw text scraped from an emergency-resource website.
Extract every distinct resource you can identify and return a JSON **array**
that conforms to this schema:

{SCHEMA_DESCRIPTION}

Rules:
- type must be "{resource_type}"
- IDs must start from "{id_prefix}{start_id:03d}" and increment
- Estimate lat/lng from addresses. Altadena CA ≈ 34.189, -118.131.
  Pasadena ≈ 34.148, -118.144. LA downtown ≈ 34.052, -118.243.
  If you cannot determine location, use 34.18, -118.13 as default.
- If capacity is unknown, estimate reasonably (shelters ~50-200, transport ~10-50).
- Return ONLY the JSON array, no markdown fences, no commentary.

Raw text:
\"\"\"
{raw_text[:12000]}
\"\"\"
"""

    try:
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[: text.rfind("```")]
        resources = json.loads(text)
        if isinstance(resources, list):
            log.info("Claude extracted %d %s resource(s)", len(resources), resource_type)
            return resources
        log.warning("Claude returned non-list for %s; skipping", resource_type)
        return []
    except Exception:
        log.exception("Claude standardization failed for %s", resource_type)
        return []


def deduplicate(resources: list[dict]) -> list[dict]:
    """Deduplicate by lowercased name, keeping the first occurrence."""
    seen: set[str] = set()
    unique: list[dict] = []
    for r in resources:
        key = r.get("name", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def reassign_ids(resources: list[dict]) -> list[dict]:
    """Reassign sequential IDs grouped by type."""
    prefix_map = {"shelter": "s", "transport": "t", "medical": "m"}
    counters = {"shelter": 1, "transport": 1, "medical": 1}
    for r in resources:
        rtype = r.get("type", "shelter")
        prefix = prefix_map.get(rtype, "x")
        idx = counters.get(rtype, 1)
        r["id"] = f"{prefix}{idx:03d}"
        counters[rtype] = idx + 1
    return resources


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def main() -> None:
    all_resources: list[dict] = []
    id_counter = 1  # global counter per scrape for initial IDs

    for task_def in SCRAPE_TASKS:
        raw_text = await scrape_one(task_def)
        if not raw_text:
            log.warning("No data from '%s'; skipping standardization", task_def["label"])
            continue

        rtype = task_def["resource_type"]
        prefix = {"shelter": "s", "transport": "t", "medical": "m"}.get(rtype, "x")
        resources = standardize_with_claude(raw_text, rtype, prefix, id_counter)
        all_resources.extend(resources)
        id_counter += len(resources)

    # Deduplicate and reassign clean IDs
    all_resources = deduplicate(all_resources)
    all_resources = reassign_ids(all_resources)

    # Save
    OUTPUT_FILE.write_text(json.dumps(all_resources, indent=2))
    log.info("Saved %d resources to %s", len(all_resources), OUTPUT_FILE)

    # Summary
    counts: dict[str, int] = {}
    for r in all_resources:
        counts[r.get("type", "unknown")] = counts.get(r.get("type", "unknown"), 0) + 1

    print("\n=== Scrape Summary ===")
    for rtype, count in sorted(counts.items()):
        print(f"  {rtype:>10}: {count}")
    print(f"  {'TOTAL':>10}: {len(all_resources)}")
    print(f"\nOutput: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
