"""
Zentrale Sprach-Tabelle + Helper fuer DE/EN.

Grundsaetze:
- Deutsch ist Master. Fehlt ein englischer Eintrag, faellt t() automatisch auf
  Deutsch zurueck -> "zurueck auf DE-only" kostet nichts (EN einfach nicht mehr
  pflegen, nichts bricht).
- Sprache ist global (config.LANG), vom Admin umstellbar. Spaeter pro-User
  moeglich: dann NUR get_current_lang() anpassen, alle Aufrufer bleiben gleich.
- Im DE-Modus erzeugt llm_lang_instruction() einen LEEREN String -> die
  validierte deutsche LLM-Ausgabe bleibt unveraendert.
"""

from __future__ import annotations

import config

SUPPORTED = ("de", "en")

# ---------------------------------------------------------------------------
# Sprach-Tabelle:  key -> {"de": ..., "en": ...}
# Deutsch ist der aktuelle Wortlaut der Templates. Englisch wird in Phase 2
# (String-Extraktion) befuellt. Fehlt "en", greift automatisch der DE-Fallback.
# ---------------------------------------------------------------------------
STRINGS: dict[str, dict[str, str]] = {
    # ======================= base.html (geteilte Chrome) =======================
    # Meta / OpenGraph
    "meta.og_title": {"de": "Wingcast – Flugwetter für Gleitschirmpiloten",
                      "en": "Wingcast – Flight weather for paraglider pilots"},
    "meta.og_description": {"de": "Präzise Thermik- und Wind-Prognose für die Schweizer Berge.",
                            "en": "Precise thermal and wind forecasts for the Swiss mountains."},
    # Test-Ansicht-Banner (nur Admin)
    "test_banner.text_pre": {"de": "TEST-ANSICHT AKTIV — Analysen kommen aus",
                             "en": "TEST VIEW ACTIVE — analyses come from"},
    "test_banner.text_post": {"de": ", nicht aus Live-Daten.",
                              "en": ", not from live data."},
    "test_banner.manage": {"de": "Verwalten", "en": "Manage"},
    # Navigation
    "nav.skip_to_content": {"de": "Zum Inhalt springen", "en": "Skip to content"},
    "nav.aria_main": {"de": "Hauptnavigation", "en": "Main navigation"},
    "nav.spots": {"de": "Startplätze", "en": "Launch sites"},
    "nav.regions": {"de": "Regionen", "en": "Regions"},
    "nav.synoptic": {"de": "Synoptik", "en": "Synoptic"},
    "nav.foehn": {"de": "Föhn", "en": "Foehn"},
    "nav.foehn_open": {"de": "Föhndiagramm öffnen", "en": "Open foehn chart"},
    "nav.settings": {"de": "Einstellungen", "en": "Settings"},
    "nav.logout": {"de": "Logout", "en": "Log out"},
    "nav.login": {"de": "Login", "en": "Log in"},
    # gemeinsam
    "common.close": {"de": "Schliessen", "en": "Close"},
    # Login-Modal
    "login.title": {"de": "Login", "en": "Log in"},
    "login.hint": {"de": "Per Magic-Link — passwordlos. Du bekommst einen einmaligen Link per Mail (30 Min gueltig).",
                   "en": "Via magic link — passwordless. You'll receive a one-time link by email (valid 30 min)."},
    "login.email_placeholder": {"de": "du@beispiel.ch", "en": "you@example.com"},
    "login.submit": {"de": "Link schicken", "en": "Send link"},
    "login.fallback_ok": {"de": "Wenn die E-Mail registriert ist, wurde ein Login-Link geschickt. Schau in dein Postfach.",
                          "en": "If the email is registered, a login link has been sent. Check your inbox."},
    "login.invalid_email": {"de": "Bitte gueltige E-Mail-Adresse eingeben.",
                            "en": "Please enter a valid email address."},
    "login.sending": {"de": "Sende ...", "en": "Sending ..."},
    "login.send_failed_pre": {"de": "Versand fehlgeschlagen (Status ",
                              "en": "Sending failed (status "},
    "login.send_failed_post": {"de": "). Bitte spaeter erneut.",
                               "en": "). Please try again later."},
    "login.no_response": {"de": "Server antwortet nicht. Bitte spaeter erneut.",
                          "en": "Server is not responding. Please try again later."},
    "login.connection_failed": {"de": "Verbindung fehlgeschlagen. Internet pruefen und erneut versuchen.",
                                "en": "Connection failed. Check your internet and try again."},
    # Mobile-Navigation (aria + Labels)
    "mobile.aria_nav": {"de": "Mobile Navigation", "en": "Mobile navigation"},
    "mobile.show_chat": {"de": "Chat anzeigen", "en": "Show chat"},
    "mobile.show_spots": {"de": "Spots anzeigen", "en": "Show spots"},
    "mobile.show_regions": {"de": "Regionen anzeigen", "en": "Show regions"},
    "mobile.chat": {"de": "Chat", "en": "Chat"},
    "mobile.spots": {"de": "Spots", "en": "Spots"},
    "common.share_title": {"de": "Wingcast Flugwetter", "en": "Wingcast flight weather"},
    # Föhn-Overlay
    "foehn.title": {"de": "Föhndiagramm", "en": "Foehn chart"},
    "foehn.subtitle": {"de": "Druckdifferenz Lugano – Zürich | 5-Tage-Prognose",
                       "en": "Pressure difference Lugano – Zurich | 5-day forecast"},
    "foehn.loading": {"de": "Lade Föhn-Daten...", "en": "Loading foehn data..."},
    "foehn.no_data": {"de": "Keine Föhn-Daten verfügbar.", "en": "No foehn data available."},
    "foehn.error_prefix": {"de": "Fehler: ", "en": "Error: "},
    # Footer
    "footer.privacy": {"de": "Datenschutz", "en": "Privacy"},
    "footer.imprint": {"de": "Impressum", "en": "Imprint"},

    # Erstbesuch-Disclaimer (Haftungshinweis, einmalig vor erster Nutzung)
    "disclaimer.title": {"de": "Bevor du loslegst", "en": "Before you start"},
    "disclaimer.intro": {
        "de": "Wingcast liefert KI-gestützte Wetter-Einschätzungen — <strong>keine verbindlichen Flugempfehlungen, Freigaben oder Garantien</strong>.",
        "en": "Wingcast provides AI-based weather assessments — <strong>not binding flight recommendations, clearances or guarantees</strong>.",
    },
    "disclaimer.p_ki": {
        "de": "Die KI kann Fehler machen. Prognosen können falsch, veraltet oder unvollständig sein.",
        "en": "The AI can make mistakes. Forecasts may be wrong, outdated or incomplete.",
    },
    "disclaimer.p_responsibility": {
        "de": "Du allein trägst die Verantwortung für deine Flugentscheidung. Prüfe immer aktuelle, offizielle Wetterquellen und beurteile die Bedingungen vor Ort selbst.",
        "en": "You alone are responsible for your decision to fly. Always check current, official weather sources and assess the conditions on site yourself.",
    },
    "disclaimer.p_risk": {
        "de": "Gleitschirm- und Drachenfliegen ist gefährlich und erfolgt auf eigene Gefahr.",
        "en": "Paragliding and hang gliding are dangerous and undertaken at your own risk.",
    },
    "disclaimer.accept": {"de": "Verstanden", "en": "Got it"},

    # ======================= index.html (Cockpit) =======================
    # Chat-Sidebar
    "chat.advisor_title": {"de": "Chat-Berater", "en": "Chat advisor"},
    "chat.data_age": {"de": "Alter der Wetterdaten", "en": "Age of weather data"},
    "chat.new_chat_aria": {"de": "Neuen Chat starten", "en": "Start new chat"},
    "chat.new_chat": {"de": "Neuer Chat", "en": "New chat"},
    "chat.welcome": {"de": "Hallo! Ich bin dein Wingcast-Berater (Beta — Antworten können noch Fehler enthalten). Frag mich zu Flugbedingungen, Gebietswahl oder Sicherheit.",
                     "en": "Hi! I'm your Wingcast advisor (beta — answers may still contain errors). Ask me about flying conditions, choosing an area, or safety."},
    "chat.quick_map_label": {"de": "Karte: 1h ab Zürich", "en": "Map: 1h from Zurich"},
    "chat.quick_map_msg": {"de": "Zeichne mir auf der Karte die Region ein, die ich in 1 Stunde Fahrzeit von Zürich aus erreiche, und zeig mir die fliegbaren Spots darin.",
                           "en": "Draw on the map the region I can reach within 1 hour's drive from Zurich, and show me the flyable spots within it."},
    "chat.quick_top3_label": {"de": "Vergleiche Top 3", "en": "Compare top 3"},
    "chat.quick_top3_msg": {"de": "Vergleiche die drei besten Spots heute in einer Tabelle mit Wind, Thermik und Sicherheit.",
                            "en": "Compare today's three best spots in a table with wind, thermals and safety."},
    "chat.quick_wind_label": {"de": "Windverlauf", "en": "Wind over the day"},
    "chat.quick_wind_msg": {"de": "Zeig mir den Windverlauf vom besten Spot heute als Chart mit Wind und Böen über den Tag.",
                            "en": "Show me the wind profile of today's best spot as a chart with wind and gusts over the day."},
    "chat.input_label": {"de": "Nachricht eingeben", "en": "Enter message"},
    "chat.input_placeholder": {"de": "Frag mich...", "en": "Ask me..."},
    "chat.send_aria": {"de": "Nachricht senden", "en": "Send message"},
    "chat.send": {"de": "Senden", "en": "Send"},
    # Locked-Karte (anonym) — enthaelt HTML, via |safe gerendert
    "locked.title": {"de": "5-Tage-Vorhersage freischalten", "en": "Unlock the 5-day forecast"},
    "locked.lead_html": {"de": "Du siehst aktuell nur <strong>heute</strong>. Mit Login bekommst du <strong>volle 5 Tage</strong> &mdash; <strong>kostenlos</strong>.",
                         "en": "Right now you only see <strong>today</strong>. With login you get <strong>all 5 days</strong> &mdash; <strong>free</strong>."},
    "locked.item1_html": {"de": "<strong>5 Tage</strong> Vorhersage statt 1",
                          "en": "<strong>5 days</strong> of forecast instead of 1"},
    "locked.item2_html": {"de": "<strong>Chat-Berater</strong> <span class=\"beta-badge beta-badge--inline\">Beta</span> mit Live-Wetter-Daten",
                          "en": "<strong>Chat advisor</strong> <span class=\"beta-badge beta-badge--inline\">Beta</span> with live weather data"},
    "locked.item3_html": {"de": "<strong>E-Mail-Wingcast</strong> an deinen Wunschtagen",
                          "en": "<strong>Email Wingcast</strong> on the days you choose"},
    "locked.cta": {"de": "Jetzt einloggen", "en": "Log in now"},
    "locked.hint": {"de": "Kein Konto? Wird automatisch angelegt.", "en": "No account? One is created automatically."},
    # Admin-Spot-Suche
    "admin.spot_search_placeholder": {"de": "Spot suchen…", "en": "Search spot…"},
    "admin.spot_search_aria": {"de": "Spot suchen (Admin)", "en": "Search spot (admin)"},
    # Meteogramm-Overlay
    "meteogram.title": {"de": "Meteogramm", "en": "Meteogram"},
    "meteogram.view_aria": {"de": "Ansicht", "en": "View"},
    "meteogram.tab_data_title": {"de": "Welche Daten die KI sieht", "en": "What data the AI sees"},
    "meteogram.tab_data": {"de": "Daten", "en": "Data"},
    "meteogram.share_aria": {"de": "Startplatz teilen", "en": "Share launch site"},
    "meteogram.share_title": {"de": "Teilen (WhatsApp)", "en": "Share (WhatsApp)"},
    "meteogram.analysis": {"de": "Analyse", "en": "Analysis"},
    "meteogram.tap_expand": {"de": "Tippen zum Aufklappen", "en": "Tap to expand"},
    "meteogram.analysis_toggle_aria": {"de": "Analyse ein-/ausblenden", "en": "Show/hide analysis"},
    # Status-Pill auf der Karte
    "status.as_of": {"de": "Stand: ", "en": "As of: "},

    # ======================= regionen.html =======================
    # (Chat-Sidebar + Locked-Karte teilen sich die Keys mit index.html)
    "region.overlay_aria": {"de": "Region-Analyse", "en": "Region analysis"},
    "region.share_aria": {"de": "Region teilen", "en": "Share region"},
    "region.no_analyses": {"de": "Keine Region-Analysen vorhanden", "en": "No region analyses available"},

    # ======================= account.html =======================
    "account.title": {"de": "Dein Konto – Wingcast", "en": "Your account – Wingcast"},
    "account.eyebrow": {"de": "Konto & Wingcast", "en": "Account & Wingcast"},
    "account.heading": {"de": "Deine Einstellungen", "en": "Your settings"},
    # Reaktivieren (abgemeldet)
    "account.reactivate_label": {"de": "Wingcast pausiert", "en": "Wingcast paused"},
    "account.reactivate_text_html": {"de": "Du bist aktuell <strong>abgemeldet</strong> &mdash; es wird kein Wingcast verschickt. Deine Einstellungen sind aber noch da. Klick zum Reaktivieren:",
                                     "en": "You are currently <strong>unsubscribed</strong> &mdash; no Wingcast is being sent. Your settings are still here, though. Click to reactivate:"},
    "account.reactivate_btn": {"de": "Wingcast wieder aktivieren", "en": "Reactivate Wingcast"},
    # Onboarding (eingeloggt, noch kein Abo)
    "account.onboarding_eyebrow": {"de": "Du bist eingeloggt &mdash; aber noch nicht abonniert",
                                   "en": "You're logged in &mdash; but not subscribed yet"},
    "account.onboarding_title": {"de": "Aktiviere deinen Wingcast", "en": "Activate your Wingcast"},
    "account.onboarding_lead": {"de": "Flugwetter für deine Regionen direkt ins Postfach &mdash; an deinen Wunschtagen, kostenlos.",
                                "en": "Flight weather for your regions straight to your inbox &mdash; on the days you choose, free."},
    "account.onboarding_step1": {"de": "Regionen wählen", "en": "Choose regions"},
    "account.onboarding_step2": {"de": "Versandtage festlegen", "en": "Set delivery days"},
    "account.onboarding_step3": {"de": "Speichern &mdash; fertig", "en": "Save &mdash; done"},
    "account.onboarding_cta": {"de": "Wingcast jetzt abonnieren", "en": "Subscribe to Wingcast now"},
    # Status-Karte
    "account.status": {"de": "Status", "en": "Status"},
    "account.pill_no_sub": {"de": "Kein Abo", "en": "No subscription"},
    "account.pill_no_sub_title": {"de": "Account existiert, aber noch nicht abonniert",
                                  "en": "Account exists but not subscribed yet"},
    "account.status_active": {"de": "Aktiv", "en": "Active"},
    "account.status_paused": {"de": "Pausiert", "en": "Paused"},
    "account.status_paused_until": {"de": " bis ", "en": " until "},
    "account.status_pending": {"de": "Nicht bestätigt", "en": "Not confirmed"},
    "account.status_unsubscribed": {"de": "Abgemeldet", "en": "Unsubscribed"},
    "account.level": {"de": "Level", "en": "Level"},
    "account.level_beginner": {"de": "Anfänger", "en": "Beginner"},
    "account.level_expert": {"de": "Profi", "en": "Expert"},
    "account.level_standard": {"de": "Standard", "en": "Standard"},
    # Regionen
    "account.regions_hint": {"de": "Wähle die Regionen, für die du den Wingcast erhalten willst — per Chip oder Klick auf der Karte.",
                             "en": "Choose the regions you want the Wingcast for — via chip or by clicking on the map."},
    "account.regions_all": {"de": "Alle", "en": "All"},
    "account.regions_all_title": {"de": "Alle Regionen auswählen / abwählen", "en": "Select / deselect all regions"},
    "account.map_toggle": {"de": "Karte ein/aus", "en": "Toggle map"},
    # Qualität
    "account.quality_label": {"de": "Qualität", "en": "Quality"},
    "account.quality_hint": {"de": "Welche Spot-Stufen sollen im Wingcast erscheinen?",
                             "en": "Which spot tiers should appear in the Wingcast?"},
    "account.quality_tiers_aria": {"de": "Qualitäts-Tiers", "en": "Quality tiers"},
    "account.tier_violet_label": {"de": "XC-Tag", "en": "XC day"},
    "account.tier_violet_hint": {"de": "Strecken-/Top-Tage (Rating 5)", "en": "Cross-country / top days (rating 5)"},
    "account.tier_green_label": {"de": "Thermikflug", "en": "Thermal flight"},
    "account.tier_green_hint": {"de": "Solide bis starke Thermik (Rating 3–4)", "en": "Solid to strong thermals (rating 3–4)"},
    "account.tier_conditional_label": {"de": "Bedingt", "en": "Conditional"},
    "account.tier_conditional_hint": {"de": "Nur in bestimmten Fenstern", "en": "Only in certain windows"},
    "account.tier_gray_label": {"de": "Abgleiter", "en": "Sled run"},
    "account.tier_gray_hint": {"de": "Keine Thermik (Rating 1–2)", "en": "No thermals (rating 1–2)"},
    # Mindest-Rating
    "account.min_rating_label": {"de": "Mindest-Rating", "en": "Minimum rating"},
    "account.min_rating_hint": {"de": "Spots unter diesem Rating bleiben aus dem Wingcast.",
                                "en": "Spots below this rating stay out of the Wingcast."},
    "account.min_rating_aria": {"de": "Minimales Rating", "en": "Minimum rating"},
    "account.min_rating_all": {"de": "alle", "en": "all"},
    # Versandtage
    "account.weekdays_label": {"de": "Versandtage", "en": "Delivery days"},
    "account.weekdays_hint": {"de": "An welchen Wochentagen willst du den Wingcast bekommen?",
                              "en": "On which weekdays do you want to receive the Wingcast?"},
    "account.weekdays_aria": {"de": "Wochentage", "en": "Weekdays"},
    "account.wd_mon": {"de": "Mo", "en": "Mon"},
    "account.wd_tue": {"de": "Di", "en": "Tue"},
    "account.wd_wed": {"de": "Mi", "en": "Wed"},
    "account.wd_thu": {"de": "Do", "en": "Thu"},
    "account.wd_fri": {"de": "Fr", "en": "Fri"},
    "account.wd_sat": {"de": "Sa", "en": "Sat"},
    "account.wd_sun": {"de": "So", "en": "Sun"},
    # Pause
    "account.pause_label": {"de": "Pause", "en": "Pause"},
    "account.pause_hint": {"de": "Definiere einen Zeitraum, in dem kein Wingcast verschickt wird.",
                           "en": "Define a period during which no Wingcast is sent."},
    "account.pause_current_label": {"de": "Aktuell:", "en": "Currently:"},
    "account.pause_to": {"de": "bis", "en": "to"},
    "account.pause_both_empty": {"de": "Beide Felder leer = keine Pause.", "en": "Both fields empty = no pause."},
    "account.pause_placeholder": {"de": "Klicken um Zeitraum zu waehlen", "en": "Click to choose a period"},
    "account.pause_winter": {"de": "Winterpause (Nov &ndash; Feb)", "en": "Winter break (Nov &ndash; Feb)"},
    "account.pause_clear": {"de": "Pause entfernen", "en": "Remove pause"},
    "account.pause_clear_aria": {"de": "Pause aufheben", "en": "Clear pause"},
    # Speichern
    "account.save_subscribe": {"de": "Wingcast abonnieren", "en": "Subscribe to Wingcast"},
    "account.save_settings": {"de": "Einstellungen speichern", "en": "Save settings"},
    # Abmelden
    "account.unsub_label": {"de": "Wingcast abmelden", "en": "Unsubscribe from Wingcast"},
    "account.unsub_hint_html": {"de": "Stoppt den Versand &mdash; <strong>dein Account und alle Einstellungen bleiben erhalten</strong>. Du kannst dich jederzeit wieder einloggen und mit einem Klick reaktivieren.<br><br><em>Nur kurzfristig weg?</em> Nutze stattdessen die <strong>Pause</strong>-Funktion oben mit Datum.",
                               "en": "Stops delivery &mdash; <strong>your account and all settings are kept</strong>. You can log back in any time and reactivate with one click.<br><br><em>Only away briefly?</em> Use the <strong>pause</strong> function above with a date instead."},
    # Feedback
    "account.feedback_label": {"de": "Feedback & Wünsche", "en": "Feedback & wishes"},
    "account.feedback_hint_html": {"de": "Was funktioniert gut, was nervt, was würdest du verbessern? Sag's mir &mdash; ich lese jede Nachricht. <strong>Kein E-Mail-Versand</strong>, geht direkt an mich.",
                                   "en": "What works well, what's annoying, what would you improve? Tell me &mdash; I read every message. <strong>No email is sent</strong>, it goes straight to me."},
    "account.feedback_placeholder": {"de": "Was würdest du dir wünschen? Was funktioniert nicht?",
                                     "en": "What would you wish for? What isn't working?"},
    "account.feedback_btn": {"de": "Feedback senden", "en": "Send feedback"},
    # Export
    "account.export_label": {"de": "Meine Daten exportieren", "en": "Export my data"},
    "account.export_hint": {"de": "Lade alle zu deinem Konto gespeicherten Daten als JSON herunter (DSG Art. 28 Datenübertragbarkeit).",
                            "en": "Download all data stored for your account as JSON (FADP Art. 28 data portability)."},
    "account.export_btn": {"de": "JSON-Export", "en": "JSON export"},
    # Account löschen
    "account.delete_summary": {"de": "Account löschen", "en": "Delete account"},
    "account.delete_hint_html": {"de": "Alle deine Daten (E-Mail, Einstellungen, Feedback-Historie) werden <strong>unwiderruflich</strong> aus der Datenbank gelöscht. Du müsstest dich anschliessend wieder neu registrieren.",
                                 "en": "All your data (email, settings, feedback history) will be <strong>permanently</strong> deleted from the database. You would then have to register again."},
    "account.delete_confirm": {"de": "Account WIRKLICH endgueltig loeschen? Alle Daten werden aus der Datenbank entfernt. Nicht rueckgaengig zu machen.",
                               "en": "Permanently delete your account? All data will be removed from the database. This cannot be undone."},
    "account.delete_btn": {"de": "Account endgültig löschen", "en": "Delete account permanently"},

    # ======================= subscribe.html =======================
    "subscribe.title": {"de": "Wingcast abonnieren", "en": "Subscribe to Wingcast"},
    "subscribe.eyebrow": {"de": "E-Mail-Wingcast", "en": "Email Wingcast"},
    "subscribe.heading": {"de": "Dein Flugwetter in 3 E-Mails pro Woche",
                          "en": "Your flight weather in 3 emails a week"},
    "subscribe.lead": {"de": "Schluss mit 5 Apps checken. Montag, Mittwoch, Freitag — du weisst wann, wo und warum.",
                       "en": "No more checking 5 apps. Monday, Wednesday, Friday — you know when, where and why."},
    "subscribe.proof_aria": {"de": "Produkt-Kennzahlen", "en": "Product metrics"},
    "subscribe.proof_sites": {"de": "488 Startplätze", "en": "488 launch sites"},
    "subscribe.proof_models": {"de": "5 Wettermodelle", "en": "5 weather models"},
    "subscribe.proof_free": {"de": "Gratis im MVP", "en": "Free during MVP"},
    "subscribe.preview_link": {"de": "So sieht der Wingcast aus", "en": "See what the Wingcast looks like"},
    "subscribe.email_label": {"de": "Deine E-Mail-Adresse", "en": "Your email address"},
    "subscribe.email_placeholder": {"de": "pilot@example.ch", "en": "pilot@example.com"},
    "subscribe.regions_legend": {"de": "Deine Regionen", "en": "Your regions"},
    "subscribe.regions_hint": {"de": "Wähle die Regionen, für die du den Wingcast erhalten willst. Mehrfachauswahl möglich — per Chip oder direkt auf der Karte.",
                               "en": "Choose the regions you want the Wingcast for. Multiple selection possible — via chip or directly on the map."},
    "subscribe.submit": {"de": "Kostenlos abonnieren", "en": "Subscribe for free"},
    "subscribe.foot_html": {"de": "Mit dem Abonnieren erhältst du eine Bestätigungs-E-Mail.<br>Du kannst dich jederzeit mit einem Klick abmelden.",
                            "en": "On subscribing you'll receive a confirmation email.<br>You can unsubscribe any time with one click."},

    # ======================= synoptik.html =======================
    "synoptik.title": {"de": "Synoptik – Wingcast", "en": "Synoptic – Wingcast"},
    "synoptik.heading": {"de": "Synoptische Analyse", "en": "Synoptic analysis"},
    "synoptik.subtitle": {"de": "Bodendruck, Isobaren und Druckzentren über Europa",
                          "en": "Surface pressure, isobars and pressure centres over Europe"},
    "synoptik.loading": {"de": "wird geladen…", "en": "loading…"},
    "synoptik.refresh": {"de": "Aktualisieren", "en": "Refresh"},
    "synoptik.day_tabs_aria": {"de": "Tagesauswahl", "en": "Day selection"},
    "synoptik.time_chips_aria": {"de": "Uhrzeit (UTC)", "en": "Time (UTC)"},

    # ======================= briefing.html =======================
    "briefing.title": {"de": "Flugwetter – Wingcast", "en": "Flight weather – Wingcast"},
    "briefing.og_title": {"de": "Wingcast – Flugwetter", "en": "Wingcast – Flight weather"},
    "briefing.heading": {"de": "Flugwetter", "en": "Flight weather"},
    "briefing.loading": {"de": "wird geladen…", "en": "loading…"},
    "briefing.refresh": {"de": "Aktualisieren", "en": "Refresh"},
    "briefing.day_tabs_aria": {"de": "Tagesauswahl", "en": "Day selection"},
    "briefing.region_label": {"de": "Region", "en": "Region"},
    "briefing.map_toggle_aria": {"de": "Regionskarte ein- oder ausblenden", "en": "Show or hide region map"},
    "briefing.safety_label": {"de": "Sicherheit", "en": "Safety"},
    "briefing.safety_title": {"de": "Zeigt nur Spots des gewaehlten Sicherheits-Bandes (RATING_CONCEPT v1.3)",
                              "en": "Shows only spots in the selected safety band (RATING_CONCEPT v1.3)"},
    "briefing.safety_filter_aria": {"de": "Filter nach Sicherheits-Band", "en": "Filter by safety band"},
    "briefing.flyability_label": {"de": "ab Fliegbarkeit", "en": "from flyability"},
    "briefing.flyability_title": {"de": "Blendet Spots unter diesem Fliegbarkeits-Rating aus",
                                  "en": "Hides spots below this flyability rating"},
    "briefing.flyability_aria": {"de": "Minimale Fliegbarkeit", "en": "Minimum flyability"},
    "briefing.footer": {"de": "ICON-D2/EU/CH1/CH2 + GFS via Open-Meteo · winds.mobi · Wingcast-KI",
                        "en": "ICON-D2/EU/CH1/CH2 + GFS via Open-Meteo · winds.mobi · Wingcast AI"},

    # ======================= login.html =======================
    "login.page_title": {"de": "Login – Wingcast", "en": "Log in – Wingcast"},
    "login.subtitle": {"de": "Per Magic-Link &mdash; ganz ohne Passwort",
                       "en": "Via magic link &mdash; no password needed"},
    "login.email_card_label": {"de": "E-Mail-Adresse", "en": "Email address"},
    "login.card_hint": {"de": "Du bekommst einen einmaligen Login-Link per Mail. Funktioniert nur wenn du bereits ein Wingcast-Abo hast.",
                        "en": "You'll get a one-time login link by email. Only works if you already have a Wingcast subscription."},
    "login.email_short_label": {"de": "E-Mail", "en": "Email"},
    "login.send_link": {"de": "Login-Link schicken", "en": "Send login link"},

    # ======================= login_confirm.html =======================
    "login_confirm.title": {"de": "Anmeldung laeuft...", "en": "Logging you in..."},
    "login_confirm.hint": {"de": "Du wirst gleich eingeloggt.", "en": "You'll be logged in shortly."},
    "login_confirm.noscript": {"de": "JavaScript ist deaktiviert. Bitte klicke zum Einloggen:",
                               "en": "JavaScript is disabled. Please click to log in:"},

    # ======================= subscribe_status.html =======================
    "subscribe_status.back_to_login": {"de": "Zur Anmeldung", "en": "To login"},

    # ======================= E-Mails: geteilt =======================
    "email.greeting_hi": {"de": "Hallo", "en": "Hi"},
    "email.button_fallback": {"de": "Button funktioniert nicht? Kopiere diesen Link in deinen Browser:",
                              "en": "Button not working? Copy this link into your browser:"},
    "email.unsubscribe_link": {"de": "Abmelden", "en": "Unsubscribe"},
    "email.in_doubt": {"de": "Im Zweifel: nicht fliegen.", "en": "When in doubt: don't fly."},
    "email.settings_adjust_cta": {"de": "Einstellungen anpassen", "en": "Adjust settings"},
    # .txt-Label-Zeilen (mit Doppelpunkt, fixe Spaltenbreite im Template)
    "email.txt_privacy_label": {"de": "Datenschutz:", "en": "Privacy:"},
    "email.txt_imprint_label": {"de": "Impressum:", "en": "Imprint:"},
    "email.txt_settings_label": {"de": "Einstellungen:", "en": "Settings:"},
    "email.txt_account_label": {"de": "Abmelden:", "en": "Unsubscribe:"},

    # ======================= E-Mail: confirm =======================
    "email.confirm.title": {"de": "Bestaetige dein Wingcast-Abo", "en": "Confirm your Wingcast subscription"},
    "email.confirm.preheader": {"de": "Klicke auf den Button, um dein Flugwetter-Abo zu aktivieren.",
                                "en": "Click the button to activate your flight-weather subscription."},
    "email.confirm.h1": {"de": "Fast geschafft!", "en": "Almost there!"},
    "email.confirm.body": {"de": "bitte bestaetige deine E-Mail-Adresse, um dein kostenloses Flugwetter-Abo zu aktivieren. Du bekommst ab sofort an deinen gewaehlten Wochentagen morgens einen personalisierten Wingcast.",
                           "en": "please confirm your email address to activate your free flight-weather subscription. From now on you'll get a personalised Wingcast each morning on your chosen weekdays."},
    "email.confirm.cta": {"de": "Abo bestaetigen", "en": "Confirm subscription"},
    "email.confirm.footer_note": {"de": "Du hast dieses Abo nicht angefordert? Dann ignoriere diese E-Mail einfach &mdash; ohne Bestaetigung wird nichts aktiviert.",
                                  "en": "Didn't request this subscription? Just ignore this email &mdash; nothing is activated without confirmation."},
    "email.confirm.txt_header": {"de": "WINGCAST — Bestaetige dein Abo", "en": "WINGCAST — Confirm your subscription"},
    "email.confirm.txt_body1": {"de": "bitte bestaetige deine E-Mail-Adresse, um dein kostenloses Flugwetter-Abo zu aktivieren.",
                                "en": "please confirm your email address to activate your free flight-weather subscription."},
    "email.confirm.txt_link_label": {"de": "Link zum Bestaetigen:", "en": "Confirmation link:"},
    "email.confirm.txt_body2": {"de": "Nach der Bestaetigung bekommst du an deinen gewaehlten Wochentagen morgens einen personalisierten Wingcast mit den besten Flugtagen fuer deine Regionen.",
                                "en": "After confirming, you'll get a personalised Wingcast each morning on your chosen weekdays, with the best flying days for your regions."},
    "email.confirm.txt_footer_note": {"de": "Du hast dieses Abo nicht angefordert? Dann ignoriere diese E-Mail einfach — ohne Bestaetigung wird nichts aktiviert.",
                                      "en": "Didn't request this subscription? Just ignore this email — nothing is activated without confirmation."},

    # ======================= E-Mail: login =======================
    "email.login.title": {"de": "Dein Wingcast Login-Link", "en": "Your Wingcast login link"},
    "email.login.preheader": {"de": "Einmaliger Login-Link fuer dein Wingcast-Konto. 30 Minuten gueltig.",
                              "en": "One-time login link for your Wingcast account. Valid for 30 minutes."},
    "email.login.h1": {"de": "Dein Login-Link", "en": "Your login link"},
    "email.login.body": {"de": "klicke auf den Button, um dich einzuloggen. Der Link ist <strong>30 Minuten</strong> gueltig und kann nur einmal verwendet werden.",
                         "en": "click the button to log in. The link is valid for <strong>30 minutes</strong> and can only be used once."},
    "email.login.footer_note": {"de": "Du hast keinen Login angefordert? Dann ignoriere diese E-Mail einfach. Niemand kann sich ohne diesen Link in dein Konto einloggen.",
                                "en": "Didn't request a login? Just ignore this email. No one can log into your account without this link."},
    "email.login.txt_body": {"de": "dein Login-Link fuer Wingcast:", "en": "your login link for Wingcast:"},
    "email.login.txt_validity": {"de": "Der Link ist 30 Minuten gueltig und kann nur einmal verwendet werden.",
                                 "en": "The link is valid for 30 minutes and can only be used once."},
    "email.login.txt_footer_note": {"de": "Du hast keinen Login angefordert? Dann ignoriere diese E-Mail einfach.",
                                    "en": "Didn't request a login? Just ignore this email."},

    # ======================= E-Mail: welcome =======================
    "email.welcome.title": {"de": "Willkommen bei Wingcast", "en": "Welcome to Wingcast"},
    "email.welcome.preheader": {"de": "Dein Abo ist aktiv. Dein erster Wingcast kommt am naechsten von dir gewaehlten Versandtag.",
                                "en": "Your subscription is active. Your first Wingcast arrives on your next chosen delivery day."},
    "email.welcome.h1": {"de": "Willkommen an Bord!", "en": "Welcome aboard!"},
    "email.welcome.body": {"de": "Dein Abo ist aktiv. Ab jetzt bekommst du an deinen Wunschtagen um 06:30 einen Wingcast mit den besten Flugtagen fuer deine Regionen. Standardmaessig taeglich &mdash; pro Wochentag steuerbar in deinen Einstellungen.",
                           "en": "Your subscription is active. From now on you'll get a Wingcast at 06:30 on your chosen days, with the best flying days for your regions. Daily by default &mdash; adjustable per weekday in your settings."},
    "email.welcome.regions_label": {"de": "Regionen:", "en": "Regions:"},
    "email.welcome.expect_h2": {"de": "Was du erwarten kannst", "en": "What to expect"},
    "email.welcome.bullet1": {"de": "5-Tage-Vorhersage mit Ampel pro Tag", "en": "5-day forecast with a traffic light per day"},
    "email.welcome.bullet2": {"de": "Top-Startplaetze in deinen Regionen, nach Rating sortiert",
                              "en": "Top launch sites in your regions, sorted by rating"},
    "email.welcome.bullet3": {"de": "Warum-Erklaerung: Sicherheit zuerst, dann Fliegbarkeit",
                              "en": "A why explanation: safety first, then flyability"},
    "email.welcome.bullet4": {"de": "Foehn- und Gewitter-Warnungen, sobald relevant",
                              "en": "Foehn and thunderstorm warnings whenever relevant"},
    "email.welcome.next_label": {"de": "Naechster Wingcast:", "en": "Next Wingcast:"},
    "email.welcome.next_value": {"de": "naechster Versandtag, 06:30", "en": "next delivery day, 06:30"},
    "email.welcome.settings_card_title": {"de": "Einstellungen jederzeit anpassen", "en": "Adjust your settings any time"},
    "email.welcome.settings_card_body": {"de": "Regionen wechseln, Versandtage waehlen oder pausieren &mdash; alles ueber einen einzigen Link in jedem Wingcast.",
                                         "en": "Change regions, choose delivery days or pause &mdash; all via a single link in every Wingcast."},
    "email.welcome.settings_card_cta": {"de": "Einstellungen oeffnen", "en": "Open settings"},
    "email.welcome.disclaimer": {"de": "Wingcast ist Decision Support &mdash; die finale Entscheidung triffst du. Im Zweifel: nicht fliegen. Sicherheit geht vor.",
                                 "en": "Wingcast is decision support &mdash; the final decision is yours. When in doubt: don't fly. Safety comes first."},
    "email.welcome.txt_header": {"de": "WINGCAST — Willkommen an Bord!", "en": "WINGCAST — Welcome aboard!"},
    "email.welcome.txt_body": {"de": "Dein Abo ist aktiv. Ab jetzt bekommst du an deinen Wunschtagen um 06:30 einen Wingcast mit den besten Flugtagen fuer deine Regionen. Standardmaessig taeglich — pro Wochentag steuerbar in den Einstellungen.",
                               "en": "Your subscription is active. From now on you'll get a Wingcast at 06:30 on your chosen days, with the best flying days for your regions. Daily by default — adjustable per weekday in your settings."},
    "email.welcome.txt_settings_header": {"de": "DEINE EINSTELLUNGEN", "en": "YOUR SETTINGS"},
    "email.welcome.txt_expect_header": {"de": "WAS DU ERWARTEN KANNST", "en": "WHAT TO EXPECT"},
    "email.welcome.txt_settings_cta_header": {"de": "EINSTELLUNGEN ANPASSEN", "en": "ADJUST SETTINGS"},
    "email.welcome.txt_settings_cta_body": {"de": "Regionen wechseln, Versandtage waehlen oder pausieren — alles ueber einen einzigen Link in jedem Wingcast:",
                                            "en": "Change regions, choose delivery days or pause — all via a single link in every Wingcast:"},
    "email.welcome.txt_disclaimer": {"de": "Wingcast ist Decision Support — die finale Entscheidung triffst du. Im Zweifel: nicht fliegen.",
                                     "en": "Wingcast is decision support — the final decision is yours. When in doubt: don't fly."},

    # ======================= E-Mail: accuracy =======================
    "email.accuracy.title": {"de": "Deine Vorhersage-Genauigkeit", "en": "Your forecast accuracy"},
    "email.accuracy.preheader_pre": {"de": "Deine Wingcast-Vorhersage war letzten Monat zu ",
                                     "en": "Last month your Wingcast forecast was "},
    "email.accuracy.preheader_post": {"de": "% korrekt.", "en": "% correct."},
    "email.accuracy.review": {"de": "Monatsrueckblick", "en": "Monthly review"},
    "email.accuracy.hero_pre": {"de": "Deine Prognose war zu", "en": "Your forecast was"},
    "email.accuracy.hero_post": {"de": "richtig.", "en": "correct."},
    "email.accuracy.based_on_pre": {"de": "Basierend auf", "en": "Based on"},
    "email.accuracy.based_on_mid": {"de": "Feedbacks von dir in den letzten",
                                    "en": "pieces of feedback from you over the past"},
    "email.accuracy.based_on_post": {"de": "Tagen:", "en": "days:"},
    "email.accuracy.times_correct": {"de": "mal passte die Vorhersage", "en": "times the forecast was right"},
    "email.accuracy.times_wrong": {"de": "mal lag sie daneben", "en": "times it was off"},
    "email.accuracy.disclaimer_html": {"de": "Wingcast ist Decision Support &mdash; die finale Entscheidung triffst du. Im Zweifel: nicht fliegen.",
                                       "en": "Wingcast is decision support &mdash; the final decision is yours. When in doubt: don't fly."},
    "email.accuracy.txt_header": {"de": "WINGCAST — Monatsrueckblick", "en": "WINGCAST — Monthly review"},
    "email.accuracy.txt_based_mid": {"de": "Feedbacks der letzten", "en": "pieces of feedback over the past"},
    "email.accuracy.txt_based_post": {"de": "Tage:", "en": "days:"},
    "email.accuracy.txt_disclaimer": {"de": "Wingcast ist Decision Support — die finale Entscheidung triffst du. Im Zweifel: nicht fliegen.",
                                      "en": "Wingcast is decision support — the final decision is yours. When in doubt: don't fly."},

    # ======================= E-Mail: briefing =======================
    "email.briefing.week_abbr": {"de": "KW", "en": "CW"},
    "email.briefing.preheader_fallback": {"de": "Dein Flugwetter-Wingcast", "en": "Your flight-weather Wingcast"},
    "email.briefing.best_day": {"de": "Bester Tag", "en": "Best day"},
    "email.briefing.week_word": {"de": "Woche", "en": "Week"},
    "email.briefing.regions_word": {"de": "Regionen", "en": "regions"},
    "email.briefing.days_word": {"de": "Tage", "en": "days"},
    "email.briefing.today": {"de": "heute", "en": "today"},
    "email.briefing.best_col": {"de": "Beste", "en": "Best"},
    "email.briefing.per_day": {"de": "Pro Tag", "en": "Per day"},
    "email.briefing.per_day_sub": {"de": "Beste Region + Top-Spots", "en": "Best region + top spots"},
    "email.briefing.nothing_flyable": {"de": "Nichts fliegbar in deinen Regionen.", "en": "Nothing flyable in your regions."},
    "email.briefing.feedback_q": {"de": "War diese Vorhersage richtig?", "en": "Was this forecast right?"},
    "email.briefing.feedback_yes": {"de": "Ja, passte", "en": "Yes, it fit"},
    "email.briefing.feedback_no": {"de": "Nein, lag daneben", "en": "No, it was off"},
    "email.briefing.adjust_title": {"de": "Wingcast anpassen", "en": "Adjust Wingcast"},
    "email.briefing.adjust_sub": {"de": "Andere Regionen, weniger Tage, pausieren?", "en": "Different regions, fewer days, pause?"},
    "email.briefing.sources_label": {"de": "Quellen:", "en": "Sources:"},
    "email.briefing.disclaimer_short_html": {"de": "Wingcast ist Decision Support &mdash; im Zweifel: nicht fliegen.",
                                             "en": "Wingcast is decision support &mdash; when in doubt: don't fly."},
    "email.briefing.txt_header": {"de": "Dein Flugwetter", "en": "Your flight weather"},
    "email.briefing.txt_in_dashboard": {"de": "Im Dashboard:", "en": "On the dashboard:"},
    "email.briefing.txt_share_whatsapp": {"de": "Per WhatsApp teilen:", "en": "Share via WhatsApp:"},
    "email.briefing.txt_regions_header": {"de": "DEINE REGIONEN · DIESE WOCHE", "en": "YOUR REGIONS · THIS WEEK"},
    "email.briefing.txt_legend": {"de": 'Legende: Zahl = Regions-Rating · "!" = Vorsicht · "x" = nicht sicher · "----" = keine Daten',
                                  "en": 'Legend: number = region rating · "!" = caution · "x" = not safe · "----" = no data'},
    "email.briefing.txt_week_glance": {"de": "DIESE WOCHE AUF EINEN BLICK", "en": "THIS WEEK AT A GLANCE"},
    "email.briefing.txt_caution": {"de": "VORSICHT", "en": "CAUTION"},
    "email.briefing.txt_not_flyable": {"de": "NICHT FLIEGBAR", "en": "NOT FLYABLE"},
    "email.briefing.txt_ok": {"de": "OK", "en": "OK"},
    "email.briefing.txt_per_day": {"de": "PRO TAG", "en": "PER DAY"},
    "email.briefing.txt_yes": {"de": "Ja:", "en": "Yes:"},
    "email.briefing.txt_no": {"de": "Nein:", "en": "No:"},
    "email.briefing.txt_adjust_sub": {"de": "Andere Regionen, weniger Versandtage oder pausieren?",
                                      "en": "Different regions, fewer delivery days, or pause?"},
    "email.briefing.txt_sources": {"de": "Quellen: ICON-CH1 (1 km), ICON-D2, ICON-EU, Open-Meteo.",
                                   "en": "Sources: ICON-CH1 (1 km), ICON-D2, ICON-EU, Open-Meteo."},
    "email.briefing.txt_disclaimer": {"de": "Wingcast ist Decision Support — du entscheidest.",
                                      "en": "Wingcast is decision support — you decide."},

    # ======================= E-Mail-Betreffzeilen (serverseitig) =======================
    # confirm/login/welcome nutzen ihre title-Keys (gleicher Wortlaut).
    "email.briefing.subject_conditional": {"de": "Bedingte Woche", "en": "Conditional week"},
    "email.briefing.subject_nothing": {"de": "Diese Woche nichts in deinen Regionen",
                                        "en": "Nothing in your regions this week"},
    "email.accuracy.subject": {"de": "Wingcast {month}: Deine Vorhersage zu {pct}% korrekt",
                               "en": "Wingcast {month}: your forecast was {pct}% correct"},

    # ======================= Tier-Labels (serverseitig, E-Mail/Briefing) =======================
    # DE exakt wie _TIER_META in email_service.py (validierte Anzeige unangetastet).
    "tier.violet": {"de": "Top-Tag", "en": "Top day"},
    "tier.green": {"de": "Sicher", "en": "Safe"},
    "tier.conditional": {"de": "Vorsicht", "en": "Caution"},
    "tier.gray": {"de": "Abgleiter", "en": "Sled run"},
    "tier.none": {"de": "Nicht fliegbar", "en": "Not flyable"},
    "tier.not_safe": {"de": "Nicht sicher", "en": "Not safe"},

    # ======================= Monatsnamen (serverseitig, accuracy-Mail) =======================
    "month.1": {"de": "Januar", "en": "January"},
    "month.2": {"de": "Februar", "en": "February"},
    "month.3": {"de": "Maerz", "en": "March"},
    "month.4": {"de": "April", "en": "April"},
    "month.5": {"de": "Mai", "en": "May"},
    "month.6": {"de": "Juni", "en": "June"},
    "month.7": {"de": "Juli", "en": "July"},
    "month.8": {"de": "August", "en": "August"},
    "month.9": {"de": "September", "en": "September"},
    "month.10": {"de": "Oktober", "en": "October"},
    "month.11": {"de": "November", "en": "November"},
    "month.12": {"de": "Dezember", "en": "December"},

    # ======================= Verdict-Headlines (serverseitig, Fallback wenn kein LLM-Headline) =======================
    "email.briefing.hl_violet_spot": {"de": "{weekday} ist dein Tag — {spot} ist Top",
                                       "en": "{weekday} is your day — {spot} is top"},
    "email.briefing.hl_violet": {"de": "{weekday} wird ein Top-Tag", "en": "{weekday} will be a top day"},
    "email.briefing.hl_green_spot": {"de": "Bester Tag: {weekday} — {spot} sicher fliegbar",
                                     "en": "Best day: {weekday} — {spot} safely flyable"},
    "email.briefing.hl_green": {"de": "{weekday} ist sicher fliegbar", "en": "{weekday} is safely flyable"},
    "email.briefing.hl_cond_spot": {"de": "{weekday} mit Vorsicht — {spot}", "en": "{weekday} with caution — {spot}"},
    "email.briefing.hl_cond": {"de": "{weekday} nur mit Vorsicht", "en": "{weekday} only with caution"},
    "email.briefing.hls_violet": {"de": "Top-Bedingungen erwartet", "en": "Top conditions expected"},
    "email.briefing.hls_green": {"de": "Solide Thermik", "en": "Solid thermals"},
    "email.briefing.hls_cond": {"de": "Nur mit Vorsicht fliegbar", "en": "Flyable only with caution"},
    "email.briefing.hls_violet_base": {"de": "{base} — Top", "en": "{base} — top"},
    "email.briefing.hls_cond_base": {"de": "{base} — mit Vorsicht", "en": "{base} — with caution"},

    # ======================= Wochen-Zusammenfassung (week_lead-Fallback) =======================
    "ws.grounded": {"de": "Diese Woche bleib am Boden — kein fliegbarer Tag in deinen Regionen.",
                    "en": "Stay grounded this week — no flyable day in your regions."},
    "ws.no_top": {"de": "Keine Top-Bedingungen, nur bedingt fliegbar.",
                  "en": "No top conditions, only conditionally flyable."},
    "ws.one_strong": {"de": "{weekday} ist dein Tag der Woche.", "en": "{weekday} is your day of the week."},
    "ws.few_strong": {"de": "{n} starke Tage: {days}.", "en": "{n} strong days: {days}."},
    "ws.many_strong": {"de": "{n} starke Tage diese Woche.", "en": "{n} strong days this week."},
    "ws.warn_days": {"de": "{label} an {days} — meiden.", "en": "{label} on {days} — avoid."},
    "ws.warn_coming": {"de": "{label} aufziehend — meiden.", "en": "{label} building — avoid."},
    "ws.none_days": {"de": "{days} nichts fliegbar.", "en": "{days} nothing flyable."},

    # Phaenomen-/Safety-Labels (DE exakt wie _SAFETY_KEYWORDS in email_service.py)
    "phenom.thunderstorm": {"de": "Gewitter", "en": "Thunderstorm"},
    "phenom.foehn": {"de": "Föhn", "en": "Foehn"},
    "phenom.storm": {"de": "Sturm", "en": "Storm"},
    "phenom.shear": {"de": "Windscherung", "en": "Wind shear"},

    # ======================= Accuracy-Framing (serverseitig) =======================
    "email.accuracy.msg_high": {"de": "Sehr gute Trefferquote! Die Modell-Kombination scheint fuer deine Regionen gut kalibriert zu sein. Danke fuer dein Feedback — das hilft uns, die Prognose weiter zu schaerfen.",
                                "en": "Great hit rate! The model combination seems well calibrated for your regions. Thanks for your feedback — it helps us sharpen the forecast further."},
    "email.accuracy.msg_mid": {"de": "Solide Trefferquote. Es gibt noch Luft nach oben — oft liegen Abweichungen an lokalen Effekten, die selbst die besten Modelle nicht vollstaendig erfassen. Dein Feedback hilft uns dabei.",
                               "en": "Solid hit rate. There's still room for improvement — deviations often come from local effects that even the best models can't fully capture. Your feedback helps us with that."},
    "email.accuracy.msg_low": {"de": "Die Vorhersage hat dir letzten Monat oft nicht gepasst. Das tut uns leid. Vielleicht sind die gewaehlten Regionen fuer dein Home-Terrain zu grob — du kannst sie in den Einstellungen anpassen.",
                               "en": "The forecast often didn't match for you last month. We're sorry about that. Maybe the chosen regions are too coarse for your home terrain — you can adjust them in your settings."},

    # ======================= Chat-Tool-Narration (user-facing Stream) =======================
    "chat.tool.geocode": {"de": "Ich suche den Standort „{q}“…", "en": "Searching for the location “{q}”…"},
    "chat.tool.geocode_noarg": {"de": "Ich suche den Standort…", "en": "Searching for the location…"},
    "chat.tool.find_spots": {"de": "Ich suche erreichbare Spots im Umkreis von {mins} Min…",
                             "en": "Searching for reachable spots within {mins} min…"},
    "chat.tool.find_spots_noarg": {"de": "Ich suche erreichbare Spots…", "en": "Searching for reachable spots…"},
    "chat.tool.clear_map": {"de": "Ich räume die Karte auf…", "en": "Clearing the map…"},
    "chat.tool.spot_analysis": {"de": "Ich schaue mir die Einschätzung für {spot} genauer an…",
                                "en": "Taking a closer look at the assessment for {spot}…"},
    "chat.tool.spot_analysis_noarg": {"de": "Ich schaue mir die Detail-Einschätzung an…",
                                      "en": "Taking a closer look at the detailed assessment…"},
    "chat.tool.spot_weather": {"de": "Ich hole die Wetterdaten für {spot}…",
                               "en": "Fetching the weather data for {spot}…"},
    "chat.tool.spot_weather_noarg": {"de": "Ich hole die Wetterdaten…", "en": "Fetching the weather data…"},
    "chat.tool.region_analysis": {"de": "Ich schaue mir die Großwetterlage im Gebiet {region} an…",
                                  "en": "Looking at the synoptic situation for the {region} area…"},
    "chat.tool.region_analysis_noarg": {"de": "Ich schaue mir die Großwetterlage an…",
                                        "en": "Looking at the synoptic situation…"},
    "chat.tool.region_weather": {"de": "Ich hole die Wetterdaten für das Gebiet {region}…",
                                 "en": "Fetching the weather data for the {region} area…"},
    "chat.tool.region_weather_noarg": {"de": "Ich hole die regionalen Wetterdaten…",
                                       "en": "Fetching the regional weather data…"},
    "chat.tool.default": {"de": "Einen Moment, ich schaue nach…", "en": "One moment, let me check…"},
    # Chat-Fehler (api_chat)
    "chat.err.no_message": {"de": "Keine Nachricht", "en": "No message"},
    "chat.err.empty_message": {"de": "Leere Nachricht", "en": "Empty message"},
    "chat.err.processing": {"de": "Entschuldigung, es gab einen Fehler bei der Verarbeitung: {error}",
                            "en": "Sorry, there was an error while processing: {error}"},
    "chat.loading_weather": {"de": "Wetterdaten werden geladen… Bitte versuche es gleich nochmal.",
                             "en": "Weather data is loading… Please try again in a moment."},
    "chat.loading_analyses": {"de": "Die Voranalysen werden gerade geladen… Bitte versuche es gleich nochmal.",
                              "en": "The pre-analyses are loading… Please try again in a moment."},

    # ======================= Flash-Messages (Account-/Login-Flow, user-facing) =======================
    "flash.service_unavailable": {"de": "Service nicht verfuegbar", "en": "Service unavailable"},
    "flash.pause_failed": {"de": "Pause fehlgeschlagen", "en": "Pause failed"},
    "flash.paused_until": {"de": "Pausiert bis {until}", "en": "Paused until {until}"},
    "flash.resume_failed": {"de": "Fortsetzen fehlgeschlagen", "en": "Resume failed"},
    "flash.sub_active_again": {"de": "Abo wieder aktiv", "en": "Subscription active again"},
    "flash.unsub_failed": {"de": "Abmelden fehlgeschlagen", "en": "Unsubscribe failed"},
    "flash.unsubscribed": {"de": "Wingcast abgemeldet", "en": "Unsubscribed from Wingcast"},
    "flash.need_region": {"de": "Mindestens eine Region waehlen", "en": "Choose at least one region"},
    "flash.need_weekday": {"de": "Mindestens einen Wochentag waehlen", "en": "Choose at least one weekday"},
    "flash.need_tier": {"de": "Mindestens eine Qualitaets-Stufe waehlen", "en": "Choose at least one quality tier"},
    "flash.save_failed": {"de": "Speichern fehlgeschlagen", "en": "Saving failed"},
    "flash.settings_saved": {"de": "Einstellungen gespeichert", "en": "Settings saved"},
    "flash.reactivate_failed": {"de": "Reaktivierung fehlgeschlagen", "en": "Reactivation failed"},
    "flash.reactivated": {"de": "Wingcast wieder aktiviert", "en": "Wingcast reactivated"},
    "flash.need_message": {"de": "Bitte eine Nachricht eingeben", "en": "Please enter a message"},
    "flash.feedback_save_failed": {"de": "Feedback konnte nicht gespeichert werden",
                                   "en": "Feedback could not be saved"},
    "flash.feedback_thanks": {"de": "Danke fuer dein Feedback!", "en": "Thanks for your feedback!"},
    "flash.account_not_found": {"de": "Account nicht gefunden", "en": "Account not found"},
    "flash.login_need_email": {"de": "Bitte E-Mail eingeben", "en": "Please enter your email"},

    # ======================= Status-Seiten (subscribe_status.html, serverseitig) =======================
    "status.service_unavail": {"de": "Der Service ist gerade nicht verfuegbar.",
                               "en": "The service is currently unavailable."},
    "status.service_unavail_retry": {"de": "Der Service ist gerade nicht verfuegbar. Bitte spaeter nochmal.",
                                     "en": "The service is currently unavailable. Please try again later."},
    "status.service_unavail_title": {"de": "Service nicht verfuegbar", "en": "Service unavailable"},
    "status.try_later": {"de": "Bitte spaeter nochmal versuchen.", "en": "Please try again later."},
    # Legacy subscribe (410 Gone)
    "status.gone_title": {"de": "Diese Anmeldung gibt es nicht mehr", "en": "This sign-up no longer exists"},
    "status.gone_msg": {"de": "Die Registrierung laeuft jetzt direkt ueber den Login.",
                        "en": "Registration now happens directly via login."},
    "status.gone_sub": {"de": "Gib deine E-Mail unter /login ein — beim ersten Klick wird dein Konto automatisch angelegt. Kein zusaetzlicher Schritt noetig.",
                        "en": "Enter your email at /login — your account is created automatically on the first click. No extra step needed."},
    # Confirm
    "status.confirm_fail_title": {"de": "Bestaetigung fehlgeschlagen", "en": "Confirmation failed"},
    "status.link_invalid_used_title": {"de": "Link ungueltig oder bereits verwendet",
                                       "en": "Link invalid or already used"},
    "status.link_invalid_used_msg": {"de": "Dieser Bestaetigungs-Link ist abgelaufen oder wurde bereits benutzt.",
                                     "en": "This confirmation link has expired or has already been used."},
    "status.sub_activated_title": {"de": "Abo aktiviert!", "en": "Subscription activated!"},
    "status.welcome_msg": {"de": "Willkommen bei Wingcast, {email}.", "en": "Welcome to Wingcast, {email}."},
    "status.first_wingcast_sub": {"de": "Dein erster Wingcast kommt am naechsten Montag, Mittwoch oder Freitag um 06:30.",
                                  "en": "Your first Wingcast arrives next Monday, Wednesday or Friday at 06:30."},
    # Feedback (One-Click aus Mail)
    "status.invalid_rating_title": {"de": "Ungueltige Bewertung", "en": "Invalid rating"},
    "status.invalid_link_msg": {"de": "Dieser Link ist ungueltig.", "en": "This link is invalid."},
    "status.feedback_fail_title": {"de": "Feedback fehlgeschlagen", "en": "Feedback failed"},
    "status.link_invalid_title": {"de": "Link ungueltig", "en": "Invalid link"},
    "status.feedback_link_invalid_msg": {"de": "Dieser Feedback-Link ist nicht (mehr) gueltig.",
                                         "en": "This feedback link is no longer valid."},
    "status.feedback_save_fail_msg": {"de": "Dein Feedback konnte nicht gespeichert werden. Versuch's spaeter nochmal.",
                                      "en": "Your feedback could not be saved. Please try again later."},
    "status.feedback_confirm_title": {"de": "Danke fuer die Bestaetigung!", "en": "Thanks for confirming!"},
    "status.feedback_confirm_msg": {"de": "Dein Feedback hilft uns, die Vorhersage zu verbessern.",
                                    "en": "Your feedback helps us improve the forecast."},
    "status.feedback_thanks_title": {"de": "Danke fuer dein Feedback!", "en": "Thanks for your feedback!"},
    "status.feedback_wrong_msg": {"de": "Schade, dass die Vorhersage nicht gepasst hat. Wir lernen daraus.",
                                  "en": "Sorry the forecast didn't fit. We're learning from it."},
    "status.feedback_wrong_sub": {"de": "Mehr Details kannst du uns gerne per E-Mail-Antwort schicken.",
                                  "en": "Feel free to send us more details by replying to the email."},
    # Account löschen / unbekannte Aktion
    "status.delete_fail_title": {"de": "Loeschen fehlgeschlagen", "en": "Deletion failed"},
    "status.delete_fail_msg": {"de": "Dein Account konnte nicht geloescht werden.",
                               "en": "Your account could not be deleted."},
    "status.account_deleted_title": {"de": "Account geloescht", "en": "Account deleted"},
    "status.account_deleted_msg": {"de": "Deine E-Mail und alle Daten wurden aus unserer Datenbank entfernt.",
                                   "en": "Your email and all data have been removed from our database."},
    "status.account_deleted_sub": {"de": "Du kannst dich jederzeit neu registrieren.",
                                   "en": "You can register again any time."},
    "status.unknown_action_title": {"de": "Unbekannte Aktion", "en": "Unknown action"},
    "status.unknown_action_msg": {"de": "Diese Aktion ist nicht erlaubt.", "en": "This action is not allowed."},
    # Login-Confirm
    "status.login_link_invalid_title": {"de": "Login-Link ungueltig", "en": "Login link invalid"},
    "status.login_link_invalid_msg": {"de": "Der Link ist abgelaufen oder wurde bereits benutzt.",
                                      "en": "The link has expired or has already been used."},
    "status.request_new_link_sub": {"de": "Fordere einen neuen Login-Link an.", "en": "Request a new login link."},
    # Unsubscribe (One-Click aus Mail)
    "status.unsub_fail_title": {"de": "Abmeldung fehlgeschlagen", "en": "Unsubscribe failed"},
    "status.unsub_link_invalid_msg": {"de": "Dieser Abmelde-Link ist nicht (mehr) gueltig.",
                                      "en": "This unsubscribe link is no longer valid."},
    "status.unsubscribed_title": {"de": "Abgemeldet", "en": "Unsubscribed"},
    "status.unsubscribed_msg": {"de": "Du bekommst keinen Wingcast mehr. Schade, dass du gehst!",
                                "en": "You'll no longer receive a Wingcast. Sorry to see you go!"},
    "status.unsubscribed_sub": {"de": "Du kannst dich jederzeit wieder anmelden.",
                                "en": "You can sign up again any time."},

    # ======================= Analyse Pre-Filter (deterministisch, KEIN LLM → user-facing Analyse-Output) =======================
    # DE exakt wie engine/analyzers.py. EN: damit englische Tester die not_safe/no-data-Verdikte lesen koennen.
    "analysis.no_weather_data": {"de": "Keine Wetterdaten fuer diesen Tag", "en": "No weather data for this day"},
    "analysis.nogo.wind_all_day": {"de": "Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors",
                                   "en": "Wind direction: outside the permitted sector all day"},
    "analysis.summary.wind_all_day": {"de": "Die Windrichtung liegt den ganzen Tag ausserhalb des erlaubten Sektors ({dir}). Kein fliegbares Fenster.",
                                      "en": "The wind direction is outside the permitted sector all day ({dir}). No flyable window."},
    "analysis.nogo.all_warnings": {"de": "Start-Fenster: Alle Stunden mit passender Windrichtung haben harte Warnungen (Sturm/Boeen/Regen/Gewitter)",
                                   "en": "Launch window: all hours with suitable wind direction have hard warnings (storm/gusts/rain/thunderstorm)"},
    "analysis.summary.all_warnings": {"de": "Alle {wind_ok}h mit passender Windrichtung haben harte Warnungen — kein nutzbares Start-Fenster.",
                                      "en": "All {wind_ok}h with suitable wind direction have hard warnings — no usable launch window."},
    "analysis.nogo.no_block": {"de": "Start-Fenster: Nur {clean}h sauber, kein zusammenhaengender Block >= {min}h",
                               "en": "Launch window: only {clean}h clean, no continuous block >= {min}h"},
    "analysis.summary.no_block": {"de": "Saubere Stunden ({clean}h) bilden kein zusammenhaengendes Start-Fenster (Minimum {min}h).",
                                  "en": "Clean hours ({clean}h) don't form a continuous launch window (minimum {min}h)."},
    "analysis.nogo.rain": {"de": "Niederschlag: Regen in {h} von {total} Stunden",
                           "en": "Precipitation: rain in {h} of {total} hours"},
    "analysis.summary.rain": {"de": "Nahezu ganztaegiger Niederschlag ({h} von {total} Stunden) ohne zusammenhaengendes trockenes Fenster (laengste Trockenphase {gap}h). Kein nutzbares Flugfenster.",
                              "en": "Near all-day precipitation ({h} of {total} hours) without a continuous dry window (longest dry spell {gap}h). No usable flight window."},
    "analysis.nogo.thunderstorm": {"de": "Gewitter: prognostiziert in {ts} von {total} Stunden",
                                   "en": "Thunderstorm: forecast in {ts} of {total} hours"},
    "analysis.summary.thunderstorm": {"de": "Praktisch ganztaegig Gewitter ({ts} von {total} Stunden). Kein fliegbares Fenster.",
                                      "en": "Thunderstorms practically all day ({ts} of {total} hours). No flyable window."},
    "analysis.window_none": {"de": "keins", "en": "none"},

    # ======================= Topic-Tags (build_topic_tags / build_region_topic_tags) =======================
    # Deterministische Backend-Tags (label/value/time) — werden zur Analyse-Bauzeit
    # in der aktiven Sprache erzeugt und in *_en.json / *.json persistiert.
    "tag.label.gusts": {"de": "Boeen", "en": "Gusts"},
    "tag.label.wind": {"de": "Wind", "en": "Wind"},
    "tag.label.aloft": {"de": "Hoehenwind", "en": "Upper wind"},
    "tag.label.foehn": {"de": "Foehn", "en": "Foehn"},
    "tag.label.rain": {"de": "Regen", "en": "Rain"},
    "tag.label.thunderstorm": {"de": "Gewitter", "en": "Thunderstorm"},
    "tag.label.clouds": {"de": "Bewoelkung", "en": "Clouds"},
    "tag.label.turbulence": {"de": "Klappern", "en": "Chop"},

    "tag.val.dir_wrong": {"de": "Richtung falsch", "en": "Wrong direction"},
    "tag.val.dir_ok_calm": {"de": "Richtung OK, ruhig", "en": "Direction OK, calm"},
    "tag.val.calm": {"de": "ruhig", "en": "calm"},
    "tag.val.foehn_strong": {"de": "stark", "en": "strong"},
    "tag.val.foehn_moderate": {"de": "moderat", "en": "moderate"},
    "tag.val.precip": {"de": "Niederschlag", "en": "Precipitation"},
    "tag.val.model_storm": {"de": "Modell-Gewitter", "en": "Model storm"},
    "tag.val.mech_rough": {"de": "mech. ruppig", "en": "mech. rough"},
    "tag.val.rain_widespread": {"de": "flaechig", "en": "widespread"},
    "tag.val.rain_scattered": {"de": "verstreut", "en": "scattered"},
    "tag.val.rain_isolated": {"de": "vereinzelt", "en": "isolated"},
    "tag.val.launch_in_clouds": {"de": "Startplatz in Wolken", "en": "Launch in clouds"},
    "tag.val.cloud_edge_launch": {"de": "Wolkenrand am Startplatz", "en": "Cloud edge at launch"},
    "tag.val.base_le_launch": {"de": "Basis {base}m ≤ Startplatz {elev}m", "en": "Base {base}m ≤ launch {elev}m"},
    "tag.val.base_near_launch": {"de": "Basis {base}m nahe Startplatz {elev}m", "en": "Base {base}m near launch {elev}m"},
    "tag.val.region_in_clouds": {"de": "Region in Wolken", "en": "Region in clouds"},
    "tag.val.cloud_edge_region": {"de": "Wolkenrand auf Region-Hoehe", "en": "Cloud edge at region level"},
    "tag.val.base_le_region": {"de": "Basis {base}m ≤ Region-Ref {elev}m", "en": "Base {base}m ≤ region ref {elev}m"},
    "tag.val.base_near_region": {"de": "Basis {base}m nahe Region-Ref {elev}m", "en": "Base {base}m near region ref {elev}m"},

    "tag.time.all_day": {"de": "ganztags", "en": "all day"},

    # ======================= JS-Strings (briefing.js + subscribe.js, user-facing) =======================
    # Werden via window.WC_I18N (siehe js_i18n()) in den Browser injiziert und mit
    # wcT(key, vars) abgerufen. DE-Werte sind VERBATIM aus dem bisherigen JS-Code
    # (DE-Ausgabe bleibt byte-identisch). Platzhalter {x} bleiben beim Injizieren
    # erhalten (t() formatiert nur mit kwargs, js_i18n() ruft ohne kwargs).
    # Safety-Baender (SAFETY_DEFS, Region-Pill)
    "js.safety.safe": {"de": "Sicher", "en": "Safe"},
    "js.safety.caution": {"de": "Vorsicht", "en": "Caution"},
    "js.safety.not_flyable": {"de": "Nicht fliegbar", "en": "Not flyable"},
    # Risk-Reward-Matrix
    "js.matrix.bubble_aria": {"de": "{spot}, {region}, Reward {score}, Sicherheit {safety}, {stars} Sterne",
                              "en": "{spot}, {region}, reward {score}, safety {safety}, {stars} stars"},
    "js.matrix.axis_safety": {"de": "↑ Sicherheit", "en": "↑ Safety"},
    "js.matrix.hidden": {"de": "{n} not-safe ausgeblendet", "en": "{n} not-safe hidden"},
    "js.matrix.legend_size": {"de": "⬤ Größe = Fliegbarkeit", "en": "⬤ Size = flyability"},
    "js.matrix.tt_safety": {"de": "Sicherheit", "en": "Safety"},
    # Region-Auswahl-Button (Toggle)
    "js.regions.none": {"de": "Keine", "en": "None"},
    "js.regions.all": {"de": "Alle", "en": "All"},
    # Wetterlage-Block (Heading, Toggle, Lage-Labels).
    # Die Lage-Label-Keys tragen den kanonischen DE-Wert aus
    # decide_lage_label() im Key ("js.lage.<value>") — das Strukturfeld
    # bleibt deutsch (deterministisch, Audit), uebersetzt wird nur die
    # Anzeige. Fehlt ein Key, zeigt briefing.js den DE-Wert als Fallback.
    "js.wetterlage.heading": {"de": "Wetterlage", "en": "Weather situation"},
    "js.wetterlage.less": {"de": "Weniger", "en": "Less"},
    "js.wetterlage.detail": {"de": "Detail", "en": "Detail"},
    "js.lage.Suedfoehnlage": {"de": "Suedfoehnlage", "en": "South foehn"},
    "js.lage.Nordfoehnlage": {"de": "Nordfoehnlage", "en": "North foehn"},
    "js.lage.Foehnlage (wechselnd)": {"de": "Foehnlage (wechselnd)", "en": "Foehn (variable)"},
    "js.lage.Vb-/Genua-Tief": {"de": "Vb-/Genua-Tief", "en": "Vb / Genoa low"},
    "js.lage.Bisenlage": {"de": "Bisenlage", "en": "Bise"},
    "js.lage.Westlage": {"de": "Westlage", "en": "Westerly flow"},
    "js.lage.Suedwestlage": {"de": "Suedwestlage", "en": "Southwesterly flow"},
    "js.lage.Nordwestlage": {"de": "Nordwestlage", "en": "Northwesterly flow"},
    "js.lage.Nordlage": {"de": "Nordlage", "en": "Northerly flow"},
    "js.lage.Nordostlage": {"de": "Nordostlage", "en": "Northeasterly flow"},
    "js.lage.Ostlage": {"de": "Ostlage", "en": "Easterly flow"},
    "js.lage.Suedostlage": {"de": "Suedostlage", "en": "Southeasterly flow"},
    "js.lage.Suedlage": {"de": "Suedlage", "en": "Southerly flow"},
    "js.lage.Hochdrucklage": {"de": "Hochdrucklage", "en": "High pressure"},
    "js.lage.Tiefdrucklage": {"de": "Tiefdrucklage", "en": "Low pressure"},
    "js.lage.Uebergangslage": {"de": "Uebergangslage", "en": "Transitional"},
    "js.lage.unbestimmt": {"de": "unbestimmt", "en": "undetermined"},
    "js.regions.deselect_all": {"de": "Alle Regionen abwählen", "en": "Deselect all regions"},
    "js.regions.select_all": {"de": "Alle Regionen auswählen", "en": "Select all regions"},
    # Tages-Statistik (Band-Counts)
    "js.stat.green": {"de": "grün", "en": "green"},
    "js.stat.amber": {"de": "amber", "en": "amber"},
    "js.stat.red": {"de": "rot", "en": "red"},
    "js.stat.top": {"de": "top", "en": "top"},
    # Focus-Banner (aus E-Mail-Deeplink)
    "js.focus.show_only_pre": {"de": "Zeige nur", "en": "Showing only"},
    "js.focus.show_all": {"de": "Alle Spots zeigen", "en": "Show all spots"},
    # Empty-States
    "js.empty.no_forecast": {"de": "Noch keine Prognosedaten vorhanden.", "en": "No forecast data yet."},
    "js.empty.spot_not_found": {"de": "Spot \"{spot}\" nicht in diesem Tag gefunden.",
                                "en": "Spot \"{spot}\" not found on this day."},
    "js.empty.no_match_pre": {"de": "Keine Spots", "en": "No spots"},
    "js.empty.in_filtered_regions": {"de": " in den gefilterten Regionen", "en": " in the filtered regions"},
    "js.empty.no_match_post": {"de": " entsprechen dem aktuellen Filter.", "en": " match the current filter."},
    "js.empty.counts_hidden": {"de": "{red} rot · {amber} amber ausgeblendet",
                               "en": "{red} red · {amber} amber hidden"},
    "js.filter.reset": {"de": "Filter zurücksetzen", "en": "Reset filters"},
    # Bulk-Toggle (Regionen auf-/zuklappen)
    "js.bulk.expand_all": {"de": "Alle ausklappen", "en": "Expand all"},
    "js.bulk.collapse_all": {"de": "Alle einklappen", "en": "Collapse all"},
    # Region-Pill-Tier-Labels (conditional/amber-Spektrum)
    "js.pill.tier0": {"de": "Abgleiter", "en": "Sled run"},
    "js.pill.tier1": {"de": "Schwacher Thermiktag", "en": "Weak thermal day"},
    "js.pill.safe_tier1": {"de": "Kurzer Thermikflug", "en": "Short thermal flight"},
    "js.pill.tier2": {"de": "Solider Thermiktag", "en": "Solid thermal day"},
    "js.pill.tier3": {"de": "Starker Thermiktag", "en": "Strong thermal day"},
    "js.pill.tier4": {"de": "XC-Tag", "en": "XC day"},
    # Spot-Detail / Meteogramm
    "js.spot.no_coords": {"de": "Keine Koordinaten", "en": "No coordinates"},
    "js.meteogram.title": {"de": "Meteogramm", "en": "Meteogram"},
    "js.meteogram.numbers_toggle": {"de": "Wind-/Böen-Zahlen ein-/ausblenden",
                                    "en": "Show/hide wind/gust numbers"},
    "js.meteogram.numbers": {"de": "Zahlen", "en": "Numbers"},
    "js.meteogram.unavailable": {"de": "Meteogramm nicht verfuegbar", "en": "Meteogram unavailable"},
    "js.meteogram.loading": {"de": "Lade Meteogramm…", "en": "Loading meteogram…"},
    "js.meteogram.no_data_for": {"de": "Keine Daten fuer {date}", "en": "No data for {date}"},
    "js.meteogram.render_error": {"de": "Render-Fehler", "en": "Render error"},
    "js.meteogram.data_unavailable": {"de": "Daten nicht verfuegbar", "en": "Data unavailable"},
    # Assessment-Sektionen (Spot-Detail)
    "js.assess.safety": {"de": "Sicherheits-Einschätzung", "en": "Safety assessment"},
    "js.assess.flight": {"de": "Flug-Einschätzung", "en": "Flight assessment"},
    # Teilen (Share)
    "js.share.flyability_suffix": {"de": " — Fliegbarkeit {rating}", "en": " — flyability {rating}"},
    "js.share.region": {"de": "Region", "en": "Region"},
    "js.share.brand_suffix": {"de": " · Wingcast Flugwetter", "en": " · Wingcast flight weather"},
    # Karten-Fallback (briefing.js + subscribe.js)
    "js.map.unavailable": {"de": "Karte nicht verfuegbar", "en": "Map unavailable"},
    # Start-Fenster-Summary (Spot-Detail)
    "js.window.time_range": {"de": "{s}:00 – {e}:00 Uhr", "en": "{s}:00 – {e}:00"},
    "js.window.sporty_only": {"de": "Nur sportlich {s}:00 – {e}:00 Uhr",
                              "en": "Experts only {s}:00 – {e}:00"},
    "js.window.not_launchable": {"de": "Heute nicht startbar", "en": "Not launchable today"},
    "js.window.sporty_secondary": {"de": "Sportlich {s}:00 – {e}:00 Uhr", "en": "Experts {s}:00 – {e}:00"},
    "js.window.hour_tooltip": {"de": "{h}:00 Uhr · {lbl}", "en": "{h}:00 · {lbl}"},
    "js.window.state_startbar": {"de": "Startbar", "en": "Launchable"},
    "js.window.state_sportlich": {"de": "Sportlich", "en": "Experts"},
    "js.window.state_blockiert": {"de": "Blockiert", "en": "Blocked"},
    "js.window.state_neutral": {"de": "Ausserhalb", "en": "Outside"},
    # Generische Fehler-/Status-Texte (briefing.js)
    "js.error.prefix": {"de": "Fehler: {msg}", "en": "Error: {msg}"},
    "js.generating": {"de": "Generiert…", "en": "Generating…"},
    "js.failed": {"de": "Fehlgeschlagen", "en": "Failed"},
    # Link Wetterlage-Block -> Synoptik-Karte
    "js.wetterlage.to_map": {"de": "Zur Druckkarte", "en": "Open pressure chart"},

    # ======================= synoptic-map.js (Synoptik-Karte, user-facing) =======================
    "js.syn.high_letter": {"de": "H", "en": "H"},
    "js.syn.low_letter": {"de": "T", "en": "L"},
    "js.syn.high_aria": {"de": "Hochdruckzentrum {p} hPa", "en": "High pressure centre {p} hPa"},
    "js.syn.low_aria": {"de": "Tiefdruckzentrum {p} hPa", "en": "Low pressure centre {p} hPa"},
    "js.syn.updated": {"de": "Stand: {ts}", "en": "Updated: {ts}"},
    "js.syn.no_data": {"de": "Keine Druckdaten verfuegbar.", "en": "No pressure data available."},
    "js.syn.no_text": {"de": "Kein Wetterlage-Text verfuegbar.", "en": "No weather situation text available."},
    "js.syn.load_failed": {"de": "Laden fehlgeschlagen", "en": "Loading failed"},
    "js.syn.isobars_hint": {"de": "Isobaren alle 4 hPa · Fläche = Bodendruck · {model}",
                            "en": "Isobars every 4 hPa · shading = surface pressure · {model}"},
    # Timeline-Animation (Redesign 07/2026): Play/Pause + Scrubber statt Tabs/Chips
    "js.syn.play": {"de": "Animation abspielen", "en": "Play animation"},
    "js.syn.pause": {"de": "Animation anhalten", "en": "Pause animation"},
    "js.syn.timeline_aria": {"de": "Zeitleiste: Zeitpunkt waehlen", "en": "Timeline: choose a time"},
    "js.syn.tick_aria": {"de": "{d}, {t} Uhr", "en": "{d}, {t}"},
    "js.syn.wetterlage_title": {"de": "Wetterlage", "en": "Weather situation"},
    # Karten-Legende (Redesign 07/2026: Druckband-Toenung)
    "js.syn.legend_title": {"de": "Bodendruck (hPa)", "en": "Surface pressure (hPa)"},
    "js.syn.legend_low": {"de": "Tief", "en": "Low"},
    "js.syn.legend_high": {"de": "Hoch", "en": "High"},

    # ======================= chat.js (user-facing; Admin-Analyse/Debug bleibt DE) =======================
    "js.chat.unknown_error": {"de": "Unbekannter Fehler", "en": "Unknown error"},
    "js.chat.login_required": {"de": "Logge dich ein, um den Chat-Berater zu nutzen.",
                               "en": "Log in to use the chat advisor."},
    "js.chat.no_reply": {"de": "Keine Antwort erhalten.", "en": "No reply received."},
    "js.chat.reset_confirm": {"de": "Gesamte Konversation zurücksetzen?",
                              "en": "Reset the entire conversation?"},
    # Dynamische Quick-Action-Prompts (label = Button, msg = an den Chat gesendet)
    "js.chat.q_meteogram_label": {"de": "Meteogramm zeigen", "en": "Show meteogram"},
    "js.chat.q_meteogram_msg": {"de": "Zeig mir das komplette Meteogramm vom besten Spot heute (Wind, Thermik, Wolken, Höhenwind).",
                                "en": "Show me the full meteogram of today's best spot (wind, thermals, clouds, upper winds)."},
    "js.chat.q_heatmap_label": {"de": "Thermik-Heatmap", "en": "Thermal heatmap"},
    "js.chat.q_heatmap_msg": {"de": "Zeig mir die Thermik-Heatmap vom besten Spot heute mit Steigwerten pro Höhe und Stunde.",
                              "en": "Show me the thermal heatmap of today's best spot with climb rates per altitude and hour."},
    "js.chat.q_upperwind_label": {"de": "Höhenwind & Turbulenz", "en": "Upper winds & turbulence"},
    "js.chat.q_upperwind_msg": {"de": "Zeig mir das vertikale Windprofil und die Turbulenz vom besten Spot heute.",
                                "en": "Show me the vertical wind profile and turbulence of today's best spot."},
    "js.chat.q_xc_today_label": {"de": "Klassiker heute?", "en": "Classic XC today?"},
    "js.chat.q_xc_today_msg": {"de": "Wo könnte heute ein XC-Klassiker gehen? Zeig mir Streckenflug-Rating, Wolkenbasis und Wind-Layer.",
                               "en": "Where could a classic XC route work today? Show me cross-country rating, cloud base and wind layers."},
    "js.chat.q_xc_tomorrow_label": {"de": "Klassiker morgen?", "en": "Classic XC tomorrow?"},
    "js.chat.q_xc_tomorrow_msg": {"de": "Wo könnte morgen ein XC-Klassiker gehen? Zeig mir Streckenflug-Rating und Basis.",
                                  "en": "Where could a classic XC route work tomorrow? Show me cross-country rating and cloud base."},
    "js.chat.q_xc_week_label": {"de": "Wo geht XC?", "en": "Where's XC on?"},
    "js.chat.q_xc_week_msg": {"de": "Wo geht diese Woche der beste Streckenflug? Zeig mir das höchste Streckenflug-Rating der nächsten Tage.",
                              "en": "Where's the best cross-country this week? Show me the highest cross-country rating over the next few days."},
    "js.chat.q_foehn_today_label": {"de": "Föhn-Check", "en": "Foehn check"},
    "js.chat.q_foehn_today_msg": {"de": "Wie sieht die Föhn-Lage aus? Zeig mir das Föhn-Diagramm und welche Spots betroffen sind.",
                                  "en": "What's the foehn situation? Show me the foehn chart and which spots are affected."},
    "js.chat.q_foehn_week_label": {"de": "Föhn-Lage?", "en": "Foehn outlook?"},
    "js.chat.q_foehn_week_msg": {"de": "Wie entwickelt sich der Föhn diese Woche? Zeig mir das Föhn-Diagramm.",
                                 "en": "How is the foehn developing this week? Show me the foehn chart."},
    "js.chat.q_planb_label": {"de": "Plan B heute?", "en": "Plan B today?"},
    "js.chat.q_planb_msg": {"de": "Heute sind viele Spots nicht fliegbar — wo gibt es trotzdem eine sichere Option und warum?",
                            "en": "Many spots aren't flyable today — where's a safe option anyway, and why?"},
    "js.chat.q_bestday_label": {"de": "Bester Tag?", "en": "Best day?"},
    "js.chat.q_bestday_msg": {"de": "Welcher Tag diese Woche ist am besten zum Fliegen?",
                              "en": "Which day this week is best for flying?"},

    # ======================= chat-charts.js (Chat-Visualisierungen, user-facing) =======================
    # Einheiten (km/h, m/s, hPa), ":00" und "Wind" bleiben (sprachneutral/identisch).
    "js.chart.loading": {"de": "Daten werden geladen…", "en": "Loading data…"},
    "js.chart.loading_chart": {"de": "Chart wird geladen…", "en": "Loading chart…"},
    "js.chart.chartjs_load_failed": {"de": "Chart.js konnte nicht geladen werden",
                                     "en": "Chart.js could not be loaded"},
    "js.chart.unknown_type": {"de": "Unbekannter Chart-Typ: {type}", "en": "Unknown chart type: {type}"},
    "js.chart.no_spot": {"de": "Kein Spot angegeben", "en": "No spot specified"},
    "js.chart.no_spot_or_region": {"de": "Kein Spot oder Region angegeben", "en": "No spot or region specified"},
    "js.chart.no_spots_or_region": {"de": "Keine Spots oder Region angegeben", "en": "No spots or region specified"},
    "js.chart.no_wind_data": {"de": "Keine Winddaten für {spot} am {date}",
                              "en": "No wind data for {spot} on {date}"},
    "js.chart.no_data_0618": {"de": "Keine Daten 06-18h", "en": "No data 06–18h"},
    "js.chart.no_thermal_data": {"de": "Keine Thermikdaten für {spot} am {date}",
                                 "en": "No thermal data for {spot} on {date}"},
    "js.chart.no_thermal_day": {"de": "Keine Thermik an diesem Tag", "en": "No thermals on this day"},
    "js.chart.no_foehn_data": {"de": "Keine Föhndaten für {date}", "en": "No foehn data for {date}"},
    "js.chart.no_profile_data": {"de": "Keine Profildaten", "en": "No profile data"},
    "js.chart.no_upperwind_data": {"de": "Keine Höhenwinddaten für {spot} am {date}",
                                   "en": "No upper-wind data for {spot} on {date}"},
    "js.chart.no_data": {"de": "Keine Daten für {spot} am {date}", "en": "No data for {spot} on {date}"},
    "js.chart.no_data_region": {"de": "Keine Daten für Region {region} am {date}",
                                "en": "No data for region {region} on {date}"},
    "js.chart.meteogram_module": {"de": "Meteogram-Modul nicht geladen", "en": "Meteogram module not loaded"},
    "js.chart.invalid_json": {"de": "Ungültiges JSON für Chart", "en": "Invalid JSON for chart"},
    "js.chart.map_error": {"de": "Kartenfehler: {msg}", "en": "Map error: {msg}"},
    "js.chart.chart_error": {"de": "Chart-Fehler: {msg}", "en": "Chart error: {msg}"},
    # Tooltip-/Legenden-Labels
    "js.chart.tt_gusts": {"de": "Böen: ", "en": "Gusts: "},
    "js.chart.tt_direction": {"de": "Richtung: ", "en": "Direction: "},
    "js.chart.tt_climb": {"de": "Steigen: ", "en": "Climb: "},
    "js.chart.tt_crestwind": {"de": "Kammwind: ", "en": "Crest wind: "},
    "js.chart.legend_gusts": {"de": "Böen", "en": "Gusts"},
    "js.chart.legend_crestwind": {"de": "Kammwind", "en": "Crest wind"},
    "js.chart.thermal_torn": {"de": "Thermik zerrissen (Höhenwind-Scherung)",
                              "en": "Thermals torn apart (upper-wind shear)"},

    # ======================= meteogram.js (Meteogramm-Visualisierung, user-facing) =======================
    # DE byte-identisch (inkl. ASCII-Schreibweisen "fuer"/"Boeen"/"verfuegbar").
    # Einheiten (km/h, m/s, mm, J/kg, m MSL, %), "Wind", "Rating", "CAPE" bleiben.
    "js.mg.no_data_day": {"de": "Keine Daten fuer diesen Tag.", "en": "No data for this day."},
    "js.mg.analysis_unavailable": {"de": "Analyse-Ansicht nicht verfuegbar", "en": "Analysis view unavailable"},
    # Warn-Typen (Legende/Bänder)
    "js.mg.warn_storm": {"de": "Gewitter", "en": "Thunderstorm"},
    "js.mg.warn_rain": {"de": "Regen", "en": "Rain"},
    "js.mg.warn_gust_danger": {"de": "Böen gefährlich", "en": "Gusts dangerous"},
    "js.mg.warn_aloft_danger": {"de": "Höhenwind gefährlich", "en": "Upper wind dangerous"},
    "js.mg.warn_aloftgust_danger": {"de": "Höhenböen gefährlich", "en": "Upper gusts dangerous"},
    "js.mg.warn_strong": {"de": "Grundwind zu stark", "en": "Ground wind too strong"},
    "js.mg.warn_wrong": {"de": "Wind falsche Richtung", "en": "Wind wrong direction"},
    "js.mg.warn_gust_warn": {"de": "Böen stark", "en": "Gusts strong"},
    "js.mg.warn_aloft_warn": {"de": "Höhenwind kräftig", "en": "Upper wind brisk"},
    "js.mg.warn_aloftgust_warn": {"de": "Höhenböen kräftig", "en": "Upper gusts brisk"},
    # Achsen-/Sektions-Labels
    "js.mg.axis_precip": {"de": "Nied./Gew.", "en": "Precip/storm"},
    "js.mg.ground_paren": {"de": "(Boden)", "en": "(ground)"},
    "js.mg.warnings": {"de": "Warnungen", "en": "Warnings"},
    "js.mg.more_warnings_one": {"de": "{n} weitere Warnung:", "en": "{n} more warning:"},
    "js.mg.more_warnings_many": {"de": "{n} weitere Warnungen:", "en": "{n} more warnings:"},
    # Niederschlag/Überentwicklung-Titel
    "js.mg.precip_storm": {"de": "{mm} mm + Gewitter", "en": "{mm} mm + thunderstorm"},
    "js.mg.overdev": {"de": "Überentwicklungsgefahr", "en": "Overdevelopment risk"},
    "js.mg.overdev_high": {"de": " (hoch)", "en": " (high)"},
    "js.mg.overdev_possible": {"de": " (möglich)", "en": " (possible)"},
    # Tooltip-Labels
    "js.mg.tt_clouds": {"de": "Wolken", "en": "Clouds"},
    "js.mg.tt_cloudbase": {"de": "Wolkenbasis", "en": "Cloud base"},
    "js.mg.tt_groundwind": {"de": "Bodenwind", "en": "Ground wind"},
    "js.mg.tt_direction": {"de": "Richtung", "en": "Direction"},
    "js.mg.tt_launchcheck": {"de": "Start-Check", "en": "Launch check"},
    "js.mg.dir_ok": {"de": "✓ OK", "en": "✓ OK"},
    "js.mg.dir_wrong": {"de": "✕ Falsche Richtung", "en": "✕ Wrong direction"},
    "js.mg.free_atm": {"de": "(freie Atm.)", "en": "(free atm.)"},
    "js.mg.tt_climbrate_here": {"de": "Steigrate hier", "en": "Climb rate here"},
    "js.mg.tt_ground": {"de": "Boden", "en": "Ground"},
    "js.mg.tt_gusts_ascii": {"de": "Boeen", "en": "Gusts"},
    "js.mg.tt_climbrate": {"de": "Steigrate", "en": "Climb rate"},
    "js.mg.tt_workheight_base": {"de": "Arbeitshöhe (Basis)", "en": "Working height (base)"},
    "js.mg.tt_workheight": {"de": "Arbeitshöhe", "en": "Working height"},
    "js.mg.torn_unusable": {"de": "⚠ zerrissen (Scherung)", "en": "⚠ torn apart (shear)"},
    "js.mg.torn_partial": {"de": "⚠ angerissen (Scherung)", "en": "⚠ partly torn (shear)"},
    "js.mg.tt_thermik": {"de": "Thermik", "en": "Thermals"},
    "js.mg.torn_hint_unusable": {"de": "Schraffur: Höhenwind zerreisst die Thermik — Steigen unbrauchbar, turbulent, abgerissene Bärte.",
                                 "en": "Hatching: upper wind tears the thermals apart — climb unusable, turbulent, broken-up cores."},
    "js.mg.torn_hint_partial": {"de": "Schraffur: Höhenwind reisst die Thermik an — Steigen brüchig und ruppig, schwer zentrierbar.",
                                "en": "Hatching: upper wind partly tears the thermals — climb patchy and rough, hard to centre."},
    # Hero-/Alt-Profil-Labels
    "js.mg.alt_gust": {"de": "Böe ", "en": "Gust "},
    "js.mg.cloud_low": {"de": "T:", "en": "L:"},

    # ======================= analysis-view.js (Analyse-Anzeige, user-facing; Admin-Feedback bleibt DE) =======================
    # Wiederverwendet: js.safety.*, js.assess.*, js.pill.*, js.window.* (Startfenster).
    "js.av.no_data": {"de": "Keine Daten", "en": "No data"},
    "js.av.no_analysis": {"de": "Keine Analyse", "en": "No analysis"},
    "js.av.rating_of5": {"de": "Rating {n} von 5", "en": "Rating {n} of 5"},
    "js.av.rating_word": {"de": "Bewertung", "en": "Rating"},
    "js.av.analysis_pending": {"de": "Datenanalyse ausstehend", "en": "Data analysis pending"},
    "js.av.type_prefix": {"de": "Typ: ", "en": "Type: "},
    "js.av.tag_info": {"de": "Hinweis", "en": "Note"},
    "js.av.start_window": {"de": "Startfenster", "en": "Launch window"},
    "js.av.start_window_aria": {"de": "Startfenster-Verlauf ueber den Tag",
                                "en": "Launch-window course over the day"},
    "js.av.flighttype": {"de": "Flugtyp", "en": "Flight type"},
    "js.av.duration": {"de": "Dauer", "en": "Duration"},
    "js.av.peak_thermik": {"de": "Peak Thermik", "en": "Peak thermals"},
    "js.av.xc_potential": {"de": "XC-Potenzial", "en": "XC potential"},
    "js.av.streckenflug": {"de": "Streckenflug", "en": "Cross-country"},
    "js.av.analysis_prefix": {"de": "Analyse: ", "en": "Analysis: "},
    # Streckenflug-Rating-Badges (1–6)
    "js.av.sf_1": {"de": "kein XC", "en": "no XC"},
    "js.av.sf_2": {"de": "ganz kurz", "en": "very short"},
    "js.av.sf_3": {"de": "lokal", "en": "local"},
    "js.av.sf_4": {"de": "kurz wegfliegen", "en": "short hop"},
    "js.av.sf_5": {"de": "weit", "en": "far"},
    "js.av.sf_6": {"de": "klassiker", "en": "classic"},
    # Lange Rating-Beschreibungen (Fliegbarkeit-Insight)
    "js.av.rating_long_1": {"de": "Abgleiter — kein Thermikflug", "en": "Sled run — no thermal flying"},
    "js.av.rating_long_2": {"de": "Kurzer Thermikflug — Suchtag (1–2 h mit Glück)",
                            "en": "Short thermal flight — a searching day (1–2 h if lucky)"},
    "js.av.rating_long_3": {"de": "Solider Thermikflug — typischer Sommertag",
                            "en": "Solid thermal flight — a typical summer day"},
    "js.av.rating_long_4": {"de": "Starker Thermikflug — lokal-XC möglich",
                            "en": "Strong thermal flight — local XC possible"},
    "js.av.rating_long_5": {"de": "XC-Tag — 50–150 km+ (Top-Tage als \"Klassiker\")",
                            "en": "XC day — 50–150 km+ (top days as \"classics\")"},

    # ======================= dataview.js („Welche Daten die KI sieht", user-facing) =======================
    "js.dv.loading": {"de": "Lade Daten…", "en": "Loading data…"},
    "js.dv.in_band": {"de": "im Flugbereich", "en": "in flight range"},
    "js.dv.above_band": {"de": "oberhalb Flugbereich", "en": "above flight range"},
    "js.dv.table_head": {
        "de": '<th>Zeit</th><th>Wind<small>Boden</small></th><th>Höhenwind<small>Wind/Böen · Richtung · Höhe</small></th><th>Thermik</th><th>Wolken<small>% · tief/mittel/hoch · Basis</small></th><th>Strahlung<small>global · direkt</small></th><th>Flugbereich<small>MSL</small></th><th>Temp</th><th>Warnungen</th>',
        "en": '<th>Time</th><th>Wind<small>Ground</small></th><th>Upper wind<small>Wind/gusts · direction · altitude</small></th><th>Thermals</th><th>Clouds<small>% · low/mid/high · base</small></th><th>Radiation<small>global · direct</small></th><th>Flight range<small>MSL</small></th><th>Temp</th><th>Warnings</th>'},

    # ======================= map.js (Spot-Karte, user-facing; Debug-Panels bleiben DE) =======================
    "js.map.no_json_long": {"de": "Server lieferte keine JSON-Daten (vermutlich Fehlerseite). Bitte kurz warten und erneut versuchen.",
                            "en": "The server returned no JSON data (probably an error page). Please wait a moment and try again."},
    "js.map.no_weather_loaded": {"de": "Keine Wetterdaten geladen", "en": "No weather data loaded"},
    "js.map.analysis_unavailable": {"de": "Analyse-Ansicht nicht verfügbar.", "en": "Analysis view unavailable."},
    "js.map.loading_data": {"de": "Lade Daten...", "en": "Loading data..."},
    "js.map.loading_analysis": {"de": "Lade Analyse...", "en": "Loading analysis..."},
    "js.map.weather_as_of": {"de": "Wetter-Stand: ", "en": "Weather as of: "},
    "js.map.http_loading": {"de": "HTTP {status} beim Laden der Wetterdaten",
                            "en": "HTTP {status} while loading weather data"},

    # ======================= region-map.js (Regionskarte, user-facing; Debug-Panels bleiben DE) =======================
    "js.rm.not_safe": {"de": "Nicht sicher", "en": "Not safe"},
    "js.rm.error": {"de": "Fehler", "en": "Error"},
    "js.rm.no_json": {"de": "Server lieferte keine JSON-Daten", "en": "The server returned no JSON data"},
    "js.rm.q_no_data": {"de": "? Keine Daten", "en": "? No data"},
    "js.rm.no_analysis_day": {"de": "Keine Analyse fuer diesen Tag", "en": "No analysis for this day"},
    "js.rm.no_spot_data": {"de": "Keine Spot-Daten an diesem Tag", "en": "No spot data on this day"},
    "js.rm.no_flyable_spot": {"de": "Heute kein fliegbarer Spot in dieser Region",
                              "en": "No flyable spot in this region today"},
    "js.rm.no_xc_spot": {"de": "Kein Spot mit Rating ≥ 5 in dieser Region",
                         "en": "No spot with rating ≥ 5 in this region"},
    "js.rm.top_spots": {"de": "Top-Spots", "en": "Top spots"},
    "js.rm.flyable_suffix": {"de": " fliegbar", "en": " flyable"},
    "js.rm.meteogram_loading": {"de": "Meteogramm wird geladen...", "en": "Loading meteogram..."},
    "js.rm.no_weather": {"de": "Keine Wetterdaten verfuegbar", "en": "No weather data available"},
    "js.rm.no_data_day": {"de": "Keine Daten fuer diesen Tag", "en": "No data for this day"},
    "js.rm.stale_title": {"de": "Wetterdaten veraltet:", "en": "Weather data outdated:"},
    "js.rm.partial_days": {"de": "Nur {have} von {expected} Vorhersagetagen verfügbar. ",
                           "en": "Only {have} of {expected} forecast days available. "},
    "js.rm.last_update": {"de": "Letztes erfolgreiches Update: {date}.",
                          "en": "Last successful update: {date}."},

    # ======================= rating-info.js (Rating-Hilfe-Panel + Mini-Legende, user-facing) =======================
    "js.ri.title": {"de": "Wie funktioniert das Rating?", "en": "How does the rating work?"},
    "js.ri.close": {"de": "Schliessen", "en": "Close"},
    "js.ri.lead": {"de": "Jeder Spot oder Region wird auf <b>zwei unabhaengigen Achsen</b> eingeschaetzt — Sicherheit und Fliegbarkeit. Beides siehst du im selben Marker.",
                   "en": "Every spot or region is assessed on <b>two independent axes</b> — safety and flyability. You see both in the same marker."},
    "js.ri.axis_color": {"de": "Farbe = Sicherheit", "en": "Colour = safety"},
    "js.ri.color_green": {"de": "<b>Gruen</b> — sicher fliegbar", "en": "<b>Green</b> — safely flyable"},
    "js.ri.color_amber": {"de": "<b>Orange</b> — Vorsicht, Caution-Notes beachten",
                          "en": "<b>Orange</b> — caution, mind the caution notes"},
    "js.ri.color_red": {"de": "<b>Rot</b> — nicht fliegbar", "en": "<b>Red</b> — not flyable"},
    "js.ri.axis_number": {"de": "Zahl = Fliegbarkeit (1–5)", "en": "Number = flyability (1–5)"},
    "js.ri.fly1": {"de": "<b>1</b> — Abgleiter", "en": "<b>1</b> — Sled run"},
    "js.ri.fly2": {"de": "<b>2</b> — Kurzer Thermikflug (Suchtag)", "en": "<b>2</b> — Short thermal flight (searching day)"},
    "js.ri.fly3": {"de": "<b>3</b> — Solider Thermikflug", "en": "<b>3</b> — Solid thermal flight"},
    "js.ri.fly4": {"de": "<b>4</b> — Starker Thermikflug", "en": "<b>4</b> — Strong thermal flight"},
    "js.ri.fly5": {"de": "<b>5</b> — XC-Tag (Top-Tage als \"Klassiker\")", "en": "<b>5</b> — XC day (top days as \"classics\")"},
    "js.ri.examples": {"de": "Beispiele", "en": "Examples"},
    "js.ri.ex_xc": {"de": "XC-Tag / Klassiker", "en": "XC day / classic"},
    "js.ri.ex_strong": {"de": "Starker Thermikflug", "en": "Strong thermal flight"},
    "js.ri.ex_caution": {"de": "Vorsicht — solid moeglich", "en": "Caution — solid possible"},
    "js.ri.ex_notfly": {"de": "Nicht fliegbar", "en": "Not flyable"},
    "js.ri.detail_title": {"de": "Im Detail-Panel — die Tiefe", "en": "In the detail panel — the depth"},
    "js.ri.dt_safety": {"de": "Sicherheits-Rating", "en": "Safety rating"},
    "js.ri.dd_safety": {"de": "0–10. Aggregat aus bis zu 8 Sub-Aspekten: Bodenwind, Boeen, Hoehenwind, Foehn, Niederschlag, Gewitter, CAPE, Sicht. Aggregation per <b>Weakest-Link</b> — der schwaechste Aspekt zieht das Rating nach unten. Ein einzelnes Gewitter macht den Tag rot, auch wenn alle anderen Aspekte perfekt sind.",
                        "en": "0–10. Aggregated from up to 8 sub-aspects: ground wind, gusts, upper wind, foehn, precipitation, thunderstorm, CAPE, visibility. Aggregated via <b>weakest link</b> — the weakest aspect pulls the rating down. A single thunderstorm turns the day red, even if every other aspect is perfect."},
    "js.ri.dt_fly": {"de": "Fliegbarkeit — Kategorie (1–5)", "en": "Flyability — category (1–5)"},
    "js.ri.dd_fly": {"de": "Statt einer Zahl vergibt die KI eine <b>Kategorie</b> die der Pilot kennt: <b>Abgleiter</b> (1, keine Thermik), <b>Kurzer Thermikflug</b> (2, Suchtag mit 1–2h Thermik wenn Glueck), <b>Solider Thermikflug</b> (3, mehrere Stunden), <b>Starker Thermikflug</b> (4, lokal-XC), <b>XC-Tag</b> (5, Strecke 50–150km+; \"Klassiker\" als Auszeichnung an Top-Tagen). Bei <b>nicht fliegbar</b> wird die Fliegbarkeit auf 1 gesetzt.",
                     "en": "Instead of a number, the AI assigns a <b>category</b> pilots know: <b>sled run</b> (1, no thermals), <b>short thermal flight</b> (2, a searching day with 1–2h of thermals if lucky), <b>solid thermal flight</b> (3, several hours), <b>strong thermal flight</b> (4, local XC), <b>XC day</b> (5, routes of 50–150km+; \"classic\" as a distinction on top days). When <b>not flyable</b>, flyability is set to 1."},
    "js.ri.dt_xc": {"de": "Streckenflug-Rating (nur Spot)", "en": "Cross-country rating (spot only)"},
    "js.ri.dd_xc": {"de": "1–5 fuer XC-Potenzial. Kann sich stark von der Fliegbarkeit unterscheiden — ein Spot kann lokal stark sein (Fliegbarkeit 4) aber die Region erlaubt kein Wegfliegen (Streckenflug 2).",
                    "en": "1–5 for XC potential. Can differ strongly from flyability — a spot can be strong locally (flyability 4) yet the region allows no flying away (cross-country 2)."},
    "js.ri.who_title": {"de": "Wer entscheidet was?", "en": "Who decides what?"},
    "js.ri.who_safety": {"de": "<b>Sicherheit:</b> KI + Decision-Engine. Das LLM beurteilt Aspekte, harte Sicherheits-Schwellen (Foehn-Durchbruch, Hoehenwind &gt; 30 km/h, Gewitter) <b>ueberschreiben</b> das LLM — ein gefaehrlicher Tag kann nicht \"weggetextet\" werden.",
                         "en": "<b>Safety:</b> AI + decision engine. The LLM judges aspects; hard safety thresholds (foehn breakthrough, upper wind &gt; 30 km/h, thunderstorm) <b>override</b> the LLM — a dangerous day cannot be \"talked away\"."},
    "js.ri.who_fly": {"de": "<b>Fliegbarkeit (Kategorie):</b> reine KI-Einschaetzung. Die KI waehlt eine der 5 Kategorien aus dem Pilot-Vokabular — kein Rechnen, kein Mittelwert. Bei <b>nicht sicher</b> faellt die Fliegbarkeit automatisch auf 1 (keine Belohnung ohne Sicherheit).",
                      "en": "<b>Flyability (category):</b> pure AI assessment. The AI picks one of the 5 categories from the pilot vocabulary — no arithmetic, no averaging. When <b>not safe</b>, flyability automatically drops to 1 (no reward without safety)."},
    "js.ri.legend_toggle": {"de": "Legende", "en": "Legend"},
    "js.ri.legend_toggle_aria": {"de": "Legende ein-/ausblenden", "en": "Show/hide legend"},
    "js.ri.legend_hint": {"de": "Zahl im Marker = Fliegbarkeit (1–5)", "en": "Number in marker = flyability (1–5)"},

    # ======================= feedback.js (Feedback-Widget, user-facing) =======================
    "js.fb.placeholder": {"de": "Was passt nicht? (z.B. Wind war stärker, Thermik viel früher, Bisenrichtung falsch …)",
                          "en": "What's off? (e.g. wind was stronger, thermals much earlier, wrong bise direction …)"},
    "js.fb.thanks": {"de": "Danke für deine Bewertung.", "en": "Thanks for your rating."},
    "js.fb.send_error": {"de": "Fehler beim Senden", "en": "Error while sending"},
    "js.fb.need_input": {"de": "Bitte Kommentar eingeben oder Bewertung wählen.",
                         "en": "Please enter a comment or choose a rating."},

    # ======================= foehn_diagram.js (Föhndiagramm, user-facing) =======================
    "js.foehn.axis_pressure": {"de": "Druckdifferenz (Süd − Nord)", "en": "Pressure difference (south − north)"},
}


def get_current_lang() -> str:
    """Aktive Sprache (global). Faellt bei ungueltigem Wert auf 'de' zurueck."""
    lang = (getattr(config, "LANG", "de") or "de").strip().lower()
    return lang if lang in SUPPORTED else "de"


def t(key: str, **kwargs) -> str:
    """Uebersetzt key in die aktive Sprache, mit Deutsch-Fallback.

    Unbekannter key -> key selbst wird zurueckgegeben (macht fehlende Eintraege
    in der UI sofort sichtbar). Optionale **kwargs werden via str.format
    eingesetzt ({name} etc.)."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    lang = get_current_lang()
    text = entry.get(lang) or entry.get("de") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def llm_lang_instruction() -> str:
    """Zusatz-Anweisung, die ans Ende eines user-facing LLM-Prompts gehaengt wird.

    DE -> leerer String (Ausgabe bleibt exakt wie die validierte Version).
    EN -> klare Englisch-Anweisung. Interne Daten/Logik/Reasoning bleiben Deutsch,
    nur die finale Ausgabesprache kippt."""
    if get_current_lang() == "en":
        return (
            "\n\nIMPORTANT — OUTPUT LANGUAGE: Write your entire response to the user "
            "in natural, fluent English. All field values, prose, summaries and notes "
            "must be in English. Keep the meaning, structure and verdicts identical; "
            "only the language changes."
        )
    return ""


# Keys OHNE 'js.'-Praefix, die das Frontend-JS dennoch braucht (Wiederverwendung
# bereits existierender Template-Keys, statt den Wortlaut zu duplizieren).
_JS_EXTRA_KEYS = (
    "chat.welcome",
    "chat.quick_map_label", "chat.quick_map_msg",
    "chat.quick_top3_label", "chat.quick_top3_msg",
    "chat.quick_wind_label", "chat.quick_wind_msg",
    "foehn.no_data",
)


def js_i18n() -> dict[str, str]:
    """Kuratiertes Subset der Sprach-Tabelle fuer das Frontend-JS.

    Liefert alle Keys mit Praefix 'js.' (plus 'month.*' fuer formatDateDE und die
    _JS_EXTRA_KEYS-Allowlist) in die AKTIVE Sprache aufgeloest. Wird in base.html
    als window.WC_I18N injiziert; der JS-Helfer wcT(key, vars) macht nur noch die
    {platzhalter}-Interpolation. Platzhalter bleiben erhalten, weil t() ohne
    kwargs nicht formatiert."""
    return {
        k: t(k)
        for k in STRINGS
        if k.startswith("js.") or k.startswith("month.") or k in _JS_EXTRA_KEYS
    }
