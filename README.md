# Portfolio-Optimierer

Eine Streamlit-App für die Portfolio-Optimierung nach Markowitz: Aktien oder ETFs auswählen, historische Kurse laden, die **Efficient Frontier** berechnen und die Vermögensentwicklung per **Monte-Carlo-Simulation** durchspielen. Ein eigener Bereich zeigt, **warum die Optimierung mit geschätzten Parametern oft enttäuscht** und was dagegen hilft. Unter **Mein Portfolio** lässt sich das eigene Depot anlegen und auf Klumpenrisiken, Absicherungen und Umschichtungen untersuchen.

![Efficient Frontier](docs/frontier.png)

## Funktionen

| Tab | Inhalt |
|---|---|
| **Mein Portfolio** | Eigenes Depot per Suche anlegen (Stückzahl, Kaufkurs), Gewinn/Verlust, Aufteilung nach Sektoren, Ländern und Währungen, Klumpenrisiko, Absicherungsvorschläge, Umschichtung (erscheint mit der Datenquelle „Mein Portfolio“) |
| **Daten** | Wertentwicklung (Start = 100), Rendite, CAGR, Volatilität, Sharpe-Ratio und maximaler Drawdown je Asset, Korrelationsmatrix |
| **Efficient Frontier** | Effizienter Rand, Kapitalmarktlinie, Minimum-Varianz- und Max-Sharpe-Portfolio, frei wählbares Portfolio per Zielvolatilität, Gewichte entlang der Frontier, Risikobeiträge |
| **Monte Carlo** | Parametrische Simulation (korrelierte geometrische Brownsche Bewegung) oder historisches Block-Bootstrap, mit Sparrate, Fächerdiagramm, Verteilung des Endvermögens, Verlust- und Zielwahrscheinlichkeit, Drawdowns |
| **Schätzfehler** | Konfidenzintervalle der erwarteten Renditen, Sensitivität der Gewichte, Simulationsexperiment „versprochen vs. geliefert“, Vergleich mit Shrinkage, Resampling, Minimum-Varianz und 1/N |

In der Seitenleiste lassen sich Schätzer (historischer Mittelwert oder Bayes-Stein, Stichproben-Kovarianz oder Ledoit-Wolf), risikoloser Zins und Gewichtsgrenzen (long-only, Höchstgewichte, Leerverkäufe oder klassischer unbeschränkter Markowitz) einstellen.

## Schnellstart

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Die App öffnet sich unter <http://localhost:8501>. Beenden mit `Strg + C` im Terminal.

### Windows und VS Code

- **Starten:** `python app.py` oder der Start-Button von VS Code starten Streamlit automatisch. `python -m streamlit run app.py` funktioniert auch dann, wenn der Befehl `streamlit` allein nicht gefunden wird.
- **Interpreter wählen:** VS Code muss den Python-Interpreter verwenden, in den die Pakete installiert wurden: `Strg + Umschalt + P` → „Python: Interpreter auswählen“ → `.venv`.
- **Kurzer Pfad:** Windows begrenzt Dateipfade standardmäßig auf 260 Zeichen, und Streamlit enthält tief verschachtelte Dateien. Liegt das Projekt in einem langen Ordnerpfad (etwa tief in OneDrive), scheitert `pip install` in einer `.venv` im Projektordner. Abhilfe: das Projekt an einen kurzen Pfad außerhalb von OneDrive legen, z. B. `C:\Projekte\Portfolio-Optimierer`, oder [lange Pfade in Windows aktivieren](https://learn.microsoft.com/de-de/windows/win32/fileio/maximum-file-path-limitation).
- **`ModuleNotFoundError: No module named '…'`:** Im verwendeten Interpreter fehlen Pakete. Im Terminal von VS Code `python -m pip install -r requirements.txt` ausführen.

### Datenquellen

- **Yahoo Finance:** Ticker wie bei Yahoo, durch Komma getrennt, z. B. `AAPL, MSFT` oder für Xetra `SAP.DE, EUNL.DE`. Verwendet werden dividendenbereinigte Schlusskurse über [yfinance](https://github.com/ranaroussi/yfinance). Das ist eine inoffizielle Schnittstelle, für die die Nutzungsbedingungen von Yahoo gelten. Vorlagen für US-ETFs, Xetra-ETFs, DAX- und US-Aktien sind hinterlegt.
- **CSV-Datei:** Die erste Spalte enthält das Datum, danach folgt eine Spalte je Asset mit Kursen. Komma, Semikolon, Tabulator sowie deutsches Zahlen- und Datumsformat werden erkannt:
  ```
  Datum;Welt-ETF;Anleihen-ETF
  02.01.2024;101,20;55,10
  03.01.2024;102,05;54,80
  ```
- **Mein Portfolio:** das eigene Depot, siehe unten. Kurse werden in Euro umgerechnet.
- **Demo-Daten:** Simulierte Kurse sechs fiktiver Assetklassen. Damit lässt sich die App ohne Internetverbindung ausprobieren.

Assets mit unterschiedlichen Handelskalendern werden über kurze Lücken (bis zu fünf Tage) fortgeschrieben, anschließend wird auf den gemeinsamen Zeitraum zugeschnitten. Bei Yahoo Finance, CSV und Demo-Daten bleiben Kurse in ihrer Handelswährung; nur „Mein Portfolio“ rechnet in Euro um.

## Mein Portfolio

Datenquelle „Mein Portfolio“ in der Seitenleiste wählen. Als Marktdaten stehen Yahoo Finance (live) oder eine **Offline-Demo** mit fiktiven Wertpapieren und einem Beispieldepot zur Verfügung (unter **Neu** → „Beispieldepot laden“).

- **Anlegen:** Wertpapiere per Name, Ticker oder ISIN suchen und mit Stückzahl und Kaufkurs je Stück (in Euro, wie im Depotauszug) hinzufügen. Stückzahl und Kaufkurs lassen sich in der Tabelle ändern. Mehrfache Käufe desselben Werts werden zusammengefasst, der Einstandskurs gemittelt.
- **Speichern:** Jede Änderung wird als JSON im Ordner `portfolios/` gespeichert (Demo-Portfolios in `portfolios/demo/`). Der Ordner ist von Git ausgeschlossen, weil er private Daten enthält. Mit der Umgebungsvariable `PORTFOLIO_DIR` lässt sich ein anderer Ort wählen. Export und Import als JSON oder CSV; eine CSV braucht die Spalten `Symbol` und `Stück`, optional `Kaufkurs`:
  ```
  Symbol;Stück;Kaufkurs
  SAP.DE;10;182,40
  EUNL.DE;25,5;88,10
  ```
- **Aufteilung:** nach Sektoren, Ländern und Handelswährungen. ETFs werden über ihre Sektorgewichte aufgeschlüsselt (Durchschau), soweit Yahoo diese liefert. Für Länder liefert Yahoo bei Fonds keine Aufteilung; sie erscheinen als „Mehrere Länder (Fonds)“.
- **Klumpenrisiko:** Konzentration nach Einzelaktie, Sektor, Land, Fremdwährung und Gruppen stark korrelierter Einzelwerte (hierarchisches Clustering). Zu jeder Gruppe gehört neben dem Gewicht der **Risikoanteil**, also der Teil der Depotschwankung, den sie verursacht. Die Grenzen (Standard: 10 % je Aktie, 30 % je Sektor, 60 % je Land, 50 % je Fremdwährung, 40 % je Cluster) sind einstellbar.
- **Absicherung:**
  - *Markt-Hedge:* Beta des Depots gegenüber mehreren Indizes. Das Instrument mit dem höchsten R² ist der beste Hedge; Short-Betrag = Beta × Depotwert × Absicherungsquote.
  - *Beimischung:* Wirkung von Anleihen, Geldmarkt, Gold, Nebenwerten usw. auf Volatilität, maximalen Rückgang und Rendite.
  - *Klumpen:* Für jede Konzentration über der Grenze der Verkaufsbetrag bis zur Grenze oder die Absicherung genau dieses Überhangs über das am besten passende Sektor- oder Index-Instrument bzw. ein Devisentermingeschäft.
- **Umschichtung:** Käufe und Verkäufe, um die Klumpenrisiko-Grenzen mit möglichst wenig Umschichtung einzuhalten (quadratisches Programm, optional mit einem Welt-ETF als Ausgleich) oder um effizient bei gleichem Risiko, zum Minimum-Varianz- oder zum Max-Sharpe-Portfolio zu kommen. Angezeigt werden Stückzahlen, Beträge, Restliquidität und die durch Verkäufe realisierten Gewinne.
- **Integration:** Das eigene Depot erscheint im Efficient-Frontier-Diagramm (mit Abstand zum effizienten Rand) und lässt sich im Tab Monte Carlo simulieren.

Alle Risiko- und Hedge-Kennzahlen beruhen auf historischen **Wochenrenditen in Euro**. Wochendaten mildern Verzerrungen durch unterschiedliche Handelszeiten der Börsen.

## Methodik

**Schätzung.** Grundlage sind einfache Tagesrenditen. Erwartete Renditen und Kovarianzen werden mit 252 Handelstagen annualisiert.

- *Bayes-Stein (Jorion 1986):* zieht die Mittelwerte in Richtung der Rendite des Minimum-Varianz-Portfolios.
- *Ledoit-Wolf (2004):* Shrinkage der Kovarianzmatrix zum Modell konstanter Korrelation. Die Varianzen bleiben dabei erhalten.

**Optimierung.** Für jede Zielrendite $r^*$ wird

$$\min_w \; w^\top \Sigma w \quad \text{u. d. N.} \quad w^\top\mu = r^*,\quad \mathbf 1^\top w = 1,\quad l \le w_i \le u$$

gelöst, mit Gewichtsgrenzen numerisch (SLSQP) und ohne Grenzen in geschlossener Form. Das Max-Sharpe-Portfolio wird über das konvexe Ersatzproblem $\min_y y^\top\Sigma y$ unter $(\mu - r_f)^\top y = 1$ mit $w = y/\mathbf 1^\top y$ bestimmt. Weil dieses Problem konvex ist, gibt es keine lokalen Nebenoptima.

**Monte Carlo.** Die parametrische Variante simuliert monatliche Log-Renditen $\mathcal N\big((\mu - \tfrac12\operatorname{diag}\Sigma)\,\Delta t,\; \Sigma\,\Delta t\big)$. Das Bootstrap zieht zusammenhängende Blöcke von 21 historischen Handelstagen, wodurch Fat Tails und kurzfristige Abhängigkeiten erhalten bleiben. Das Portfolio wird monatlich auf die Zielgewichte zurückgesetzt; die Sparrate wird am Monatsende eingezahlt.

**Schätzfehler-Experiment.** Ein bekanntes „wahres“ Modell (die aktuellen Schätzungen oder N identische Assets) erzeugt viele alternative Kurshistorien. Auf jeder Historie wird geschätzt und optimiert, das Ergebnis wird anschließend mit den wahren Parametern bewertet. Verglichen werden:

- Max-Sharpe mit Stichprobenschätzern,
- Max-Sharpe mit nur geschätztem μ bzw. nur geschätztem Σ (Chopra & Ziemba 1993),
- Max-Sharpe mit Shrinkage (Bayes-Stein und Ledoit-Wolf),
- Resampled Efficiency nach Michaud (Mittel der Max-Sharpe-Gewichte über Parameterziehungen),
- Minimum-Varianz und 1/N.

Sieht eine Schätzung kein Portfolio über dem risikolosen Zins, bleibt der Anleger risikolos investiert (Sharpe-Ratio 0).

![Schätzfehler-Experiment mit identischen Assets](docs/schaetzfehler.png)

Im Szenario mit identischen Assets ist das wahre Optimum 1/N. Trotzdem verspricht der Optimierer im Mittel eine Sharpe-Ratio von 0,67 und liefert nur 0,31 – weniger als die schlichte Gleichgewichtung mit 0,39.

## Projektstruktur

```
app.py                         Streamlit-Oberfläche
portfolio_tab.py               Tab „Mein Portfolio“
portfolio_optimizer/
  data.py                      Yahoo Finance, CSV-Import, Datenbereinigung, Demo-Daten
  estimators.py                Mittelwert- und Kovarianzschätzer (Stichprobe, Bayes-Stein, Ledoit-Wolf)
  optimization.py              Minimum-Varianz, Max-Sharpe, Efficient Frontier, Zielrendite/-volatilität
  monte_carlo.py               GBM-Simulation und Block-Bootstrap
  instability.py               Schätzunsicherheit, Sensitivität, Simulationsexperimente
  market.py                    Suche, Stammdaten, Kurse, Wechselkurse (Yahoo und Offline-Demo)
  portfolio.py                 Positionen, Speichern/Laden, Bewertung, Aufteilung
  concentration.py             Klumpenrisiko: Konzentrationen, Cluster, Risikoanteile
  hedging.py                   Markt-Hedge, Beimischungen, Absicherung von Klumpen
  rebalancing.py               Zielgewichte unter Grenzen, Käufe und Verkäufe
  charts.py                    Plotly-Diagramme (helles und dunkles Theme)
  formatting.py                Deutsche Zahlenformate
tests/                         pytest-Suite, inkl. Rauchtests der Oberfläche
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Die Tests prüfen unter anderem die Optimierer gegen geschlossene Lösungen, den Ledoit-Wolf-Schätzer gegen eine direkte Umsetzung der Formeln aus dem Paper, die Monte-Carlo-Simulation gegen analytische Erwartungswerte und alle Tabs der Oberfläche mit `streamlit.testing`. Netzwerkzugriffe werden in den Tests durch Attrappen ersetzt.

## Grenzen

- Keine Anlageberatung. Die App ist ein Lern- und Analysewerkzeug.
- Transaktionskosten und Steuern werden nicht berücksichtigt; Wechselkurse nur unter „Mein Portfolio“.
- Absicherungen und Umschichtungen beruhen auf historischen Daten. Hedges sichern mit dem Risiko auch die erwartete Rendite ab und verursachen Kosten.
- Die parametrische Simulation unterstellt normalverteilte Log-Renditen und behandelt die geschätzten Parameter als bekannt. Wie problematisch das ist, zeigt der Tab „Schätzfehler“.

## Literatur

- Markowitz, H. (1952): Portfolio Selection. *Journal of Finance* 7(1).
- Michaud, R. O. (1989): The Markowitz Optimization Enigma: Is 'Optimized' Optimal? *Financial Analysts Journal* 45(1).
- Best, M. J. & Grauer, R. R. (1991): On the Sensitivity of Mean-Variance-Efficient Portfolios to Changes in Asset Means. *Review of Financial Studies* 4(2).
- Broadie, M. (1993): Computing Efficient Frontiers Using Estimated Parameters. *Annals of Operations Research* 45.
- Chopra, V. K. & Ziemba, W. T. (1993): The Effect of Errors in Means, Variances, and Covariances on Optimal Portfolio Choice. *Journal of Portfolio Management* 19(2).
- Jorion, P. (1986): Bayes-Stein Estimation for Portfolio Analysis. *Journal of Financial and Quantitative Analysis* 21(3).
- Ledoit, O. & Wolf, M. (2004): Honey, I Shrunk the Sample Covariance Matrix. *Journal of Portfolio Management* 30(4).
- Jagannathan, R. & Ma, T. (2003): Risk Reduction in Large Portfolios: Why Imposing the Wrong Constraints Helps. *Journal of Finance* 58(4).
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009): Optimal Versus Naive Diversification: How Inefficient Is the 1/N Portfolio Strategy? *Review of Financial Studies* 22(5).
