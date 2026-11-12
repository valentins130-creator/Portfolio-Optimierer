/* Portfolio-Optimierer – Landingpage
   Kleine Interaktionen ohne Bibliothek: Hell/Dunkel, mobiles Menü, Vorher/Nachher im
   Beispieldepot und das Kontaktformular mit Entwurfsspeicher.

   Konfiguration im HTML am Formular (#contact-form):
     data-email     Empfängeradresse für Anfragen (auch im Text der Seite verwendet)
     data-endpoint  optional: URL eines Formular-Dienstes, der JSON per POST annimmt.
                    Leer = die Anfrage wird als E-Mail vorbereitet (mailto). */

(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const storage = {
    get(key) {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(key, value);
      } catch {
        /* Speicher nicht verfügbar: Seite funktioniert trotzdem */
      }
    },
    remove(key) {
      try {
        localStorage.removeItem(key);
      } catch {
        /* siehe oben */
      }
    },
  };

  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const decimal1 = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const integer = new Intl.NumberFormat("de-DE");
  const euro = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });
  const percent = (value) => `${decimal1.format(value)} %`;

  /* ---------------------------------------------------------------- Hell / Dunkel */
  function initTheme() {
    const button = $("[data-theme-toggle]");
    if (!button) return;
    const tip = $("[data-theme-tip]");
    const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const root = document.documentElement;
    const current = () => root.getAttribute("data-theme") || (darkQuery.matches ? "dark" : "light");

    const render = () => {
      const dark = current() === "dark";
      const label = dark ? "Helles Design aktivieren" : "Dunkles Design aktivieren";
      button.setAttribute("aria-label", label);
      if (tip) tip.textContent = label;
      // SVG-Elemente kennen die Eigenschaft hidden nicht, daher das Attribut setzen
      $('[data-theme-icon="moon"]', button).toggleAttribute("hidden", dark);
      $('[data-theme-icon="sun"]', button).toggleAttribute("hidden", !dark);
      const background = getComputedStyle(document.body).backgroundColor;
      $$('meta[name="theme-color"]').forEach((meta) => meta.setAttribute("content", background));
    };

    button.addEventListener("click", () => {
      const next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      storage.set("po-theme", next);
    });
    darkQuery.addEventListener("change", render);
    // data-theme kann auch von außen kommen (z. B. vom Viewer, der die Seite einbettet)
    new MutationObserver(render).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    render();
  }

  /* ---------------------------------------------------------------- Tooltips: Escape blendet aus */
  function initTooltips() {
    $$(".tip").forEach((tip) => {
      const control = $("button, a", tip);
      if (!control) return;
      control.addEventListener("keydown", (event) => {
        if (event.key === "Escape") tip.classList.add("is-dismissed");
      });
      control.addEventListener("blur", () => tip.classList.remove("is-dismissed"));
      tip.addEventListener("mouseleave", () => tip.classList.remove("is-dismissed"));
    });
  }

  /* ---------------------------------------------------------------- Mobiles Menü */
  function initMenu() {
    const button = $("[data-menu-toggle]");
    const panel = $("#mobile-nav");
    if (!button || !panel) return;
    const tip = $("[data-menu-tip]");
    const isOpen = () => button.getAttribute("aria-expanded") === "true";

    const setOpen = (open, { returnFocus = false } = {}) => {
      button.setAttribute("aria-expanded", String(open));
      const label = open ? "Menü schließen" : "Menü öffnen";
      button.setAttribute("aria-label", label);
      if (tip) tip.textContent = label;
      $('[data-menu-icon="open"]', button).toggleAttribute("hidden", open);
      $('[data-menu-icon="close"]', button).toggleAttribute("hidden", !open);
      panel.hidden = !open;
      panel.classList.toggle("is-open", open);
      if (!open && returnFocus) button.focus();
    };

    button.addEventListener("click", () => setOpen(!isOpen()));
    panel.addEventListener("click", (event) => {
      if (event.target.closest("a")) setOpen(false);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && isOpen()) setOpen(false, { returnFocus: true });
    });
    document.addEventListener("click", (event) => {
      if (isOpen() && !panel.contains(event.target) && !button.contains(event.target)) setOpen(false);
    });
    window.matchMedia("(min-width: 768px)").addEventListener("change", (event) => {
      if (event.matches) setOpen(false);
    });
  }

  /* ---------------------------------------------------------------- Beispieldepot: vorher / nachher
     Werte aus der Offline-Demo der App (portfolio_optimizer), Standardgrenzen,
     Ziel „Klumpenrisiko begrenzen“ mit Welt-ETF als Ausgleich und ganzen Stücken.
     Je Zeile: [Gewicht in %, Risikoanteil in %, Status] */
  const DEMO = {
    before: {
      label: "Vorher",
      exceeded: 4,
      effective: 7.8,
      trades: "Ohne Umschichtung sind 4 Grenzen überschritten, bei 3 Einzelwerten und beim Sektor Technologie.",
      rows: {
        tech: [51.5, 62.8, "over"],
        pch: [17.5, 24.4, "over"],
        lcl: [15.7, 19.0, "over"],
        nls: [14.0, 15.8, "over"],
        usd: [48.9, 59.2, "near"],
      },
    },
    after: {
      label: "Nach Umschichtung",
      exceeded: 0,
      effective: 9.3,
      trades: `Vorschlag: 3 Verkäufe für ${euro.format(12769.65)} und 7 Käufe für ${euro.format(11949.72)}, in ganzen Stücken. Danach hält das Depot alle Grenzen ein.`,
      rows: {
        tech: [29.6, 37.4, "near"],
        pch: [9.7, 14.2, "near"],
        lcl: [8.5, 10.9, "near"],
        nls: [6.6, 7.9, "ok"],
        usd: [37.7, 48.3, "ok"],
      },
    },
  };
  const SCALE_MAX = 60; // Balkenskala in %
  const STATUS_TEXT = { over: "über Grenze", near: "nahe Grenze", ok: "im Rahmen" };

  function initDemo() {
    const card = $(".demo");
    if (!card) return;
    const buttons = $$("[data-demo-state]", card);
    const live = $("[data-demo-live]", card);

    const show = (key) => {
      const data = DEMO[key];
      buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.demoState === key)));
      $('[data-stat="exceeded"]', card).textContent = integer.format(data.exceeded);
      $('[data-stat="effective"]', card).textContent = decimal1.format(data.effective);
      $('[data-stat="tech"]', card).textContent = percent(data.rows.tech[1]);
      Object.entries(data.rows).forEach(([id, [weight, risk, status]]) => {
        const row = $(`[data-row="${id}"]`, card);
        if (!row) return;
        row.classList.remove("is-over", "is-near", "is-ok");
        row.classList.add(`is-${status}`);
        $(".meter-fill", row).style.setProperty("--v", (weight / SCALE_MAX).toFixed(4));
        $("[data-weight]", row).textContent = percent(weight);
        $("[data-risk]", row).textContent = percent(risk);
        $("[data-status]", row).textContent = STATUS_TEXT[status];
      });
      $("[data-trades]", card).textContent = data.trades;
      live.textContent = `${data.label}: ${integer.format(data.exceeded)} Grenzen überschritten, ${decimal1.format(
        data.effective
      )} effektive Positionen.`;
    };

    buttons.forEach((button) =>
      button.addEventListener("click", () => {
        if (button.getAttribute("aria-pressed") !== "true") show(button.dataset.demoState);
      })
    );
  }

  /* ---------------------------------------------------------------- Kontaktformular */
  const DRAFT_KEY = "po-kontakt-entwurf";

  function relativeTime(timestamp) {
    const seconds = Math.round((timestamp - Date.now()) / 1000);
    const abs = Math.abs(seconds);
    if (!Number.isFinite(seconds) || abs < 60) return "gerade eben";
    const rtf = new Intl.RelativeTimeFormat("de", { numeric: "auto" });
    if (abs < 3600) return rtf.format(Math.round(seconds / 60), "minute");
    if (abs < 86400) return rtf.format(Math.round(seconds / 3600), "hour");
    return rtf.format(Math.round(seconds / 86400), "day");
  }

  async function copyText(text) {
    if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error("Zwischenablage nicht verfügbar");
    await navigator.clipboard.writeText(text);
  }

  function selectContents(element) {
    const range = document.createRange();
    range.selectNodeContents(element);
    const selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function initForm() {
    const form = $("#contact-form");
    if (!form) return;
    const panel = form.closest(".contact-panel");
    const recipient = (form.dataset.email || "").trim();
    const endpoint = (form.dataset.endpoint || "").trim();

    $$("[data-contact-email]").forEach((link) => {
      link.href = `mailto:${recipient}`;
      link.textContent = recipient;
    });

    const fields = { name: form.elements.name, email: form.elements.email, message: form.elements.message };
    const names = Object.keys(fields);
    const submit = $("[data-submit]", form);
    const submitLabel = $("[data-submit-label]", form);
    const alertBox = $("[data-form-alert]", form);
    const alertText = $("[data-form-alert-text]", form);
    const copyErrorButton = $("[data-copy-error]", form);
    const resultMail = $('[data-result="mail"]', panel);
    const resultSent = $('[data-result="sent"]', panel);
    const notice = $("[data-draft-notice]", panel);
    const noticeText = $("[data-draft-text]", panel);
    const noticeAction = $("[data-draft-action]", panel);

    const defaultLabel = endpoint ? "Anfrage senden" : "Anfrage per E-Mail senden";
    submitLabel.textContent = defaultLabel;

    /* Prüfregeln: Meldungen nennen, was hilft, nicht was falsch war */
    const rules = {
      name: (value) => (value.trim() ? "" : "Gib deinen Namen ein, damit wir dich ansprechen können."),
      email: (value) => {
        const text = value.trim();
        if (!text) return "Gib eine E-Mail-Adresse ein, zum Beispiel name@beispiel.de.";
        return /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(text) ? "" : "Gib eine E-Mail-Adresse wie name@beispiel.de ein.";
      },
      message: (value) => {
        const text = value.trim();
        if (!text) return "Schreib kurz, worum es geht.";
        return text.length >= 10 ? "" : "Schreib noch ein paar Worte mehr, mindestens 10 Zeichen.";
      },
    };

    // je Feld: pristine (unberührt) | valid | invalid
    const state = { name: "pristine", email: "pristine", message: "pristine" };
    let keepErrorOnFocus = false;

    const errorElement = (name) => document.getElementById(`${name}-error`);
    const showError = (name, message) => {
      const element = errorElement(name);
      $("span", element).textContent = message;
      element.hidden = false;
      fields[name].setAttribute("aria-invalid", "true");
      state[name] = "invalid";
    };
    const hideError = (name) => {
      errorElement(name).hidden = true;
      fields[name].removeAttribute("aria-invalid");
    };
    const validate = (name) => {
      const message = rules[name](fields[name].value);
      if (message) {
        showError(name, message);
        return false;
      }
      hideError(name);
      state[name] = "valid";
      return true;
    };
    const resetValidation = () =>
      names.forEach((name) => {
        hideError(name);
        state[name] = "pristine";
      });

    let lastError = null;
    const showAlert = (message, withDetails = false) => {
      alertText.textContent = message;
      copyErrorButton.hidden = !withDetails;
      alertBox.hidden = !message;
    };
    const hideAlert = () => {
      alertBox.hidden = true;
      alertText.textContent = "";
    };

    /* Entwurf im Browser speichern, damit nichts verloren geht */
    let draftTimer = 0;
    let discarded = null;
    const readForm = () => ({ name: fields.name.value, email: fields.email.value, message: fields.message.value });
    const hasContent = (draft) => Boolean(draft && `${draft.name || ""}${draft.email || ""}${draft.message || ""}`.trim());
    const fillForm = (draft) => names.forEach((name) => (fields[name].value = draft[name] || ""));
    const saveDraft = () => {
      const draft = readForm();
      if (hasContent(draft)) storage.set(DRAFT_KEY, JSON.stringify({ ...draft, updatedAt: Date.now() }));
      else storage.remove(DRAFT_KEY);
    };
    const scheduleDraft = () => {
      window.clearTimeout(draftTimer);
      draftTimer = window.setTimeout(saveDraft, 600);
    };
    const showNotice = (text, actionLabel, mode) => {
      noticeText.textContent = text;
      noticeAction.textContent = actionLabel;
      noticeAction.dataset.mode = mode;
      notice.hidden = false;
    };

    try {
      const saved = JSON.parse(storage.get(DRAFT_KEY) || "null");
      if (hasContent(saved)) {
        fillForm(saved);
        showNotice(`Entwurf wiederhergestellt, zuletzt bearbeitet ${relativeTime(saved.updatedAt)}.`, "Entwurf verwerfen", "discard");
      }
    } catch {
      storage.remove(DRAFT_KEY);
    }

    const discardDraft = () => {
      discarded = readForm();
      form.reset();
      resetValidation();
      hideAlert();
      storage.remove(DRAFT_KEY);
      showNotice("Entwurf verworfen.", "Rückgängig machen", "undo");
    };

    /* Verwerfen nur nach Bestätigung; Abbrechen hat den Fokus, Escape schließt ohne Folgen */
    const dialog = $("[data-discard-dialog]", panel);
    const canUseDialog = Boolean(dialog && typeof dialog.showModal === "function");
    if (canUseDialog) {
      $("[data-dialog-cancel]", dialog).addEventListener("click", () => dialog.close("cancel"));
      $("[data-dialog-confirm]", dialog).addEventListener("click", () => dialog.close("confirm"));
      // Tab bleibt im Dialog: vom letzten Button zurück zum ersten und umgekehrt
      dialog.addEventListener("keydown", (event) => {
        if (event.key !== "Tab") return;
        const buttons = $$("button", dialog);
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      });
      dialog.addEventListener("close", () => {
        if (dialog.returnValue === "confirm") discardDraft();
        dialog.returnValue = "";
        noticeAction.focus();
      });
    }

    noticeAction.addEventListener("click", () => {
      if (noticeAction.dataset.mode === "discard") {
        if (canUseDialog) {
          dialog.returnValue = "";
          dialog.showModal();
          $("[data-dialog-cancel]", dialog).focus();
        } else {
          discardDraft(); // ohne <dialog>: sofort verwerfen, „Rückgängig machen“ bleibt
        }
      } else if (discarded) {
        fillForm(discarded);
        discarded = null;
        saveDraft();
        showNotice("Entwurf wiederhergestellt.", "Entwurf verwerfen", "discard");
      }
    });

    names.forEach((name) => {
      const field = fields[name];
      field.addEventListener("blur", () => validate(name));
      field.addEventListener("focus", () => {
        if (state[name] === "invalid" && !keepErrorOnFocus) hideError(name);
      });
      field.addEventListener("input", () => {
        if (state[name] === "invalid") hideError(name);
        if (state[name] !== "pristine" && !rules[name](field.value)) state[name] = "valid";
        // Ein Übertragungsfehler bleibt sichtbar, bis erneut gesendet wird
        if (copyErrorButton.hidden) hideAlert();
        if (discarded) {
          discarded = null;
          notice.hidden = true;
        }
        scheduleDraft();
      });
    });

    /* Ladezustand erst nach 100 ms zeigen, damit schnelle Antworten nicht flackern */
    let loadingTimer = 0;
    const setLoading = (loading) => {
      window.clearTimeout(loadingTimer);
      if (loading) {
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
        loadingTimer = window.setTimeout(() => {
          submit.classList.add("is-loading");
          submitLabel.textContent = "Wird gesendet…";
        }, 100);
      } else {
        submit.disabled = false;
        submit.removeAttribute("aria-busy");
        submit.classList.remove("is-loading");
        if (submitLabel.textContent === "Wird gesendet…") submitLabel.textContent = defaultLabel;
      }
    };

    const showResult = (result) => {
      form.hidden = true;
      notice.hidden = true;
      result.hidden = false;
      result.focus({ preventScroll: true });
      result.scrollIntoView({ block: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
    };
    const showForm = (focusField) => {
      resultMail.hidden = true;
      resultSent.hidden = true;
      form.hidden = false;
      fields[focusField].focus();
    };

    const prepareMail = (data) => {
      const subject = "Anfrage Depot-Check";
      const body = `${data.message}\n\n${data.name}\n${data.email}`;
      const href = `mailto:${recipient}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
      $("[data-mailto]", resultMail).href = href;
      $("[data-preview]", resultMail).textContent = `An: ${recipient}\nBetreff: ${subject}\n\n${body}`;
      $("[data-copy-status]", resultMail).textContent = "";
      showResult(resultMail);
      try {
        window.location.href = href;
      } catch {
        /* Der Button „E-Mail-Programm öffnen“ bleibt als Weg */
      }
    };

    const sendToEndpoint = async (data) => {
      setLoading(true);
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        storage.remove(DRAFT_KEY);
        form.reset();
        resetValidation();
        hideAlert();
        submitLabel.textContent = defaultLabel;
        $("[data-sent-to]", resultSent).textContent = data.email;
        showResult(resultSent);
      } catch (error) {
        lastError = { zeit: new Date().toISOString(), fehler: String((error && error.message) || error), ziel: endpoint };
        showAlert("Deine Anfrage ist nicht angekommen. Prüf die Verbindung und sende sie erneut.", true);
        submitLabel.textContent = "Erneut senden";
      } finally {
        setLoading(false);
      }
    };

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const invalid = names.filter((name) => !validate(name));
      if (invalid.length) {
        showAlert(invalid.length >= 3 ? `${invalid.length} Felder brauchen noch Angaben.` : "");
        const first = fields[invalid[0]];
        keepErrorOnFocus = true;
        first.focus({ preventScroll: true });
        keepErrorOnFocus = false;
        first.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
        return;
      }
      const data = { name: fields.name.value.trim(), email: fields.email.value.trim(), message: fields.message.value.trim() };
      saveDraft();
      if (endpoint) sendToEndpoint(data);
      else prepareMail(data);
    });

    copyErrorButton.addEventListener("click", async () => {
      try {
        await copyText(JSON.stringify(lastError, null, 2));
        alertText.textContent = "Fehlerdetails kopiert. Sende die Anfrage erneut oder schick uns die Details per E-Mail.";
      } catch {
        alertText.textContent = `Kopieren hat nicht geklappt. Schreib uns direkt an ${recipient}.`;
      }
    });

    $("[data-copy-text]", resultMail).addEventListener("click", async () => {
      const preview = $("[data-preview]", resultMail);
      const status = $("[data-copy-status]", resultMail);
      try {
        await copyText(preview.textContent);
        status.textContent = "Text kopiert.";
      } catch {
        selectContents(preview);
        status.textContent = "Kopieren hat nicht geklappt. Der Text ist markiert, kopiere ihn mit Strg+C oder ⌘+C.";
      }
    });
    $("[data-edit]", resultMail).addEventListener("click", () => showForm("message"));
    $("[data-new]", resultSent).addEventListener("click", () => showForm("name"));
  }

  /* ---------------------------------------------------------------- Jahr im Copyright */
  function initYear() {
    const year = String(new Date().getFullYear());
    $$("[data-year]").forEach((element) => (element.textContent = year));
  }

  initTheme();
  initTooltips();
  initMenu();
  initDemo();
  initForm();
  initYear();
})();
