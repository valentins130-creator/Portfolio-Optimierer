"""Trade Republic import preview with separated snapshot holdings and cash-flow audit."""
from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from portfolio_optimizer.trade_republic_import import CATEGORIES, confirmed_positions, parse_broker_csv, parse_statement_pdf


def render() -> None:
    st.markdown("**Trade Republic: Vermögensübersicht (PDF) und Transaktionen (CSV)**")
    st.caption("PDF = tatsächlicher Bestand am Stichtag. CSV = historische Buchungen. "
               "Dividenden, Zinsen und Einzahlungen erzeugen keine zusätzlichen Stücke. "
               "Die Vorschau bleibt nur in dieser Browser-Sitzung; sie wird nicht automatisch als Portfolio gespeichert.")
    pdf = st.file_uploader("Vermögensübersicht (PDF)", type=["pdf"], key="tr_pdf")
    csv = st.file_uploader("Transaktionshistorie (CSV, optional)", type=["csv"], key="tr_csv")
    snapshot = None
    holdings = None
    audit = None
    counts = None
    if pdf:
        try:
            snapshot = parse_statement_pdf(pdf.getvalue())
        except Exception as exc:
            st.error(f"PDF-Import nicht möglich: {exc}")
    if csv:
        try:
            holdings, audit, counts = parse_broker_csv(csv.getvalue())
        except Exception as exc:
            st.error(f"CSV-Import nicht möglich: {exc}")

    if snapshot is not None:
        st.success(f"Vermögensübersicht vom {snapshot.as_of}: {len(snapshot.positions)} Positionen erkannt.")
        st.metric("Gesamtwert laut PDF", f"{snapshot.expected_total:,.2f} €")
        for issue in snapshot.warnings:
            st.warning(issue)
        st.markdown("**Bestandsliste – Werte und Anlageklassen kontrollieren und korrigieren**")
        frame = snapshot.positions.copy()
        edited = st.data_editor(
            frame,
            key="tr_snapshot_editor_" + hashlib.sha256(pdf.getvalue()).hexdigest(),
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            disabled=["Bereich", "Prüfhinweis"],
            column_config={
                "Anlageklasse": st.column_config.SelectboxColumn("Anlageklasse", options=list(CATEGORIES), required=True),
                "Wert EUR": st.column_config.NumberColumn("Wert EUR", min_value=0.0, format="%.2f"),
                "Anteile": st.column_config.NumberColumn("Anteile", format="%.8f"),
                "Kurs (Beleg)": st.column_config.NumberColumn("Kurs (Beleg)", format="%.4f"),
            },
        )
        edited["Wert EUR"] = pd.to_numeric(edited["Wert EUR"], errors="coerce").fillna(0)
        if edited["Wert EUR"].lt(0).any():
            st.error("Negative Positionswerte sind nicht zulässig.")
            return
        st.caption("Nur ausdrücklich bestätigte, gültige Positionen fließen in Berechnung und Bestandsexport ein.")
        edited = confirmed_positions(edited)
        total = float(edited["Wert EUR"].sum())
        if total > 0:
            edited["Anteil %"] = edited["Wert EUR"] / total * 100
            summary = (edited.groupby("Anlageklasse", dropna=False)["Wert EUR"]
                       .sum().sort_values(ascending=False).rename("Wert EUR").reset_index())
            summary["Anteil %"] = summary["Wert EUR"] / total * 100
            st.subheader("Vermögensaufteilung")
            st.dataframe(summary, hide_index=True, use_container_width=True,
                         column_config={"Wert EUR": st.column_config.NumberColumn(format="%.2f €"),
                                        "Anteil %": st.column_config.NumberColumn(format="%.2f %%")})
            st.bar_chart(summary.set_index("Anlageklasse")["Anteil %"])
            st.caption("Aktien-ETFs werden nicht als Einzelaktien ausgewiesen. "
                       "Leveraged-Produkte sind separat gekennzeichnet; das ist keine Look-through-Risikoanalyse.")
            difference = round(total - snapshot.expected_total, 2)
            if abs(difference) > 0.05:
                st.warning(f"Die bearbeiteten Werte weichen um {difference:+.2f} € vom PDF-Gesamtwert ab.")
            st.download_button(
                "Kontrollierte Bestandsliste als CSV herunterladen",
                data=edited.to_csv(index=False).encode("utf-8-sig"),
                file_name="portfolio_bestand_kontrolliert.csv",
                mime="text/csv",
                key="tr_download_holdings",
            )
        else:
            st.warning("Keine bestätigten, gültigen Positionswerte vorhanden.")
    elif holdings is not None:
        st.info("Ohne Vermögensübersicht können wir nur vorläufige Stückbestände berechnen. "
                "Prozentuale **Wert**anteile benötigen aktuelle Bewertungen; historische Kaufpreise wären irreführend.")
        reviewed = st.data_editor(holdings, hide_index=True, disabled=["Status", "Prüfhinweis"], num_rows="dynamic",
                                  key="tr_csv_review_" + hashlib.sha256(csv.getvalue()).hexdigest())
        approved = confirmed_positions(reviewed)
        st.caption(f"{len(approved)} bestätigte Positionen; alle übrigen sind vom Bestand ausgeschlossen. "
                   "Fehlende Bestände nach Belegprüfung als neue Zeile ergänzen. Doppelte Symbole bleiben ausgeschlossen.")
        st.dataframe(approved, hide_index=True, use_container_width=True)
        st.download_button("Bestätigten Bestand als CSV", approved.to_csv(index=False).encode("utf-8-sig"),
                           file_name="portfolio_bestand_bestaetigt.csv", mime="text/csv")

    if audit is not None:
        with st.expander("CSV-Prüfprotokoll: Käufe, Verkäufe und Kapitalmaßnahmen", expanded=snapshot is None):
            st.caption("Nur gültige BUY und SELL ergeben vorläufige Stückzahlen. FREE_RECEIPT muss geprüft werden. "
                       "SPLIT, MERGER und andere Kapitalmaßnahmen erfordern eine Einzelprüfung. "
                       "Dividenden und reine Geldbewegungen sind ausgeschlossen.")
            summary = pd.DataFrame([{"Buchungstyp": kind, "Anzahl": count}
                                    for kind, count in sorted(counts.items(), key=lambda x: -x[1])])
            st.dataframe(summary, hide_index=True, use_container_width=True)
            needs_review = audit[audit["Status"].str.contains("Prüfen|prüfen", na=False)]
            if len(needs_review):
                st.warning(f"{len(needs_review)} Buchungen müssen manuell geprüft werden.")
            st.dataframe(audit, hide_index=True, use_container_width=True)
            st.download_button("Prüfprotokoll als CSV", audit.to_csv(index=False).encode("utf-8-sig"),
                               file_name="transaktionen_pruefprotokoll.csv", mime="text/csv",
                               key="tr_download_audit")
