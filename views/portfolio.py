"""Ebene 1 – Portfolio: Daten und Aufteilung des eigenen Depots."""

from ui import portfolio_view
from ui.state import current_run

portfolio_view.render(current_run())
