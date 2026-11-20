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


# ---------- grafica della mail (HTML compatibile con i client di posta: tabelle e stili in linea) ----------
# Inter è il carattere più vicino al San Francisco di Apple; sui dispositivi Apple si usa direttamente quello di sistema
FONT = "'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Helvetica Neue',Helvetica,Arial,sans-serif"
COL = {"green": ("#e7f7ee", "#127a43"), "yellow": ("#fff5d9", "#8a5a00"), "red": ("#fdecec", "#a32d2d")}
E_ = html.escape
GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def _shell(site: dict, preheader: str, inner: str, sponsor: dict | None) -> str:
    base = site["base_url"]
    sp = ""
    if sponsor:
        sp = (f"<tr><td style='padding:0 28px 22px'><table width='100%' style='background:#f4f7fb;border-radius:14px'>"
              f"<tr><td style='padding:14px 16px;font-size:13px;color:#51607a'>Con il supporto di "
              f"<a href='{E_(sponsor['url'])}' style='color:#0f2236;font-weight:700;text-decoration:none'>{E_(sponsor['name'])}</a>"
              f"{' · ' + E_(sponsor.get('tagline', '')) if sponsor.get('tagline') else ''}</td></tr></table></td></tr>")
    social = []
    if site.get("social", {}).get("telegram"):
        social.append(f"<a href='{site['social']['telegram']}' style='color:#2563eb;text-decoration:none'>Telegram</a>")
    if site.get("social", {}).get("whatsapp"):
        social.append(f"<a href='{site['social']['whatsapp']}' style='color:#2563eb;text-decoration:none'>WhatsApp</a>")
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        f"<link href='https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap' rel='stylesheet'>"
        f"<style>body,table,td,p,a,h1,h2,div,span{{font-family:{FONT} !important}}h1,h2{{letter-spacing:-.02em}}</style></head>"
        f"<body style='margin:0;padding:0;background:#eef3f9;-webkit-font-smoothing:antialiased'>"
        f"<div style='display:none;max-height:0;overflow:hidden'>{E_(preheader)}</div>"
        f"<table width='100%' cellpadding='0' cellspacing='0' style='background:#eef3f9;font-family:{FONT}'><tr><td align='center' style='padding:24px 12px'>"
        f"<table width='600' cellpadding='0' cellspacing='0' style='max-width:600px;width:100%;background:#ffffff;border-radius:22px;overflow:hidden'>"
        f"<tr><td style='background:#0f2236;padding:20px 28px'><table width='100%'><tr>"
        f"<td><img src='{base}/static/brand/telegram-640.png' width='40' height='40' alt='' style='border-radius:10px;vertical-align:middle'>"
        f"<span style='color:#ffffff;font-size:20px;font-weight:800;vertical-align:middle;margin-left:10px'>Crinale</span>"
        f"<span style='color:#9db7d6;font-size:12px;letter-spacing:.12em;vertical-align:middle;margin-left:6px'>APPENNINO</span></td>"
        f"</tr></table></td></tr>"
        f"{inner}{sp}"
        f"<tr><td style='padding:18px 28px 26px;border-top:1px solid #eef2f7;font-size:12px;line-height:1.6;color:#8391a7'>"
        f"Ricevi questa mail perché ti sei iscritto su <a href='{base}/' style='color:#8391a7'>crinaleappennino.it</a>."
        f"{' Seguici anche su ' + ' e '.join(social) + '.' if social else ''}<br>"
        f"Previsioni automatiche e indicative: per impianti, piste e innevamento fanno fede i comunicati ufficiali dei gestori. "
        f"<a href='{{{{ unsubscribe }}}}' style='color:#8391a7'>Cancella l'iscrizione</a></td></tr>"
        f"</table></td></tr></table></body></html>")


def _btn(url: str, label: str, primary: bool = True) -> str:
    bg, fg = ("#2563eb", "#ffffff") if primary else ("#eef3fb", "#1d4ed8")
    return (f"<a href='{url}' style='display:inline-block;background:{bg};color:{fg};font-weight:700;font-size:15px;"
            f"padding:12px 20px;border-radius:999px;text-decoration:none;margin:4px 8px 4px 0'>{E_(label)}</a>")


def weekly_html(site: dict, latest: dict, sponsor: dict | None) -> tuple[str, str]:
    base = site["base_url"]
    now = datetime.now(ZoneInfo("Europe/Rome"))
    art = latest.get("article") or {}
    title = art.get("title") or "Il weekend in Appennino"
    brief = art.get("brief") or ([latest["overview"]] if latest.get("overview") else [])
    hero = (f"<tr><td style='padding:28px 28px 8px'>"
            f"<p style='margin:0 0 6px;font-size:13px;font-weight:700;letter-spacing:.06em;color:#2563eb;text-transform:uppercase'>"
            f"{GIORNI[now.weekday()].capitalize()} {now.day} {MESI[now.month - 1]}</p>"
            f"<h1 style='margin:0 0 14px;font-size:27px;line-height:1.18;color:#0f1b2d;font-weight:700;letter-spacing:-.02em'>{E_(title)}</h1>"
            + "".join(f"<p style='margin:0 0 10px;font-size:16px;line-height:1.5;color:#2c3a50'>{E_(b)}</p>" for b in brief[:4])
            + "</td></tr>")
    # weekend località per località
    rows = ""
    for L in latest.get("locs", []):
        wk = L.get("weekend") or {}
        bg, fg = COL.get(wk.get("color"), ("#f1f4f8", "#51607a"))
        days = " · ".join(f"{d['name']} {('🟢' if d['color'] == 'green' else '🟡' if d['color'] == 'yellow' else '🔴')}"
                          for d in wk.get("days", []))
        rows += (f"<tr><td style='padding:12px 0;border-bottom:1px solid #eef2f7'>"
                 f"<a href='{base}/{L['slug']}/' style='text-decoration:none'>"
                 f"<span style='font-size:16px;font-weight:800;color:#0f1b2d'>{E_(L['name'].split(' · ')[0])}</span></a>"
                 + (f"<span style='display:inline-block;margin-left:8px;background:{bg};color:{fg};font-size:12px;font-weight:700;"
                    f"padding:3px 10px;border-radius:999px'>{E_(wk.get('title', ''))}</span>" if wk.get("title") else "")
                 + f"<div style='font-size:14px;line-height:1.45;color:#45536a;margin-top:4px'>{E_(L['title'])}</div>"
                 + (f"<div style='font-size:12px;color:#8391a7;margin-top:3px'>{days}</div>" if days else "")
                 + "</td></tr>")
    weekend = (f"<tr><td style='padding:18px 28px 6px'><h2 style='margin:0 0 4px;font-size:20px;color:#0f1b2d;font-weight:700;letter-spacing:-.01em'>"
               f"🏔️ Il weekend, località per località</h2><table width='100%' cellpadding='0' cellspacing='0'>{rows}</table></td></tr>")
    # prossime settimane
    cards = ""
    for p in (latest.get("phases") or [])[1:]:
        c = p.get("card") or {}
        tag = c.get("tag")
        cards += (f"<tr><td style='padding:6px 0'><table width='100%' style='background:#f6f9fd;border-radius:16px'><tr>"
                  f"<td width='52' style='font-size:30px;padding:12px 0 12px 14px;vertical-align:top'>{c.get('emoji', '')}</td>"
                  f"<td style='padding:12px 14px 12px 6px'><div style='font-size:12px;color:#8391a7;font-weight:700'>"
                  f"{E_(p['from'])} – {E_(p['to'])}</div>"
                  f"<div style='font-size:16px;font-weight:800;color:#0f1b2d;margin:2px 0'>{E_(c.get('head', ''))}</div>"
                  + (f"<div style='font-size:13px;color:#1d5fd1;font-weight:700'>{E_(tag[1])}</div>" if tag else "")
                  + f"<div style='font-size:12px;color:#51607a;margin-top:4px'>🎿 neve alle stazioni {p['snow_low']}/100 · "
                    f"🏔️ in quota {p['snow']}/100 · 🥶 freddo {p['cold']}/100</div></td></tr></table></td></tr>")
    trend = (f"<tr><td style='padding:18px 28px 6px'><h2 style='margin:0 0 8px;font-size:20px;color:#0f1b2d;font-weight:700;letter-spacing:-.01em'>"
             f"📈 Le prossime settimane</h2><table width='100%' cellpadding='0' cellspacing='0'>{cards}</table></td></tr>") if cards else ""
    cta = (f"<tr><td style='padding:20px 28px 26px'>{_btn(base + '/', 'Apri le previsioni')}"
           + (_btn(f"{base}/tendenze/{art['date']}/", 'Leggi l’analisi completa', False) if art.get("date") else "")
           + "</td></tr>")
    pre = brief[0] if brief else title
    return title, _shell(site, pre, hero + weekend + trend + cta, sponsor)


def alert_html(site: dict, fresh: list, sponsor: dict | None) -> str:
    base = site["base_url"]
    rows = "".join(
        f"<tr><td style='padding:12px 0;border-bottom:1px solid #eef2f7'><a href='{base}/{a['slug']}/' style='text-decoration:none;"
        f"font-size:17px;font-weight:800;color:#0f1b2d'>{E_(a['name'].split(' · ')[0])}</a>"
        f"<div style='font-size:15px;line-height:1.45;color:#2c3a50;margin-top:4px'>{E_(a['title'])}</div></td></tr>"
        for a in fresh)
    inner = (f"<tr><td style='padding:28px 28px 8px'><p style='margin:0 0 6px;font-size:13px;font-weight:700;"
             f"letter-spacing:.06em;color:#2563eb;text-transform:uppercase'>Allerta neve</p>"
             f"<h1 style='margin:0 0 10px;font-size:27px;line-height:1.18;color:#0f1b2d;font-weight:700;letter-spacing:-.02em'>❄️ Ci siamo: arriva la neve</h1>"
             f"<p style='margin:0;font-size:16px;line-height:1.5;color:#2c3a50'>Nelle prossime 72 ore è attesa neve in queste località:</p></td></tr>"
             f"<tr><td style='padding:6px 28px'><table width='100%' cellpadding='0' cellspacing='0'>{rows}</table></td></tr>"
             f"<tr><td style='padding:20px 28px 26px'>{_btn(base + '/', 'Guarda quota per quota')}</td></tr>")
    return _shell(site, "Neve in arrivo entro 72 ore", inner, sponsor)


def send(subject: str, body: str, site: dict) -> bool:
    key, list_id, sender = (os.environ.get(k, "").strip() for k in ("BREVO_API_KEY", "BREVO_LIST_ID", "SENDER_EMAIL"))
    nl = site.get("newsletter", {})
    list_id = list_id or str(nl.get("brevo_list_id", ""))   # non segreti: anche in config/site.json
    sender = sender or nl.get("sender_email", "")
    if not (key and list_id and sender):
        print("Brevo non configurato: nessun invio.")
        return False
    h = {"api-key": key, "content-type": "application/json", "accept": "application/json"}
    r = requests.post(f"{API}/emailCampaigns", headers=h, timeout=60, json={
        "name": f"{subject} {datetime.now():%Y-%m-%d %H:%M}", "subject": subject,
        "sender": {"name": site["name"], "email": sender}, "htmlContent": body,
        "recipients": {"listIds": [int(list_id)]}})
    if r.status_code == 401:
        print("Brevo: chiave rifiutata (401):", r.text[:200], "— Controlla la chiave API e, in Brevo > Sicurezza, "
              "che il blocco degli IP non autorizzati sia disattivato. Nessun invio.")
        return False
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
    if not 7 <= now.hour < 22:  # di notte niente email: l'allerta parte al primo giro del mattino
        fresh = []
    if fresh:
        names = ", ".join(a["name"].split(" · ")[0] for a in fresh)
        sent = send(f"❄️ Arriva la neve: {names}" if len(fresh) < 3 else f"❄️ Nevica su tutto il crinale: {names}",
                    alert_html(site, fresh, nl_sponsor), site)
        for a in fresh if sent else []:
            state["alerted"][a["slug"]] = now.isoformat()

    # riepilogo del giovedì, una volta sola, dopo le 7
    week = now.strftime("%G-W%V")
    if now.weekday() == 3 and now.hour >= 7 and state.get("weekly") != week:
        title, body = weekly_html(site, latest, nl_sponsor)
        if send(f"🏔️ {title}", body, site):
            state["weekly"] = week

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))


if __name__ == "__main__":
    main()
