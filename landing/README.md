# Landingpage

Statische Seite ohne Build-Schritt: `index.html`, `styles.css`, `script.js`, dazu `impressum.html`
und `datenschutz.html`. Lokal ansehen:

```bash
python -m http.server 8000 --directory landing
```

Dann <http://localhost:8000> öffnen.

## Vor der Veröffentlichung anpassen

| Was | Wo |
|---|---|
| Empfängeradresse für Anfragen | `index.html`, Attribut `data-email` am Formular `#contact-form` (die Seite übernimmt sie in alle Links) sowie die Adressen in `impressum.html` und `datenschutz.html` |
| Formular-Dienst (optional) | `data-endpoint` am Formular: URL, die JSON per POST annimmt (z. B. Formspree). Leer = die Anfrage wird als E-Mail im Mailprogramm vorbereitet |
| Impressum, Datenschutz | alle `<mark>`-Platzhalter ersetzen und rechtlich prüfen lassen |
| Ziel des Buttons „Depot-Check anfragen“ | springt zum Kontaktformular (`#kontakt`); bei einer gehosteten App hier verlinken |

## Zahlen im Beispieldepot

Die Werte der Hero-Karte und der Belege stammen aus der App selbst (Offline-Demo, fiktive
Wertpapiere, Standardeinstellungen):

- Klumpenrisiko vorher und nachher: Beispieldepot, `portfolio_optimizer.concentration.analyze`
  mit Wochenrenditen in Euro über 5 Jahre und Standardgrenzen; Umschichtung mit
  `rebalancing.closest_to_limits` (Welt-ETF als Ausgleich, ganze Stücke, Kleinstbetrag 50 €).
- Sharpe-Ratio versprochen und geliefert: `instability.strategy_experiment` mit 10 identischen
  Aktien (7 % Rendite, 20 % Volatilität, Korrelation 0,3), 5 Jahren Historie, 100 Durchläufen,
  Seed 1, risikolosem Zins 2 %, long-only.

Ändert sich die Demo oder die Rechenlogik, die Werte in `index.html` (Startzustand) und in
`script.js` (Objekt `DEMO`) gemeinsam aktualisieren.

## Gestaltung

- Schrift: Plus Jakarta Sans, lokal eingebunden (`fonts/`, SIL Open Font License); es entsteht
  keine Verbindung zu Google Fonts.
- Hell und dunkel über Tokens am Anfang von `styles.css`; die Wahl wird im Browser gespeichert
  (`po-theme`).
- Das Kontaktformular speichert Entwürfe lokal (`po-kontakt-entwurf`), prüft Felder beim
  Verlassen und verwirft Entwürfe nur nach Bestätigung.
