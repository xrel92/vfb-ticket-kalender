#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://tickets.vfb.de/shop?wes=empty_session_103&language=1&shopid=103&nextstate=2&lpShortcutId=5"
OUT = Path("docs/vfb-ticketkalender.ics")
TZ = ZoneInfo("Europe/Berlin")

MATCH_RE = re.compile(r"\b(?:Mo|Di|Mi|Do|Fr|Sa|So)\.\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})\b")
SALE_RE = re.compile(
    r"(?:Mitglieder|Freier Verkauf|Verkauf)?[^.\n]{0,70}?\bab\s+"
    r"(?:Mo|Di|Mi|Do|Fr|Sa|So)\.,?\s*(\d{1,2})\.(\d{1,2})\.?,?\s*(\d{1,2})(?::(\d{2}))?\s*Uhr",
    re.IGNORECASE,
)
TEAM_RE = re.compile(r"VfB Stuttgart\s*[-–]\s*([^\n|]{2,60})", re.IGNORECASE)

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def esc(value: str) -> str:
    return (value.replace("\\", "\\\\").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))

def fold(line: str) -> str:
    # RFC 5545: physical lines should be <= 75 octets.
    out, current = [], ""
    for ch in line:
        trial = current + ch
        if len(trial.encode("utf-8")) > 73:
            out.append(current)
            current = " " + ch
        else:
            current = trial
    out.append(current)
    return "\r\n".join(out)

def uid(kind: str, title: str, dt: datetime) -> str:
    raw = f"{kind}|{title}|{dt.isoformat()}".encode()
    return hashlib.sha256(raw).hexdigest()[:24] + "@vfb-ticketkalender"

def nearest_card(node):
    best = node.parent
    for parent in node.parents:
        text = clean(parent.get_text(" ", strip=True))
        if len(text) > 1200:
            break
        if "VfB Stuttgart" in text and MATCH_RE.search(text):
            best = parent
    return best

def opponent_from(text: str) -> str:
    m = TEAM_RE.search(text)
    if m:
        opponent = clean(m.group(1))
        opponent = re.split(r"(?:Bundesliga|Testspiel|DFB|Tickets|Mitglieder|Freier Verkauf)", opponent)[0].strip(" -–")
        if opponent:
            return opponent
    # Fallback: find a likely line after VfB Stuttgart.
    parts = [clean(x) for x in re.split(r"[\r\n]+", text) if clean(x)]
    for i, part in enumerate(parts):
        if part.lower() == "vfb stuttgart":
            for candidate in parts[i+1:i+5]:
                if candidate not in {"-", "–", "vs"} and "VfB Stuttgart" not in candidate:
                    return candidate[:60]
    return "Gegner noch offen"

def event_block(summary: str, start: datetime, end: datetime, description: str, location: str = "") -> list[str]:
    stamp = datetime.now(TZ).astimezone(ZoneInfo("UTC")).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid(summary.split()[0], summary, start)}",
        f"DTSTAMP:{stamp}",
        f"DTSTART;TZID=Europe/Berlin:{start.strftime('%Y%m%dT%H%M%S')}",
        f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",
        f"SUMMARY:{esc(summary)}",
        f"DESCRIPTION:{esc(description)}",
        f"URL:{SOURCE_URL}",
    ]
    if location:
        lines.append(f"LOCATION:{esc(location)}")
    lines.extend(["STATUS:CONFIRMED", "END:VEVENT"])
    return lines

def parse():
    response = requests.get(
        SOURCE_URL,
        timeout=40,
        headers={"User-Agent": "Mozilla/5.0 (compatible; VfB-Kalender/1.0)"},
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    events = {}
    for text_node in soup.find_all(string=MATCH_RE):
        card = nearest_card(text_node)
        card_text = clean(card.get_text(" ", strip=True))
        match = MATCH_RE.search(card_text)
        if not match:
            continue

        day, month, year, hour, minute = map(int, match.groups())
        match_dt = datetime(year, month, day, hour, minute, tzinfo=TZ)
        opponent = opponent_from(card_text)
        match_title = f"VfB-Spiel: VfB Stuttgart – {opponent}"
        events[uid("match", match_title, match_dt)] = event_block(
            match_title,
            match_dt,
            match_dt + timedelta(hours=2),
            f"Termin aus dem offiziellen VfB-Ticketshop. Angaben können sich ändern.\n{card_text[:700]}",
            "MHP Arena Stuttgart",
        )

        for sale in SALE_RE.finditer(card_text):
            sday, smonth, shour, sminute = sale.groups()
            sale_year = year
            sale_dt = datetime(sale_year, int(smonth), int(sday), int(shour), int(sminute or 0), tzinfo=TZ)
            # Sale dates shown late in the previous calendar year are possible.
            if sale_dt > match_dt + timedelta(days=20):
                sale_dt = sale_dt.replace(year=year - 1)
            sale_title = f"VfB-Ticketverkauf: {opponent}"
            events[uid("sale", sale_title, sale_dt)] = event_block(
                sale_title,
                sale_dt,
                sale_dt + timedelta(minutes=30),
                f"Verkaufsstart laut offiziellem VfB-Ticketshop. Frühzeitig einloggen.\n{card_text[:700]}",
            )

    if not events:
        raise RuntimeError("Keine Termine erkannt. Wahrscheinlich wurde die Shop-Struktur geändert.")

    return [line for block in events.values() for line in block]

def main():
    body = [
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
    body.extend(parse())
    body.append("END:VCALENDAR")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\r\n".join(fold(x) for x in body) + "\r\n", encoding="utf-8")
    print(f"{OUT} aktualisiert.")

if __name__ == "__main__":
    main()
