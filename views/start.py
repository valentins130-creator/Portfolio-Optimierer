"""Start – was die App kann und wie es um das gewählte Depot steht."""

from ui import start_view
from ui.state import current_run

start_view.render(current_run())
