# Portfolio-Optimierer

Eine Streamlit-App für das eigene Depot: Käufe und Verkäufe mit Datum erfassen, die Wertentwicklung verfolgen, Klumpenrisiken erkennen, die **Efficient Frontier** nach Markowitz berechnen, die Vermögensentwicklung per **Monte-Carlo-Simulation** durchspielen und sehen, **warum die Optimierung mit geschätzten Parametern oft enttäuscht**. Zu jedem Befund schlägt die App Lösungen vor: Umschichtungen und Absicherungen.

![Ebene Portfolio mit dem Beispieldepot der Offline-Demo](docs/portfolio.png)

## Aufbau

Drei Bereiche, oben in der Leiste: **Übersicht**, **Depot** und **Analysen**. Innerhalb eines Bereichs wählt ein Segment-Schalter den Abschnitt; gezeigt und gerechnet wird nur, was gerade gewählt ist. Gewählte Abschnitte und Eingaben bleiben beim Wechsel des Bereichs erhalten. Die passenden Lösungen stehen direkt bei der Analyse.

| Bereich | Inhalt |
|---|---|
| **Übersicht** | Depotwert · Schnellzugriff · Klumpenrisiko jetzt und nach Umschichtung · Hinweise, was zu tun ist. Ohne Depot: drei Einstiege (erfassen, importieren, Beispiel) und eine Vorschau |
| **Depot** | Transaktion erfassen · Positionen · Transaktionen · Entwicklung · Kennzahlen · Aufteilung nach Sektoren und Währungen |
| **Analysen** | Klumpenrisiko mit **Was-wäre-wenn-Regler**, Umschichtung und Absicherung · Effizienz (Markowitz) mit Umschichtung zum effizienten Portfolio · Zukunft (Monte Carlo) · Schätzfehler |

Die Kopfzeile darüber gilt für alle Bereiche: Depot auswählen, **Verwalten** (Neu, Import/Export, Löschen, Papierkorb), **Einstellungen** und mit Konten **Konto** (Abmelden, Konto löschen). In den Einstellungen werden Marktdaten (Yahoo Finance oder Offline-Demo), die Länge der Historie für die Analysen, die Schätzer (historischer Mittelwert oder Bayes-Stein, Stichproben-Kovarianz oder Ledoit-Wolf), der risikolose Zins und die Gewichtsgrenzen (long-only, Höchstgewichte, Leerverkäufe oder klassischer unbeschränkter Markowitz) eingestellt.

**Was wäre, wenn.** Unter Analysen → Klumpenrisiko verschiebt ein Regler das Gewicht einer Position; die übrigen teilen sich den Rest im bisherigen Verhältnis. Grenzen, Risikoanteile, effektive Positionen und die Schwankung rechnen sofort neu, umschaltbar zwischen „Jetzt“ und „Was wäre, wenn“.

**Design.** Finanz-Look in zwei Welten: Nachtblau rahmt und hebt hervor (Kopfzeile, Bühne der Startseite, Depotwert), helles kühles Grau mit weißen Karten trägt die Arbeit. Ein Indigo für alles Anklickbare, Grün und Rot nur für Gewinne und Verluste, Bernstein nur für überschrittene Grenzen, ein warmes Band auf der Startseite. Bewegung mit Zweck: Inhalte steigen beim Erscheinen auf, Balken wachsen, die Kurve zeichnet sich, die Markierung der Abschnittswahl gleitet, Kennzahlen zählen einmal hoch; bei „Bewegung reduzieren“ ist alles aus. Karten heben sich an, wenn die Maus darüberfährt. Schrift Inter (von der App selbst ausgeliefert, ohne Google-Server). Die App folgt der hellen oder dunklen Systemeinstellung; umschalten lässt sich oben rechts im Menü (⋮ → System, Light, Dark).

**Konten.** Mit `ACCOUNTS=on` (im `Dockerfile` gesetzt, also auf Railway an) ist die App eine Website mit Konten: Abgemeldete sehen die Startseite mit **Anmelden** und **Konto erstellen** (E-Mail und Passwort, jeder darf sich registrieren), jedes Konto hat eigene Depots. Passwörter liegen nur als scrypt-Hash vor; nach 5 Fehlversuchen ist eine E-Mail 15 Minuten gesperrt. **Angemeldet bleiben** setzt ein Cookie mit einem zufälligen Schlüssel für 30 Tage; Abmelden oder Konto löschen macht ihn sofort ungültig. **Passwort vergessen?** schickt einen Einmal-Link per E-Mail, der eine Stunde gilt; danach enden gemerkte Anmeldungen auf anderen Geräten (Einrichtung siehe [Online betreiben](#online-betreiben-railway)). Lokal ohne die Variable startet die App wie gewohnt ohne Anmeldung.

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

## Online betreiben (Railway)

Die App läuft als Website mit Konten, zum Beispiel auf [Railway](https://railway.com). Das Repository enthält dafür ein `Dockerfile`; Railway erkennt es und baut die App daraus. Den Port gibt Railway in `$PORT` vor, das `Dockerfile` reicht ihn an Streamlit weiter und schaltet die Konten ein (`ACCOUNTS=on`).

1. **Projekt anlegen:** In Railway **New Project → Deploy from GitHub repo** und dieses Repository wählen (Branch `main`).
2. **Speicher anhängen:** Ein **Volume** anlegen und an den Service hängen, Mount Path zum Beispiel `/data`. Dort liegen die Konten (`konten.sqlite`), die Depots je Konto (`nutzer/…`) und die gespeicherten Kurse; Railway setzt dafür `RAILWAY_VOLUME_MOUNT_PATH`. **Ohne Volume sind Konten und Depots nach jedem Neustart weg.**
3. **Adresse:** Unter **Settings → Networking** mit **Generate Domain** eine öffentliche Adresse erzeugen.
4. **Deploy-Einstellungen:** Unter **Settings → Deploy** als Healthcheck Path `/_stcore/health` eintragen und unter **Settings → Source** „Wait for CI“ einschalten (siehe [Automatisches Deployment](#automatisches-deployment)).
5. **Region:** Service und Volume in der EU betreiben (**Settings → Deploy → Regions**: EU West, Amsterdam). Die Datenschutzerklärung geht davon aus.
6. **Impressum und Datenschutz:** Fußzeile der Startseite in `ui/landing_view.py`; Name, Anschrift und E-Mail stehen oben in `OWNER`, `ADDRESS` und `EMAIL`. Die Datenschutzerklärung nennt einen Vertrag zur Auftragsverarbeitung mit Railway: das [Data Processing Addendum](https://railway.com/legal/dpa) unterschreiben. Texte vor dem Start rechtlich prüfen lassen.
7. **E-Mails für „Passwort vergessen“:** Unter **Variables** den Absender `MAIL_FROM` setzen (z. B. `Portfolio-Optimierer <noreply@deine-domain.de>`) und entweder `RESEND_API_KEY` (Versand über [Resend](https://resend.com), läuft über HTTPS) oder `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` für einen SMTP-Server. Empfohlen ist außerdem `APP_URL` mit der öffentlichen Adresse (z. B. `https://dein-name.up.railway.app`), damit der Link in der E-Mail immer dorthin zeigt. Ohne Versand meldet die App, dass er nicht eingerichtet ist, und schreibt den Link ins Deploy-Log, das nur du siehst. Railway sperrt ausgehendes SMTP je nach Tarif; dann den Weg über Resend nehmen. Die Datenschutzerklärung nennt den Dienst von selbst (Resend oder den SMTP-Server); bei Resend dessen Vertrag zur Auftragsverarbeitung abschließen.

Die SQLite-Datei verträgt genau eine laufende Instanz; mehrere Replikate bräuchten eine Datenbank wie PostgreSQL. Yahoo begrenzt Abfragen und reagiert auf Cloud-Server eher mit „Too Many Requests“; die App rechnet dann mit den gespeicherten Kursen weiter (siehe [Fehlende Kurse](#fehlende-kurse)).

Lokal lässt sich der Container so testen:

```bash
docker build -t portfolio-optimierer .
docker run -p 8501:8501 -v "$PWD/daten:/data" -e PORTFOLIO_DIR=/data portfolio-optimierer
```

### Automatisches Deployment

Jeder Merge (oder Push) auf `main` geht automatisch live, aber nur, wenn alle Prüfungen grün sind:

1. **CI** (`.github/workflows/ci.yml`, auch bei jedem Pull Request):
   - **Tests:** die ganze pytest-Suite.
   - **Container, Migration und Smoke-Test:** baut das Image aus dem `Dockerfile` wie Railway. Dann legt es mit dem *vorherigen* Stand (Basis des Pull Requests bzw. letzter Commit auf `main`) ein Konto an, startet den neuen Stand auf denselben Daten und meldet sich mit diesem Konto an. Damit ist die Migration gegen echte Altdaten geprüft. Danach ein Neustart wie bei einem weiteren Deployment und noch einmal anmelden: Die Daten bleiben, und die Migration läuft ein zweites Mal ohne Schaden.
2. **Railway** wartet mit dem Deploy, bis die CI fertig ist („Wait for CI“), und überspringt das Deployment, wenn sie rot ist.
3. **Start im Container:** zuerst `python -m portfolio_optimizer.migrations`, dann Streamlit. Ein Pre-Deploy-Befehl von Railway ginge nicht, weil dort das Volume nicht eingehängt ist. Schlägt die Migration fehl, startet die App nicht, der Healthcheck (`/_stcore/health`) schlägt fehl und Railway meldet das Deployment als fehlgeschlagen. Mit Volume hat jeder Deploy eine kurze Ausfallzeit, weil Railway nie zwei Deployments gleichzeitig auf dasselbe Volume lässt.
4. **Live-Check** (`.github/workflows/live-check.yml`): Railway meldet jedes Deployment an GitHub. Ist es erfolgreich, prüft ein Smoke-Test die Live-Seite (Health-Check, Startseite ohne Fehler, Impressum, Datenschutz). Er liest nur und legt kein Konto an. Schlägt das Deployment fehl, wird der Workflow rot. Die Adresse lässt sich über die Repository-Variable `APP_URL` ändern.

**Migrationen** stehen in `portfolio_optimizer/migrations.py`. Den erreichten Stand merkt sich die Konten-Datenbank (`PRAGMA user_version`). Vor jeder Migration wird `konten.sqlite` nach `backups/` im Volume gesichert, die letzten 10 Sicherungen bleiben liegen. Alle ausstehenden Schritte laufen in einer Transaktion, bei einem Fehler bleibt der alte Stand. Eine neue Migration ist eine Funktion `_v<n>(db, root)`, die hinten an `MIGRATIONS` angehängt wird. Sie bekommt auch den Speicherordner und kann so Depot-Dateien umbauen. Bestehende Migrationen nie ändern, sie sind auf dem Server schon gelaufen. Ist die Datenbank neuer als der Code (Rollback auf ein älteres Deployment), bleibt sie unverändert.

**Empfohlen in GitHub:** Unter **Settings → Branches** für `main` eine Regel anlegen, die Pull Requests und die Checks „Tests“ und „Container, Migration und Smoke-Test“ verlangt. Dann landet nichts Ungeprüftes auf `main`.

Den Smoke-Test gibt es auch lokal (braucht `pip install playwright` und `python -m playwright install chromium`):

```bash
python scripts/smoke_test.py https://portfolio-optimierer-production.up.railway.app
```

## Portfolio

**Marktdaten.** Unter **Einstellungen** stehen Yahoo Finance oder eine **Offline-Demo** mit fiktiven Wertpapieren zur Wahl. In der Demo lädt **Verwalten → Neu → Beispieldepot laden** ein Depot mit Käufen über drei Jahre, einem Teilverkauf und einem Aktiensplit 4:1. Yahoo-Daten kommen über [yfinance](https://github.com/ranaroussi/yfinance), eine inoffizielle Schnittstelle, für die die Nutzungsbedingungen von Yahoo gelten.

**Kurse.** Während der Handelszeit bewertet die App mit dem letzten Minutenkurs von Yahoo (in der Regel etwa 15 Minuten verzögert), sonst mit dem letzten Schlusskurs. Die Spalte „Stand“ der Positionstabelle zeigt, welcher Kurs gilt, etwa „live 14:32“ oder „Schluss 06.11.2026“. Bewertung, Wertentwicklung und der Kursvorschlag beim Erfassen beruhen auf den tatsächlichen Schlusskursen; Renditen und Risiken in den Analysen auf dividendenbereinigten Kursen. Alle Werte werden zum jeweiligen Tageskurs in Euro umgerechnet, auch Kurse in Pence (GBp). Warum Kurse zeitweise fehlen können und was die App dagegen tut, steht unter [Fehlende Kurse](#fehlende-kurse).

**Transaktionen.** Ein Wertpapier per Name, Ticker oder ISIN suchen oder aus dem Depot wählen, dann Kauf oder Verkauf mit Datum, Stückzahl und Kurs je Stück in Euro erfassen. Sobald Wertpapier oder Datum feststehen, trägt die App den Schlusskurs dieses Tages ein; gibt es keinen, bleibt das Feld leer. Für genaue Gewinne den Ausführungskurs aus der Abrechnung eintragen. Ein Verkauf kann den Bestand an seinem Datum nicht übersteigen. In der Tabelle **Transaktionen** lassen sich Datum, Typ, Stück und Kurs direkt ändern. Gelöscht wird in zwei Schritten: Zeilen markieren, dann „markierte löschen“; danach lässt sich das Löschen rückgängig machen. Einstandskurse und realisierte Gewinne folgen dem FIFO-Prinzip: Die zuerst gekauften Stücke gelten als zuerst verkauft.

**Sparpläne.** Unter **Transaktion erfassen** mit Typ **Sparplan** legst du regelmäßige Käufe an:
- **Sparrate** in Euro.
- **Rhythmus:** monatlich, alle 2 Monate, vierteljährlich, halbjährlich oder jährlich.
- **Erste Ausführung:** danach immer am selben Tag im Monat. Gibt es den Tag nicht, etwa den 31., dann am Monatsletzten.
- **Ende:** **Bis heute** heißt, der Plan läuft weiter, und neue Termine kommen beim Öffnen des Depots automatisch dazu. Mit **Bis Datum** endet der Plan an einem festen Tag.

Jede Ausführung ist ein normaler Kauf für die Sparrate zum Schlusskurs am Termin bzw. am nächsten Handelstag, in der damaligen Stückelung, mit Bruchstücken. Hat ein Termin noch keinen Schlusskurs (heute vor Börsenschluss), folgt die Ausführung beim nächsten Laden. Die Käufe stehen in der Tabelle **Transaktionen** mit dem Vermerk des Sparplans und lassen sich dort einzeln korrigieren, etwa auf den Kurs aus der Abrechnung. Einzeln gelöschte Ausführungen legt die App nicht neu an. Über der Tabelle stehen die Sparpläne mit Stand und investierter Summe:
- **Beenden** setzt ein Enddatum und löscht spätere Ausführungen.
- **Löschen** entfernt den Plan. Seine Käufe bleiben dabei als einzelne Transaktionen stehen oder werden mitgelöscht.

Beides lässt sich rückgängig machen.

**Kapitalmaßnahmen.** Aktiensplits und Reverse-Splits berücksichtigt die App automatisch: Yahoo liefert sie mit den Kursen, und Transaktionen vor einem Split zählen mit entsprechend mehr (bzw. weniger) Stücken zum angepassten Kurs. Erfasst werden Käufe wie in der Abrechnung, also in der damaligen Stückelung; auch der vorgeschlagene Schlusskurs ist der damalige. Unter den Positionen steht, welcher Split berücksichtigt wurde. Andere Kapitalmaßnahmen erkennt die App nicht automatisch; sie lassen sich als Transaktionen abbilden: eine Abspaltung (Spin-off) als Kauf der neuen Aktien mit dem Kurs, den die Abrechnung der Depotbank ausweist, eine Fusion oder ein Umtausch als Verkauf der alten und Kauf der neuen Aktie, eine Kapitalerhöhung als Kauf der neuen Aktien zum Bezugspreis.

**Wertentwicklung.**

- *Depotwert und Einzahlungen:* täglicher Depotwert gegenüber dem netto eingezahlten Kapital (Käufe minus Verkaufserlöse).
- *Persönliche Rendite p. a.:* interner Zinsfuß (XIRR) aller Ein- und Auszahlungen und des heutigen Depotwerts. Er berücksichtigt, wann wie viel investiert wurde. Unter einem Jahr Haltedauer zeigen persönliche und zeitgewichtete Rendite die tatsächliche Rendite „seit“ dem ersten Kauf statt einer Hochrechnung aufs Jahr, die kurze Schwankungen vervielfachen würde.
- *Zeitgewichtete Rendite p. a.:* Rendite unabhängig vom Zeitpunkt der Käufe, vergleichbar mit Fonds und Indizes.
- *Vergleich mit einem Index:* Depot und Index starten beim ersten Kauf mit 100, beide samt Dividenden (Depot mit den Brutto-Dividenden, Index dividendenbereinigt). Zusätzlich zeigt die App, was mit denselben Ein- und Auszahlungen im Index angelegt wäre.
- *Brutto-Dividenden:* Am Ex-Tag rechnet die App Stückzahl am Vorabend × Dividende je Aktie laut Yahoo, zum Tageskurs in Euro. Die Beträge zählen als Auszahlung an dich in Gewinn, persönlicher und zeitgewichteter Rendite und erscheinen in der Zeile unter dem Depotwert sowie unter **Entwicklung** (gesamt, letzte 12 Monate, je Jahr und je Position). Brutto heißt vor Quellensteuer und Abgeltungssteuer; gutgeschrieben wird weniger. Thesaurierende Fonds schütten nichts aus, ihre Erträge stecken im Kurs.
- *Entwicklung je Position:* Gewinn oder Verlust jeder Position seit dem ersten Kauf, realisiert und unrealisiert.

**Kursdaten und Kennzahlen.** Wertentwicklung der Positionen im Analysezeitraum, erwartete Rendite, CAGR, Volatilität, Sharpe-Ratio, maximaler Drawdown und Korrelationen.

**Aufteilung.** Nach Sektoren und Handelswährungen. ETFs werden über ihre Sektorgewichte aufgeschlüsselt (Durchschau), soweit Yahoo diese liefert. Eine Länderaufteilung gibt es bewusst nicht: Für Fonds liefert die Datenquelle keine, und ohne sie wäre das Bild schief.

**Speichern.** Jede Änderung wird als JSON im Ordner `portfolios/` gespeichert (Demo-Portfolios in `portfolios/demo/`). Der Ordner ist von Git ausgeschlossen, weil er private Daten enthält. Gelöschte Portfolios landen 30 Tage im Papierkorb (`portfolios/papierkorb/`) und lassen sich unter **Verwalten → Papierkorb** wiederherstellen. Mit der Umgebungsvariable `PORTFOLIO_DIR` lässt sich ein anderer Ort wählen. Export und Import als JSON oder CSV (Semikolon, deutsches Zahlen- und Datumsformat). Pflicht sind die Spalten `Symbol` und `Stück`, optional `Datum`, `Typ` (Kauf oder Verkauf, sonst Kauf) und `Kurs` in Euro je Stück. Ist der Kurs leer, übernimmt der Import den Schlusskurs des Tages (in der damaligen Stückelung, wie beim Erfassen von Hand); für exakte Gewinne den Kurs aus der Abrechnung eintragen. Ein Beispieldepot für Präsentationen liegt in `docs/praesentationsdepot.csv`:

```
Datum;Typ;Symbol;Stück;Kurs
15.03.2022;Kauf;SAP.DE;10;120,50
02.05.2024;Kauf;EUNL.DE;25,5;88,10
10.06.2025;Verkauf;SAP.DE;4;235,00
```

Dateien im früheren Format (`Symbol;Stück;Kaufkurs`) werden weiterhin gelesen; ihre Käufe haben dann kein Datum und gehen erst in die Wertentwicklung ein, wenn eines ergänzt ist.

## Analysen

- **Klumpenrisiko:** Konzentration nach Einzelaktie, Sektor, Fremdwährung und Gruppen stark korrelierter Einzelwerte (hierarchisches Clustering). Zu jeder Gruppe gehört neben dem Gewicht der **Risikoanteil**, also der Teil der Depotschwankung, den sie verursacht. Die Grenzen (Standard: 10 % je Aktie, 30 % je Sektor, 50 % je Fremdwährung, 40 % je Cluster) sind unter „Grenzen anpassen“ einstellbar und gelten auch für die Umschichtung.
- **Markowitz – Efficient Frontier:** effizienter Rand der Depotpositionen mit Kapitalmarktlinie, Minimum-Varianz- und Max-Sharpe-Portfolio und dem eigenen Depot. **Effizient bei Zielrisiko** ist das Portfolio mit der höchsten erwarteten Rendite bei der gewählten Volatilität. Voreingestellt ist das Risiko des eigenen Depots; die Kennzahlen zeigen dann, wie viel mehr Rendite bei gleichem Risiko laut Schätzung möglich wäre. Das Diagramm **Zusammensetzung der effizienten Portfolios je Risikoniveau** zeigt für jedes Risiko die Gewichte des effizienten Portfolios; eine gestrichelte Linie markiert das Zielrisiko.
- **Monte Carlo:** parametrische Simulation (korrelierte geometrische Brownsche Bewegung) oder historisches Block-Bootstrap, mit Sparrate, Fächerdiagramm, Verteilung des Endvermögens, Verlust- und Zielwahrscheinlichkeit und Drawdowns. Vorausgewählt sind das eigene Depot und sein Wert als Anfangskapital.
- **Schätzfehler:** Konfidenzintervalle der erwarteten Renditen, Sensitivität der Gewichte, Simulationsexperiment „versprochen vs. geliefert“, Vergleich mit Shrinkage, Resampling, Minimum-Varianz und 1/N.

![Markowitz-Abschnitt mit dem Beispieldepot](docs/frontier.png)

Alle Risiko- und Hedge-Kennzahlen des Klumpenrisikos und der Lösungen beruhen auf historischen **Wochenrenditen in Euro**. Wochendaten mildern Verzerrungen durch unterschiedliche Handelszeiten der Börsen. Markowitz, Monte Carlo und Schätzfehler nutzen Tagesrenditen der bis zu 24 größten Positionen.

## Lösungen

- **Umschichtung:** Käufe und Verkäufe, um die Klumpenrisiko-Grenzen mit möglichst wenig Umschichtung einzuhalten (quadratisches Programm, optional mit einem Welt-ETF als Ausgleich), oder um zum effizienten Portfolio bei gleichem Risiko, zum Minimum-Varianz- oder zum Max-Sharpe-Portfolio zu kommen. Sind die Grenzen mit den vorhandenen Positionen nicht erreichbar, kommt der Vorschlag ihnen so nahe wie möglich und nennt den verbleibenden Überhang. Angezeigt werden Stückzahlen (auf Wunsch ganze Stücke), Beträge, Restliquidität und die durch Verkäufe realisierten Gewinne nach FIFO.
- **Absicherung:**
  - *Markt-Hedge:* Beta des Depots gegenüber mehreren Indizes. Das Instrument mit dem höchsten R² ist der beste Hedge; Short-Betrag = Beta × Depotwert × Absicherungsquote.
  - *Beimischung:* Wirkung von Anleihen, Geldmarkt, Gold, Nebenwerten usw. auf Volatilität, maximalen Rückgang und Rendite.
  - *Klumpenrisiko absichern:* Für jede Konzentration über der Grenze der Verkaufsbetrag bis zur Grenze oder die Absicherung genau dieses Überhangs über das am besten passende Sektor- oder Index-Instrument bzw. ein Devisentermingeschäft.

## Fehlende Kurse

Yahoo begrenzt, wie oft Daten abgefragt werden dürfen. Kommen zu viele Anfragen in kurzer Zeit („Too Many Requests“), liefert Yahoo für einzelne Wertpapiere zeitweise nichts – das betrifft beliebige Werte, etwa SAP ebenso wie Fonds. Bei Fonds mit Morningstar-Kennung (Symbole wie `0P0001O0JW`) kommt hinzu, dass Yahoo deren Anteilspreise oft nur lückenhaft und mit ein bis zwei Tagen Verzögerung führt.

Die App geht damit so um:

- Kurse, Dividendenbereinigung und Splits eines Depots kommen in **einem** Abruf, samt Wechselkursen.
- Fehlt ein Wertpapier, fragt die App es nach einer kurzen Pause einzeln noch einmal ab.
- Vollständige Ergebnisse bleiben eine Stunde im Zwischenspeicher, lückenhafte nur zwei Minuten – danach versucht es die App erneut, statt die Lücke eine Stunde festzuhalten.
- Jede erfolgreich geladene Kursreihe wird lokal gespeichert (`portfolios/kurse/`). Liefert Yahoo später nichts, rechnet die App mit diesen Kursen weiter und zeigt den Stand an.
- Liefert Yahoo keine Stammdaten (Name, Währung, Art), wird nichts geraten und gespeichert; die App meldet das, und ein zweiter Versuch einige Sekunden später klappt in der Regel.

Fehlt ein Fonds dauerhaft, hilft oft die Suche nach seiner ISIN und die Wahl einer Notierung mit Börsenkürzel (etwa `.F` für Frankfurt). Außerdem lohnt es sich, yfinance aktuell zu halten (`python -m pip install -U yfinance`), weil Yahoo seine Schnittstelle immer wieder ändert.

## Methodik

**Schätzung.** Grundlage sind einfache Tagesrenditen. Erwartete Renditen und Kovarianzen werden mit 252 Handelstagen annualisiert.

Voreingestellt sind Bayes-Stein und Ledoit-Wolf (unter **Einstellungen** auf die Stichprobenschätzer umstellbar), weil sie die Schätzfehler der Optimierung dämpfen.

- *Bayes-Stein (Jorion 1986):* zieht die Mittelwerte in Richtung der Rendite des Minimum-Varianz-Portfolios.
- *Ledoit-Wolf (2004):* Shrinkage der Kovarianzmatrix zum Modell konstanter Korrelation. Die Varianzen bleiben dabei erhalten.

**Optimierung.** Für jede Zielrendite $r^*$ wird

$$\min_w \; w^\top \Sigma w \quad \text{u. d. N.} \quad w^\top\mu = r^*,\quad \mathbf 1^\top w = 1,\quad l \le w_i \le u$$

gelöst, mit Gewichtsgrenzen numerisch (SLSQP) und ohne Grenzen in geschlossener Form. Das Max-Sharpe-Portfolio der App (Effizienz, Vergleich, Umschichtung) ist standardmäßig nach Michaud geglättet: das Mittel der Max-Sharpe-Gewichte aus 100 Parameterziehungen, die zur Schätzunsicherheit passen (fester Startwert, also reproduzierbar). Es liegt etwas unter dem geschätzten Rand, ist aber breiter gestreut; unter **Einstellungen** lässt sich das klassische Portfolio wählen. Das Max-Sharpe-Portfolio wird über das konvexe Ersatzproblem $\min_y y^\top\Sigma y$ unter $(\mu - r_f)^\top y = 1$ mit $w = y/\mathbf 1^\top y$ bestimmt. Weil dieses Problem konvex ist, gibt es keine lokalen Nebenoptima.

**Monte Carlo.** Die parametrische Variante simuliert monatliche Log-Renditen $\mathcal N\big((\mu - \tfrac12\operatorname{diag}\Sigma)\,\Delta t,\; \Sigma\,\Delta t\big)$. Das Bootstrap zieht zusammenhängende Blöcke von 21 historischen Handelstagen, wodurch Fat Tails und kurzfristige Abhängigkeiten erhalten bleiben. Das Portfolio wird monatlich auf die Zielgewichte zurückgesetzt; die Sparrate wird am Monatsende eingezahlt.

**Wertentwicklung.** Der Depotwert ergibt sich täglich aus den Beständen laut Transaktionen und den Schlusskursen in Euro. Für die zeitgewichtete Rendite fließen Käufe und Verkäufe zu Tagesbeginn zum Transaktionskurs zu bzw. ab; die Tagesrendite ist $(V_t - V_{t-1} - F_t)/(V_{t-1} + F_t)$ mit dem Nettozufluss $F_t$. Der interne Zinsfuß löst $\sum_i C_i\,(1+r)^{-(t_i - t_0)/365} = 0$ für alle Zahlungen $C_i$ einschließlich des heutigen Depotwerts.

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
app.py                         Einstieg: Konten, Kopfzeile und Navigation (Übersicht · Depot · Analysen)
Dockerfile                     Container für die Website (z. B. Railway), mit Konten
views/                         Die Seiten der Navigation (uebersicht.py, depot.py, analysen.py)
ui/
  auth.py                      Konten: Anmelden, Konto erstellen, angemeldet bleiben, Passwort vergessen, Abmelden, Konto löschen
  landing_view.py              Startseite für Abgemeldete: Anmeldung, Beispiel, Kennzahlen, Datenblatt, Impressum, Datenschutz
  header.py                    Depot-Auswahl, Neu, Export/Import, Löschen, Papierkorb, Einstellungen, Konto
  state.py                     Einstellungen, zwischengespeicherte Marktdaten, Portfolio-Kontext, Ablage je Konto
  common.py                    Designsystem (hell und dunkel, Nachtflächen), Bewegung, Segment-Schalter, Karten
  xray.py                      Karte Klumpenrisiko: jetzt/nach Umschichtung und Was wäre, wenn
  overview_view.py             Übersicht
  portfolio_view.py            Depot
  analysis_view.py             Analysen mit Was-wäre-wenn-Regler und Lösungen
  solutions_view.py            Lösungs-Bausteine: Umschichtung und Absicherung
portfolio_optimizer/
  data.py                      Kursabruf bei Yahoo Finance, Datenbereinigung
  estimators.py                Mittelwert- und Kovarianzschätzer (Stichprobe, Bayes-Stein, Ledoit-Wolf)
  optimization.py              Minimum-Varianz, Max-Sharpe, Efficient Frontier, Zielrendite/-volatilität
  monte_carlo.py               GBM-Simulation und Block-Bootstrap
  instability.py               Schätzunsicherheit, Sensitivität, Simulationsexperimente
  market.py                    Suche, Stammdaten, Kurse, Live-Kurse, Wechselkurse (Yahoo und Offline-Demo)
  portfolio.py                 Transaktionen, Sparpläne, FIFO, Aktiensplits, Speichern/Laden mit Papierkorb, Bewertung
  price_store.py               Lokaler Kursspeicher als Rückfall, wenn Yahoo zeitweise nichts liefert
  performance.py               Depotwert, Einzahlungen, zeitgewichtete Rendite, interner Zinsfuß, Indexvergleich
  concentration.py             Klumpenrisiko: Konzentrationen, Cluster, Risikoanteile
  hedging.py                   Markt-Hedge, Beimischungen, Absicherung von Klumpen
  rebalancing.py               Zielgewichte unter Grenzen, Käufe und Verkäufe
  charts.py                    Plotly-Diagramme
  formatting.py                Deutsche Zahlenformate
  accounts.py                  Konten und Sitzungen (SQLite, scrypt), Sperre nach Fehlversuchen, Links für neue Passwörter
  migrations.py                Versionierte Migrationen des Datenspeichers mit Sicherung, läuft beim Start
  mailer.py                    E-Mail-Versand über die Resend-API oder SMTP
static/                        Bildmarke und Schrift (Inter, SIL Open Font License), von der App ausgeliefert
tests/                         pytest-Suite, inkl. Rauchtests der Oberfläche
scripts/smoke_test.py          Smoke-Test gegen eine laufende Instanz (CI-Container und Live-Seite)
.github/workflows/             CI vor dem Deploy, Live-Check danach (siehe Automatisches Deployment)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Die Tests prüfen unter anderem die Optimierer gegen geschlossene Lösungen, den Ledoit-Wolf-Schätzer gegen eine direkte Umsetzung der Formeln aus dem Paper, die Monte-Carlo-Simulation gegen analytische Erwartungswerte, FIFO, Rendite und internen Zinsfuß an Hand gerechneter Beispiele sowie alle Ebenen und Abschnitte der Oberfläche mit `streamlit.testing`. Netzwerkzugriffe werden in den Tests durch Attrappen ersetzt.

## Grenzen

- Keine Anlageberatung. Die App ist ein Lern- und Analysewerkzeug.
- Transaktionskosten und Steuern werden nicht berücksichtigt. Dividenden zählen brutto, am Ex-Tag statt am Zahltag und so, wie Yahoo sie führt; bei manchen Fonds fehlen dort Ausschüttungen, die Offline-Demo schüttet nie aus.
- Von den Kapitalmaßnahmen werden nur Aktiensplits automatisch berücksichtigt; Abspaltungen, Fusionen und Bezugsrechte als Transaktionen erfassen (siehe oben).
- Absicherungen und Umschichtungen beruhen auf historischen Daten. Hedges sichern mit dem Risiko auch die erwartete Rendite ab und verursachen Kosten.
- Die parametrische Simulation unterstellt normalverteilte Log-Renditen und behandelt die geschätzten Parameter als bekannt. Wie problematisch das ist, zeigt der Abschnitt „Schätzfehler“.
- Die frühere Seitenleiste mit freier Ticker-Auswahl, CSV-Kursdateien und Demo-Assetklassen ist vorerst ausgeblendet; die Analysen beziehen sich auf das eigene Depot.

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

 
### Import: CSV, Broker-Export und PDF-Vermögensübersicht

Alles läuft über denselben Import (**Verwalten → Import/Export** oder die Karte
„Depot importieren“ in der Übersicht). Die Art der Datei wird automatisch erkannt:

- **JSON**: Export dieser App.
- **CSV** mit Symbol und Stück, optional Datum, Typ und Kurs; leere Kurse werden mit dem
  Schlusskurs des Tages gefüllt.
- **Broker-Export (CSV)**, etwa die Transaktionshistorie von Trade Republic: Nur plausible
  `BUY` und `SELL` werden zu Käufen und Verkäufen (Kurs aus `price` oder `amount`/Stück,
  sonst Schlusskurs des Tages). Dividenden, Zinsen, Ein- und Auszahlungen, Steuern und
  Kartenzahlungen erzeugen keine Stücke; `FREE_RECEIPT`, `SPLIT`, `MERGER` und unbekannte
  Buchungsarten werden nicht übernommen und in der Meldung gezählt. Splits kommen aus den
  Kursdaten.
- **PDF-Vermögensübersicht** (Trade Republic): Jede Position wird als Kauf zum Stichtag
  übernommen, als Einstand gilt der Wert laut Beleg. Bargeld wird nicht übernommen. Weicht
  die Summe der Positionen vom Gesamtwert ab, steht das in der Meldung.

ISINs werden über die Suche einem Börsensymbol zugeordnet; was sich nicht zuordnen lässt,
wird übersprungen und genannt. Das Auslesen von PDFs braucht das Paket `pdfplumber` (steht in
`requirements.txt`); fehlt es, meldet der Import das, statt abzustürzen. Hochgeladene Dateien
werden nicht gespeichert, nur das daraus erzeugte Depot.
