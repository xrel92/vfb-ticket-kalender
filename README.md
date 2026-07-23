# VfB-Ticketkalender für Apple Kalender

Dieses kleine Projekt liest regelmäßig den offiziellen VfB-Ticketshop aus und erzeugt eine abonnierbare ICS-Datei.

## Einmalige Einrichtung bei GitHub

1. Auf GitHub ein neues **öffentliches Repository** anlegen, zum Beispiel `vfb-ticketkalender`.
2. Alle Dateien aus diesem Ordner hochladen und in den Branch `main` übernehmen.
3. Im Repository **Settings → Pages** öffnen.
4. Unter **Build and deployment** als Source **Deploy from a branch** wählen.
5. Branch **main** und Ordner **/docs** auswählen, dann speichern.
6. Unter **Actions** den Workflow „VfB Ticketkalender aktualisieren“ einmal manuell starten.
7. Danach lautet die Kalenderadresse normalerweise:

   `https://DEIN-GITHUB-NAME.github.io/vfb-ticketkalender/vfb-ticketkalender.ics`

## In Apple Kalender abonnieren

### iPhone/iPad
**Einstellungen → Apps → Kalender → Kalenderaccounts → Account hinzufügen → Andere → Kalenderabo hinzufügen**

Dort die GitHub-Pages-Adresse einfügen.

### Mac
**Kalender → Ablage → Neues Kalenderabonnement**

## Aktualisierung

GitHub prüft die Shopseite automatisch alle drei Stunden. Apple entscheidet selbst, wann ein abonnierter Kalender neu geladen wird; Änderungen erscheinen daher eventuell etwas verzögert.

## Hinweise

- Enthalten sind erkannte Spieltermine und ausdrücklich genannte Verkaufsstarts.
- Der Kalender kauft keine Tickets und meldet sich nicht in deinem VfB-Konto an.
- Termine, die nur nach Anmeldung sichtbar sind, können nicht ausgelesen werden.
- Ändert der Ticketshop seine technische Struktur, muss der Parser eventuell angepasst werden.
