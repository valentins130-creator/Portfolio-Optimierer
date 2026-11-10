---
name: awesome-design
description: Real-world design systems (colors, typography, spacing, components) from 84 well-known products as DESIGN.md references. Use when choosing a visual direction, restyling the UI, picking a palette or type scale, or when the user says "make it look like X" (e.g. Stripe, Linear, Revolut, Wise, Mercury, Coinbase).
---

# Awesome Design – echte Design-Systeme als Referenz

Quelle: VoltAgent/awesome-design-md (MIT, siehe `LICENSE`). Jede Datei in
`systems/` beschreibt ein Design-System: Farb-Tokens, Typografie, Abstände,
Radien, Komponenten und die Stimmung der Marke.

## Vorgehen

1. `INDEX.md` lesen und 1–3 passende Systeme auswählen. Für diesen
   Portfolio-Optimierer (Finanz-App) passen meist: `stripe`, `mercury`,
   `wise`, `revolut`, `coinbase`, `kraken`, `nerdwallet`, `linear.app`, `vercel`.
2. Nur die ausgewählten Dateien in `systems/` lesen (sie sind groß, nicht
   alle auf einmal laden).
3. Die Tokens (Farben, Schriftgrößen, Abstände, Radien) in das Theme der
   App übertragen. In diesem Repo: `.streamlit/config.toml` (falls vorhanden)
   und das CSS in `ui/common.py`.
4. Die Referenz als **Inspiration** nutzen: Struktur und Prinzipien
   übernehmen, keine Logos, Markennamen oder lizenzierten Schriften kopieren.
   Für lizenzierte Fonts eine freie Alternative wählen (z. B. Inter).
5. Semantische Farben für Gewinne/Verluste (`semantic-up` / `semantic-down`)
   auf ausreichenden Kontrast prüfen.
