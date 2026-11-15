"""Smoke-Test gegen eine laufende Instanz der App: in der CI gegen den frisch gebauten Container,
nach jedem Railway-Deploy gegen die Live-Seite.

    python scripts/smoke_test.py https://portfolio-optimierer-production.up.railway.app
    python scripts/smoke_test.py http://localhost:8501 --register test@beispiel.de   # nur Test-Container!
    python scripts/smoke_test.py http://localhost:8501 --login test@beispiel.de      # nach einem Neustart

Ohne Option wird nur gelesen: Health-Check, Startseite ohne Fehler, Impressum und Datenschutz.
``--register`` legt ein Konto an, ``--login`` meldet sich damit an (Passwort aus ``SMOKE_PASSWORD``).
Nie gegen die Live-Seite mit ``--register``: das Konto bliebe dort liegen.

Braucht Playwright: ``pip install playwright`` und ``python -m playwright install chromium``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

from playwright.sync_api import Page, expect, sync_playwright

TIMEOUT = 60_000  # ms; Streamlit baut die Seite erst im Browser auf


def wait_healthy(url: str, seconds: int) -> None:
    deadline, last = time.monotonic() + seconds, None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=10) as response:
                if response.status == 200 and response.read().strip() == b"ok":
                    return
                last = f"HTTP {response.status}"
        except Exception as exc:  # noqa: BLE001 - jeder Fehler heißt: noch nicht bereit
            last = exc
        time.sleep(3)
    raise AssertionError(f"{url}/_stcore/health antwortet nach {seconds} s nicht mit ok ({last})")


def no_errors(page: Page) -> None:
    errors = page.locator('[data-testid="stException"]')
    if errors.count():
        raise AssertionError(f"Fehler auf der Seite: {errors.first.inner_text()[:800]}")


def open_landing(page: Page, url: str) -> None:
    page.goto(url)
    expect(page.locator(".st-key-login_email input")).to_be_visible(timeout=TIMEOUT)
    expect(page.locator("h1").first).to_be_visible()
    no_errors(page)


def check_dialog(page: Page, button_key: str, text: str) -> None:
    page.locator(f".st-key-{button_key} button").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text(text, timeout=TIMEOUT)
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)


def expect_signed_in(page: Page) -> None:
    expect(page.locator(".st-key-login_email")).to_have_count(0, timeout=TIMEOUT)
    expect(page.get_by_role("button", name="Konto")).to_be_visible(timeout=TIMEOUT)
    no_errors(page)


def register(page: Page, email: str, password: str) -> None:
    page.locator(".st-key-auth_mode").get_by_text("Konto erstellen").click()
    page.locator(".st-key-register_email input").fill(email)
    page.locator(".st-key-register_password input").fill(password)
    page.locator('[data-testid="stForm"]').get_by_role("button", name="Konto erstellen").click()
    expect_signed_in(page)


def login(page: Page, email: str, password: str) -> None:
    page.locator(".st-key-login_email input").fill(email)
    page.locator(".st-key-login_password input").fill(password)
    page.locator('[data-testid="stForm"]').get_by_role("button", name="Anmelden").click()
    expect_signed_in(page)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    account = parser.add_mutually_exclusive_group()
    account.add_argument("--register", metavar="EMAIL", help="Konto anlegen (nur Test-Container)")
    account.add_argument("--login", metavar="EMAIL", help="mit einem bestehenden Konto anmelden")
    parser.add_argument("--wait", type=int, default=240, help="Sekunden, die der Health-Check warten darf")
    args = parser.parse_args()
    url = args.url.rstrip("/")
    password = os.environ.get("SMOKE_PASSWORD", "")
    if (args.register or args.login) and len(password) < 10:
        parser.error("SMOKE_PASSWORD mit mindestens 10 Zeichen setzen")

    steps = [("Health-Check", lambda page: wait_healthy(url, args.wait)),
             ("Startseite ohne Fehler", lambda page: open_landing(page, url)),
             ("Impressum", lambda page: check_dialog(page, "po_imprint", "§ 5 DDG")),
             ("Datenschutz", lambda page: check_dialog(page, "po_privacy", "Verantwortlicher"))]
    if args.register:
        steps.append((f"Konto {args.register} anlegen", lambda page: register(page, args.register, password)))
    if args.login:
        steps.append((f"Anmelden als {args.login}", lambda page: login(page, args.login, password)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, locale="de-DE")
        try:
            for name, step in steps:
                started = time.monotonic()
                step(page)
                print(f"ok    {name} ({time.monotonic() - started:.1f} s)", flush=True)
        except Exception:
            page.screenshot(path="smoke-fehler.png", full_page=True)
            print(f"FEHLER {name}; Screenshot: smoke-fehler.png", flush=True)
            raise
        finally:
            browser.close()
    print(f"Smoke-Test bestanden: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
