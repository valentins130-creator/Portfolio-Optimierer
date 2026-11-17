# Portfolio-Optimierer

Streamlit-App zur Portfolio-Analyse und -Optimierung. Antworten und UI-Texte auf Deutsch.

- Start: `python -m streamlit run app.py`
- Tests: `pip install -r requirements-dev.txt` und dann `pytest` (läuft auch in der CI)
- Aufbau: Rechenlogik in `portfolio_optimizer/`, Oberfläche in `ui/` (Styles in `ui/common.py`), Seiten in `views/`, Theme in `.streamlit/config.toml`
- Bereiche: Übersicht (`ui/overview_view.py`), Depot (`ui/portfolio_view.py`), Analysen (`ui/analysis_view.py`, Lösungen aus `ui/solutions_view.py`); Abschnitte über `common.choose` (Segment-Schalter, Schlüssel `sec_…`)
- Design: Finanz-Look in zwei Welten (Referenzen Stripe und Mercury): Nachtblau für Kopfzeile, Bühne und Depotwert (`NIGHT_TOKENS`), helle Arbeitsfläche, ein Indigo für Aktionen, Grün/Rot nur für Gewinn/Verlust, Bernstein nur für überschrittene Grenzen; Farben für hell und dunkel in `.streamlit/config.toml` und `ui/common.py` (`TOKENS`), Diagrammfarben (mit dem dataviz-Validator geprüft) in `portfolio_optimizer/charts.py`; Schrift Inter, Karten mit Schlüssel `card_…` reagieren auf die Maus
- Website mit Konten: `ACCOUNTS=on` (im `Dockerfile`), Logik in `portfolio_optimizer/accounts.py`, Oberfläche in `ui/auth.py`, Startseite für Abgemeldete in `ui/landing_view.py`; Speicher über `PORTFOLIO_DIR` oder das Railway-Volume (`RAILWAY_VOLUME_MOUNT_PATH`), Depots je Konto unter `nutzer/<id>`; „Passwort vergessen“ verschickt Einmal-Links über `portfolio_optimizer/mailer.py` (`MAIL_FROM` und `RESEND_API_KEY` oder `SMTP_HOST`, dazu `APP_URL`)
- Bewegung: in der App 300 ms, sanft auslaufend, nur `transform`/`opacity` (Keyframes `po-rise`/`po-grow`/`po-draw` in `ui/common.py`); Skript `MOTION_JS` für gleitende Segment-Markierung, Einblenden beim Scrollen (`data-po-reveal`) und hochzählende Zahlen (`xray.count`); bei „Bewegung reduzieren“ aus

## Design- und UI-Arbeit

Bei jeder Aufgabe, die Aussehen, Layout oder Bedienung der App betrifft
(z. B. „Design überarbeiten“, „schöner machen“, „UI verbessern“, neue Seite
oder Komponente), diese Projekt-Skills aus `.claude/skills/` verwenden:

1. **`awesome-design`**: Vor dem Umgestalten eine passende Referenz wählen
   (für eine Finanz-App z. B. Stripe, Mercury, Wise, Revolut, Coinbase) und
   die Tokens (Farben, Schrift, Abstände, Radien) daraus ableiten. Nur als
   Inspiration, keine Logos oder Markennamen übernehmen.
2. **`image-to-code`**: Wenn ein Bild, Screenshot oder Mockup mitgeschickt wird.
3. **`web-design-guidelines`**: Den geänderten UI-Code nach der Umsetzung
   gegen die Guidelines prüfen und gefundene Probleme beheben.
4. **`playwright-cli`**: Die App starten und das Ergebnis per Screenshot
   prüfen, auf Desktop-Breite (1280 px) und Mobil (375 px). Falls das Tool
   fehlt: `npm install -g @playwright/cli@latest`.

Am Ende kurz berichten, welche Referenz genutzt wurde, was geändert wurde und
was die Prüfung ergeben hat.

## Regeln

- Keine Fantasiewerte in der UI: Zahlen kommen aus `portfolio_optimizer/`.
- Gewinne/Verluste immer mit ausreichendem Kontrast und nicht nur über Farbe unterscheidbar.
- Vor dem Commit `pytest` ausführen.
- Änderungen an der Konten-Datenbank oder am Format der Depot-Dateien nur als neue Migration in
  `portfolio_optimizer/migrations.py` (hinten anhängen, bestehende nie ändern). Merge auf `main`
  deployt automatisch nach Railway, sobald die CI grün ist (README, „Automatisches Deployment“).
