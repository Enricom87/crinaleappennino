"""Invio automatico via Brevo: allerta neve (quando serve) e riepilogo del giovedì.

Variabili d'ambiente richieste (segreti di GitHub):
  BREVO_API_KEY   chiave API di Brevo
  BREVO_LIST_ID   id numerico della lista iscritti
  SENDER_EMAIL    mittente verificato su Brevo (es. allerta@tuodominio.it)
Senza chiave lo script non invia nulla e termina senza errori.
"""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "state.json"
API = "https://api.brevo.com/v3"


def load_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def email_html(site: dict, heading: str, items: list[str], sponsor: dict | None) -> str:
    li = "".join(f"<li style='margin:6px 0'>{html.escape(i)}</li>" for i in items)
    sp = ""
    if sponsor:
        sp = (f"<p style='background:#e8f2fa;padding:12px;border-radius:8px;font-size:14px'>Con il supporto di "
              f"<a href='{html.escape(sponsor['url'])}'><strong>{html.escape(sponsor['name'])}</strong></a> · "
              f"{html.escape(sponsor.get('tagline', ''))}</p>")
    return (f"<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#0f2236'>"
            f"<h2 style='color:#1d4f7a'>{html.escape(heading)}</h2><ul>{li}</ul>"
            f"<p><a href='{site['base_url']}/' style='background:#1d4f7a;color:#fff;padding:10px 16px;"
            f"border-radius:20px;text-decoration:none'>Dettagli quota per quota</a></p>{sp}"
            f"<p style='font-size:12px;color:#6b7f93'>Previsioni automatiche e indicative, non sostituiscono i "
            f"bollettini ufficiali. <a href='{{{{ unsubscribe }}}}'>Cancellati</a></p></div>")


def send(subject: str, body: str, site: dict) -> bool:
    key, list_id, sender = (os.environ.get(k, "").strip() for k in ("BREVO_API_KEY", "BREVO_LIST_ID", "SENDER_EMAIL"))
    if not (key and list_id and sender):
        print("Brevo non configurato: nessun invio.")
        return False
    h = {"api-key": key, "content-type": "application/json", "accept": "application/json"}
    r = requests.post(f"{API}/emailCampaigns", headers=h, timeout=60, json={
        "name": f"{subject} {datetime.now():%Y-%m-%d %H:%M}", "subject": subject,
        "sender": {"name": site["name"], "email": sender}, "htmlContent": body,
        "recipients": {"listIds": [int(list_id)]}})
    r.raise_for_status()
    cid = r.json()["id"]
    requests.post(f"{API}/emailCampaigns/{cid}/sendNow", headers=h, timeout=60).raise_for_status()
    print(f"inviata campagna {cid}: {subject}")
    return True


def main() -> None:
    site = load_json(ROOT / "config" / "site.json", {})
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shop import merged_sponsors
    sponsors = merged_sponsors()
    nl_sponsor = (sponsors.get("_newsletter") or [None])[0]
    latest = load_json(ROOT / "data" / "latest.json", {})
    state = load_json(STATE, {"alerted": {}, "weekly": ""})
    now = datetime.now(ZoneInfo("Europe/Rome"))

    # allerta: solo località nuove o non avvisate nelle ultime 48 ore
    fresh = []
    for a in latest.get("alerts", []):
        last = state["alerted"].get(a["slug"])
        if not last or now - datetime.fromisoformat(last) > timedelta(hours=48):
            fresh.append(a)
    if fresh:
        names = ", ".join(a["name"].split(" · ")[0] for a in fresh)
        sent = send(f"Allerta neve: {names}",
             email_html(site, "Neve in arrivo nelle prossime 72 ore", [f"{a['name']}: {a['title']}" for a in fresh],
                        nl_sponsor), site)
        for a in fresh if sent else []:
            state["alerted"][a["slug"]] = now.isoformat()

    # riepilogo del giovedì, una volta sola, dopo le 7
    week = now.strftime("%G-W%V")
    if now.weekday() == 3 and now.hour >= 7 and state.get("weekly") != week:
        if send("Neve sull'Appennino: il punto per il weekend",
                email_html(site, "Il punto del giovedì", [latest.get("overview", "")], nl_sponsor), site):
            state["weekly"] = week

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
