"""Ebene 2 – Analysen: Klumpenrisiko, Markowitz, Monte Carlo und Schätzfehler."""

from ui import analysis_view
from ui.state import current_run

analysis_view.render(current_run())
