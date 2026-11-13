"""Depot: Transaktionen erfassen, Positionen, Entwicklung, Kennzahlen, Aufteilung."""

from ui import portfolio_view
from ui.state import current_run

portfolio_view.render(current_run())
