"""Pubblicazione automatica sul canale Telegram.

- Ogni mattina (dopo le 7, una volta al giorno): il punto della giornata, località per località.
- Quando scatta un'allerta neve (≥ soglia in 72 h): un post subito, al massimo uno ogni 48 ore per località.

Serve il segreto TELEGRAM_BOT_TOKEN (il bot va aggiunto come amministratore del canale) e il nome del
canale in config/site.json → telegram_chat (es. "@crinaleappennino"). Senza token non pubblica nulla.
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


def load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def post(token: str, chat: str, text: str) -> bool:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
        "chat_id": chat, "text": text, "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}})
    if not r.ok:
        print("Telegram:", r.status_code, r.text[:200])
    return r.ok


def e(s: str) -> str:
    return html.escape(s or "", quote=False)


def daily_text(site: dict, latest: dict, sponsor: dict | None) -> str:
    base = site["base_url"]
    lines = [f"<b>☀️ Buongiorno dal crinale</b>" if latest.get("summer") else "<b>❄️ Buongiorno dal crinale</b>", ""]
    if latest.get("overview"):
        lines += [e(latest["overview"]), ""]
    for L in latest.get("locs", []):
        name = L["name"].split(" · ")[0]
        if latest.get("summer"):
            extra = f" · rientro entro le {L['back_by']}" if L.get("back_by") else ""
            lines.append(f"• <a href=\"{base}/{L['slug']}/\">{e(name)}</a>: {e(L.get('verdict') or '')}{extra}")
        else:
            lines.append(f"• <a href=\"{base}/{L['slug']}/\">{e(name)}</a>: {e(L['title'])}")
    lines += ["", f"👉 <a href=\"{base}/\">Tutte le previsioni quota per quota</a>"]
    if sponsor:
        lines.append(f"🤝 Con il supporto di <a href=\"{e(sponsor['url'])}\">{e(sponsor['name'])}</a>")
    return "\n".join(lines)


def alert_text(site: dict, fresh: list[dict], sponsor: dict | None) -> str:
    base = site["base_url"]
    lines = ["<b>🚨 Allerta neve: ci siamo!</b>", ""]
    for a in fresh:
        lines.append(f"• <a href=\"{base}/{a['slug']}/\">{e(a['name'].split(' · ')[0])}</a>: {e(a['title'])}")
    lines += ["", f"👉 <a href=\"{base}/\">Dettagli quota per quota</a>"]
    if sponsor:
        lines.append(f"🤝 Con il supporto di <a href=\"{e(sponsor['url'])}\">{e(sponsor['name'])}</a>")
    return "\n".join(lines)


def main() -> None:
    site = load(ROOT / "config" / "site.json", {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT", "").strip() or site.get("telegram_chat", "")
    if not (token and chat):
        print("Telegram non configurato: nessun post.")
        return
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from shop import merged_sponsors
    sponsor = (merged_sponsors().get("_newsletter") or [None])[0]
    latest = load(ROOT / "data" / "latest.json", {})
    state = load(STATE, {})
    tg = state.setdefault("telegram", {"daily": "", "alerted": {}})
    now = datetime.now(ZoneInfo("Europe/Rome"))

    fresh = [a for a in latest.get("alerts", [])
             if not tg["alerted"].get(a["slug"])
             or now - datetime.fromisoformat(tg["alerted"][a["slug"]]) > timedelta(hours=48)]
    if fresh and post(token, chat, alert_text(site, fresh, sponsor)):
        for a in fresh:
            tg["alerted"][a["slug"]] = now.isoformat()

    # logo e descrizione del canale: si aggiornano da soli quando cambia la versione in config/site.json
    brand = site.get("telegram_brand_version", "")
    if brand and tg.get("brand") != brand:
        api = f"https://api.telegram.org/bot{token}"
        with open(ROOT / "static" / "brand" / "telegram-640.png", "rb") as f:
            ok = requests.post(f"{api}/setChatPhoto", data={"chat_id": chat}, files={"photo": f}, timeout=60).ok
        requests.post(f"{api}/setChatDescription", timeout=30, json={
            "chat_id": chat, "description": "Previsioni neve e meteo in quota sull'Appennino tosco-emiliano: "
            "il punto ogni mattina e l'allerta appena arriva la neve. " + site["base_url"]})
        if ok:
            tg["brand"] = brand

    today = now.date().isoformat()
    if now.hour >= 7 and tg.get("daily") != today and post(token, chat, daily_text(site, latest, sponsor)):
        tg["daily"] = today

    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
