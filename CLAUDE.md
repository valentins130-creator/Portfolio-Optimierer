# Portfolio-Optimierer

Streamlit-App zur Portfolio-Analyse und -Optimierung. Antworten und UI-Texte auf Deutsch.

- Start: `python -m streamlit run app.py`
- Tests: `pip install -r requirements-dev.txt` und dann `pytest` (läuft auch in der CI)
- Aufbau: Rechenlogik in `portfolio_optimizer/`, Oberfläche in `ui/` (Styles in `ui/common.py`), Seiten in `views/`, Theme in `.streamlit/config.toml`
- Startseite in `ui/start_view.py` (Seite `views/start.py`); Farben für hell und dunkel in `.streamlit/config.toml` (`[theme.light]`, `[theme.dark]`) und `ui/common.py` (`TOKENS`)

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
