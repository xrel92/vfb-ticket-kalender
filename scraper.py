#!/usr/bin/env python3
"""
VfB Stuttgart Ticket-Vorverkauf -> ICS-Kalender

Liest die offiziellen VfB-Ticketseiten (Heim- und Auswärtsspiele) aus und
baut daraus eine .ics-Kalenderdatei mit allen bekannten Vorverkaufsterminen.

Wird von GitHub Actions regelmäßig ausgeführt (siehe .github/workflows/update.yml),
das Ergebnis landet in docs/vfb-vorverkauf.ics und wird per GitHub Pages
bereitgestellt -> das ist die URL, die man in Apple Kalender abonniert.

Hinweis: Dies ist ein HTML-Scraper. Wenn der VfB seine Seite umbaut, kann das
Skript brechen und muss angepasst werden (siehe README.md).
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from uuid import uuid5, NAMESPACE_URL

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Bitte 'beautifulsoup4' installieren: pip install beautifulsoup4", file=sys.stderr)
    raise

PAGES = {
    "Heimspiel": "https://shop.vfb.de/de/vorkerkauf-uebersicht",
    "Auswärtsspiel": "https://shop.vfb.de/de/europa-legaue-termine",
}

OUTPUT_PATH = "docs/vfb-vorverkauf.ics"
CAL_NAME = "VfB Ticket-Vorverkauf"

MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

# z.B. "Mittwoch, 1. April, 9 Uhr" oder "26. April, 15:30 Uhr" oder
# "Mittwoch, 1. April 2026, 9:00 Uhr"
DATE_RE = re.compile(
    r"(?:\w+,\s*)?(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\.?\s*(\d{4})?,?\s*(\d{1,2})\s*:?\s*(\d{2})?\s*Uhr",
    re.IGNORECASE,
)


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; VfBTicketCalendarBot/1.0)"})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def guess_year(month: int, day: int, ref: datetime) -> int:
    """Rät das Jahr, wenn die VfB-Seite keins angibt (Saison läuft über Jahreswechsel)."""
    candidate = datetime(ref.year, month, day)
    # Wenn das Datum schon >60 Tage in der Vergangenheit läge, ist es wohl nächstes Jahr
    if candidate < ref - timedelta(days=60):
        return ref.year + 1
    return ref.year


def parse_datetime(text: str, ref: datetime):
    m = DATE_RE.search(text)
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2).lower().rstrip(".")
    year = int(m.group(3)) if m.group(3) else None
    hour = int(m.group(4))
    minute = int(m.group(5)) if m.group(5) else 0

    month = MONTHS.get(month_name)
    if not month:
        return None
    if year is None:
        year = guess_year(month, day, ref)

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError:
        return None


SALE_KEYWORDS = ("Mitglieder", "Dauerkarte", "Freier Verkauf", "freier Verkauf",
                 "Warteliste", "Fanclub", "Ticketbörse", "Bewerbung")

COMPETITIONS = ("Bundesliga", "DFB-Pokal", "Champions League", "Europa League",
                "Conference League", "Supercup", "DFL-Supercup", "Testspiel")


def looks_like_match_line(text: str) -> bool:
    if not text.endswith(")"):
        return False
    if "Uhr" not in text:
        return False
    if " - " not in text:
        return False
    return any(text.startswith(c) for c in COMPETITIONS) or "VfB" in text


def looks_like_sale_info(text: str) -> bool:
    if "Uhr" not in text:
        return False
    return any(text.startswith(k) or (k + ":") in text for k in SALE_KEYWORDS)


def extract_events(html: str, category: str, ref: datetime):
    soup = BeautifulSoup(html, "html.parser")
    content = soup.find("main") or soup

    # Wir arbeiten auf reinem Text statt auf bestimmten HTML-Tags (b/strong/em/i),
    # weil die VfB-Seite Fett/Kursiv teils über CSS-Klassen statt semantische
    # Tags umsetzt. Jede sichtbare Zeile wird einzeln betrachtet.
    raw_text = content.get_text("\n")
    lines = [ln.strip() for ln in raw_text.split("\n")]
    lines = [ln for ln in lines if ln]

    events = []
    current_match = None

    for line in lines:
        if looks_like_match_line(line):
            current_match = line
            continue

        if looks_like_sale_info(line) and current_match:
            dt = parse_datetime(line, ref)
            if not dt:
                continue
            sale_type = line.split(":")[0].strip()
            events.append({
                "match": current_match,
                "sale_type": sale_type,
                "detail": line,
                "start": dt,
                "category": category,
            })

    return events


def escape_ics(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))


def build_ics(events) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//vfb-ticket-kalender//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        "X-WR-TIMEZONE:Europe/Berlin",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    ]

    for ev in events:
        uid_src = f"{ev['match']}|{ev['sale_type']}|{ev['start'].isoformat()}"
        uid = str(uuid5(NAMESPACE_URL, uid_src))
        dtstart = ev["start"].strftime("%Y%m%dT%H%M%S")
        summary = f"VVK-Start: {ev['match']} ({ev['sale_type']})"
        desc = f"{ev['category']} – {ev['detail']}"

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@vfb-ticket-kalender",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Berlin:{dtstart}",
            f"SUMMARY:{escape_ics(summary)}",
            f"DESCRIPTION:{escape_ics(desc)}",
            "BEGIN:VALARM",
            "TRIGGER:-PT30M",
            "ACTION:DISPLAY",
            "DESCRIPTION:Vorverkauf startet in 30 Minuten",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def main():
    ref = datetime.now()
    all_events = []
    for category, url in PAGES.items():
        try:
            html = fetch(url)
        except Exception as exc:
            print(f"Warnung: Konnte {url} nicht laden: {exc}", file=sys.stderr)
            continue
        all_events.extend(extract_events(html, category, ref))

    seen = set()
    deduped = []
    for ev in all_events:
        key = (ev["match"], ev["sale_type"], ev["start"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)
    all_events = deduped

    all_events.sort(key=lambda e: e["start"])

    ics = build_ics(all_events)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(ics)

    print(f"{len(all_events)} Vorverkaufstermine geschrieben nach {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
