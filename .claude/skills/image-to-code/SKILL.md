---
name: image-to-code
description: Turn a design reference (screenshot, mockup, Figma export, photo of a sketch) into working UI code for this Streamlit app. Use when the user shares an image and asks to build, recreate, or match that layout or look.
---

# Image-to-Code – Design-Vorlage in Code umsetzen

## 1. Bild analysieren (bevor Code entsteht)

Das Bild mit dem Read-Tool öffnen und schriftlich festhalten:
- **Layout**: Raster, Spalten, Reihenfolge der Bereiche, was oben/unten steht.
- **Komponenten**: Kennzahlen-Kacheln, Tabellen, Charts, Tabs, Buttons, Formulare.
- **Tokens**: Farben (Hex schätzen), Schriftgrößen und -gewichte, Abstände
  (auf 4/8-px-Raster runden), Eckenradien, Rahmen und Schatten.
- **Inhalte**: Texte und Beispieldaten; unklare Stellen als Annahme markieren.

## 2. Auf die vorhandene App abbilden

- Bestehende Bausteine wiederverwenden: `ui/common.py` (Styles/Helfer),
  `ui/header.py`, die Views in `ui/*_view.py` und `views/`.
- Streamlit-Primitive bevorzugen (`st.columns`, `st.metric`, `st.tabs`,
  `st.dataframe`, `st.plotly_chart`/`st.altair_chart`), eigenes CSS nur
  dort, wo Streamlit es nicht kann – gesammelt an einer Stelle.
- Echte Daten und Berechnungen aus `portfolio_optimizer/` anbinden, keine
  Fantasiewerte hartkodieren.

## 3. Bauen und vergleichen

1. App starten: `python -m streamlit run app.py --server.headless true`.
2. Mit dem Skill `playwright-cli` einen Screenshot in derselben Breite wie
   die Vorlage machen (zusätzlich 375 px für Mobil).
3. Vorlage und Screenshot nebeneinander prüfen: Abstände, Ausrichtung,
   Farben, Schriftgrößen. Abweichungen korrigieren, bis es passt.
4. Kurz berichten, was übernommen wurde und wo bewusst abgewichen wurde.
