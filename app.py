"""Streamlit-Oberfläche des Portfolio-Optimierers.

Start: ``python -m streamlit run app.py`` (oder einfach ``python app.py``)

Drei Ebenen in der oberen Leiste – Portfolio, Analysen, Lösungen. Jede Seite
besteht aus aufklappbaren Abschnitten, die erst beim Aufklappen rechnen.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import streamlit as st
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    from ui import common, header, state
except ModuleNotFoundError as exc:
    package = (exc.name or "").split(".")[0]
    if package in ("portfolio_optimizer", "ui"):
        raise
    sys.exit(
        f"Das Python-Paket „{package}“ ist für diesen Python-Interpreter nicht installiert:\n"
        f"    {sys.executable}\n\n"
        "Bitte im Terminal im Projektordner ausführen:\n"
        "    python -m pip install -r requirements.txt\n"
        "und die App danach mit „python -m streamlit run app.py“ starten."
    )

if __name__ == "__main__" and get_script_run_ctx(suppress_warning=True) is None:
    # Direkt mit "python app.py" oder dem Start-Button von VS Code aufgerufen:
    # Streamlit starten, das dieses Skript dann im Browser ausführt.
    from streamlit.web import cli

    sys.argv = ["streamlit", "run", os.path.abspath(__file__), *sys.argv[1:]]
    sys.exit(cli.main())

HERE = Path(__file__).resolve().parent
st.set_page_config(page_title="Portfolio-Optimierer", page_icon=str(HERE / "static" / "mark.svg"), layout="wide",
                   initial_sidebar_state="collapsed")

PAGES = [
    st.Page("views/portfolio.py", title="Portfolio", default=True),
    st.Page("views/analysen.py", title="Analysen"),
    st.Page("views/loesungen.py", title="Lösungen"),
]


def main() -> None:
    common.keep_page_state()
    st.logo(str(HERE / "static" / "logo.svg"), size="large")
    th = common.theme()
    common.inject_style()
    page = st.navigation(PAGES, position="top")
    settings = header.render()
    ctx = state.load_context(settings)
    st.session_state["_run"] = state.build_run(settings, ctx, th)
    page.run()


main()
