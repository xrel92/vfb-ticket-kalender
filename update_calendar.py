#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

SOURCE_URL = "https://tickets.vfb.de/shop?language=1&shopid=103&nextstate=2&lpShortcutId=5"
OUT = Path("docs/vfb-ticketkalender.ics")
TZ = ZoneInfo("Europe/Berlin")

GAME_RE = re.compile(
    r"VfB Stuttgart\s*[-–]\s*(?P<opponent>.+?)\s+"
    r"(?:(?:Bundesliga|Testspiel|DFB-Pokal|Champions League|Europa League|"
    r"Conference League|Freundschaftsspiel|VfB Saison Opening).*?\s+)?"
    r"(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.\s*"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE | re.DOTALL,
)

DATE_RE = re.compile(
    r"(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.\s*"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})",
    re.IGNORECASE,
)

SALE_RE = re.compile(
    r"(?P<label>Mitglieder(?:verkauf)?|Freier Verkauf|Verkaufsstart)?\s*:?\s*ab\s+"
    r"(?P<weekday>Mo|Di|Mi|Do|Fr|Sa|So)\.,?\s*"
    r"(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.?,?\s*"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*Uhr",
    re.IGNORECASE,
)

def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()

def esc(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))

def fold(line: str) -> str:
    result, current = [], ""
    for char in line:
        candidate = current + char
        if len(candidate.encode("utf-8")) > 73:
            result.append(current)
            current = " " + char
        else:
            current = candidate
    result.append(current)
    return "\r\n".join(result)

def make_uid(kind: str, title: str, start: datetime) -> str:
    raw = f"{kind}|{title}|{start.isoformat()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24] + "@vfb-ticketkalender"

def vevent(kind: str, title: str, start: datetime, end: datetime,
           description: str, location: str = "", alarm_minutes: int | None = None) -> list[str]:
    stamp = datetime.now(TZ).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{make_uid(kind, title, start)}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID=Europe/Berlin:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{esc(title)}",
        f"DESCRIPTION:{esc(description)}",
        f"URL:{SOURCE_URL}",
    ]
    if location:
        lines.append(f"LOCATION:{esc(location)}")
    if alarm_minutes is not None:
        lines.extend([
            "BEGIN:VALARM",
            f"TRIGGER:-PT{alarm_minutes}M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{esc(title)}",
            "END:VALARM",
        ])
    lines.extend(["STATUS:CONFIRMED", "END:VEVENT"])
    return lines

def get_page_text() -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
        )
        page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=90000)
        try:
            page.wait_for_selector("text=VfB Stuttgart", timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(5000)
        text = page.locator("body").inner_text()
        browser.close()
        return clean(text)

def opponent_before(text: str, date_start: int) -> str:
    window = text[max(0, date_start - 500):date_start]
    matches = list(re.finditer(r"VfB Stuttgart\s*[-–]\s*([^|]{2,80}?)(?=\s+(?:Bundesliga|Testspiel|DFB|Champions|Europa|Conference|Freier Verkauf|Mitglieder|Mo\.|Di\.|Mi\.|Do\.|Fr\.|Sa\.|So\.))", window, re.I))
    if matches:
        return clean(matches[-1].group(1))
    # Alternative based on nearby text after the last occurrence of VfB Stuttgart.
    pos = window.lower().rfind("vfb stuttgart")
    if pos >= 0:
        tail = clean(window[pos + len("vfb stuttgart"):]).lstrip("-– ")
        candidate = re.split(r"\s+(?:Bundesliga|Testspiel|DFB-Pokal|Freier Verkauf|Mitgliederverkauf|Mitglieder:)", tail, maxsplit=1, flags=re.I)[0]
        candidate = clean(candidate)
        if 1 < len(candidate) <= 80:
            return candidate
    return "Gegner noch offen"

def parse_events(text: str) -> list[list[str]]:
    events: dict[str, list[str]] = {}

    for match in DATE_RE.finditer(text):
        day = int(match.group("day"))
        month = int(match.group("month"))
        year = int(match.group("year"))
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        start = datetime(year, month, day, hour, minute, tzinfo=TZ)
        opponent = opponent_before(text, match.start())

        if opponent == "Gegner noch offen":
            continue

        title = f"VfB-Spiel: VfB Stuttgart – {opponent}"
        key = make_uid("match", title, start)
        context = text[max(0, match.start()-500):min(len(text), match.end()+250)]
        events[key] = vevent(
            "match",
            title,
            start,
            start + timedelta(hours=2),
            "Termin aus dem offiziellen VfB-Ticketshop. Angaben können sich ändern.\n" + context,
            "MHP Arena Stuttgart",
        )

        # Verkaufsstarts innerhalb des zugehörigen Textblocks suchen.
        block_start = max(0, match.start() - 500)
        block = text[block_start:match.end()]
        for sale in SALE_RE.finditer(block):
            sale_day = int(sale.group("day"))
            sale_month = int(sale.group("month"))
            sale_hour = int(sale.group("hour"))
            sale_minute = int(sale.group("minute") or 0)
            sale_year = year
            sale_start = datetime(sale_year, sale_month, sale_day, sale_hour, sale_minute, tzinfo=TZ)
            if sale_start > start + timedelta(days=20):
                sale_start = sale_start.replace(year=year - 1)

            label = clean(sale.group("label") or "Ticketverkauf")
            sale_title = f"VfB-{label}: {opponent}"
            sale_key = make_uid("sale", sale_title, sale_start)
            events[sale_key] = vevent(
                "sale",
                sale_title,
                sale_start,
                sale_start + timedelta(minutes=30),
                "Verkaufsstart laut offiziellem VfB-Ticketshop. Frühzeitig einloggen.",
                alarm_minutes=30,
            )

    return list(events.values())

def write_calendar(blocks: list[list[str]]) -> None:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Tobias Okos//VfB Ticketkalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:VfB Ticketshop",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
        "X-PUBLISHED-TTL:PT6H",
    ]
    for block in blocks:
        lines.extend(block)
    lines.append("END:VCALENDAR")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\r\n".join(fold(line) for line in lines) + "\r\n", encoding="utf-8")

def main() -> None:
    try:
        text = get_page_text()
        blocks = parse_events(text)
        if not blocks:
            raise RuntimeError("Keine Termine auf der gerenderten Shopseite erkannt.")
        write_calendar(blocks)
        print(f"{len(blocks)} Kalendereinträge geschrieben.")
    except Exception as exc:
        # Wichtig: Bei einem vorübergehenden Shop-/Browserfehler bleibt die letzte
        # funktionierende ICS-Datei bestehen und der Workflow zerstört nichts.
        if OUT.exists() and OUT.stat().st_size > 100:
            print(f"WARNUNG: {exc}")
            print("Vorhandene Kalenderdatei bleibt unverändert bestehen.")
            return
        raise

if __name__ == "__main__":
    main()
