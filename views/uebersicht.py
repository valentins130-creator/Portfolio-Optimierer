"""Übersicht: Depotwert, Klumpenrisiko jetzt und nach Umschichtung, Hinweise, Schnellzugriff."""

from ui import overview_view
from ui.state import current_run

overview_view.render(current_run())
