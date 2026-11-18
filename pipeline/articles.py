"""Articoli «Tendenza»: ogni lunedì e giovedì un pezzo scritto in automatico dai dati del sito
(scenari dei modelli, quota del freddo, weekend, neve misurata), in tutte le lingue.
Ogni articolo è una fotografia: si salva in data/articles/<data>/<lingua>.json e non si riscrive."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cards import prob_word
from i18n import T, nice_date
from verdict import low

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "articles"
OBS = ROOT / "data" / "snowobs.json"
PUB_DAYS = (0, 3)  # lunedì, giovedì


def due(today: str) -> bool:
    now = datetime.now(ZoneInfo("Europe/Rome"))
    exists = (DIR / today).exists()
    first_ever = not DIR.exists() or not any(DIR.iterdir())
    return not exists and (first_ever or (date.fromisoformat(today).weekday() in PUB_DAYS and now.hour >= 6))


def _stations() -> list[dict]:
    try:
        return json.loads(OBS.read_text()).get("stations", [])
    except Exception:  # noqa: BLE001
        return []


def compose(tv: dict, synv: dict, bestpick: list, today: str) -> dict | None:
    if not tv or not tv.get("phases"):
        return None
    ph = tv["phases"]
    top = max(ph[:3], key=lambda p: p["snow"])
    if top["snow"] >= 50 and top.get("snow_low", 0) >= 30:
        title = T("Neve fino alle stazioni tra {a} e {b}: {k} modelli su {n} ci credono",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 50:
        title = T("Neve in quota tra {a} e {b}: {k} modelli su {n} ci credono, sotto rischia di essere pioggia",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 25:
        title = T("Qualche spiraglio di neve tra {a} e {b}", a=top["from"], b=top["to"])
    else:
        title = T("Niente neve seria all'orizzonte: cosa aspettarsi nelle prossime settimane")
    lead = [tv["head"],
            T("Abbiamo messo insieme {sc} scenari da {n} modelli meteo diversi, fino a {u}.",
              sc=tv["nscen"], n=tv["nmodels"], u=tv["until"])]
    if synv and synv.get("head"):
        lead.append(synv["head"])

    phases = []
    for p in ph:
        txt = T("Dal {a} al {b}: prevale {type} ({sh} scenari su 100). Neve: {w} ({p} su 100), "
                "la vedono {k} modelli su {n}. Temperatura tipica in quota intorno a {t} °C, affidabilità {c}.",
                a=p["from"], b=p["to"], type=low(p["type"]), sh=p["share"],
                w=prob_word(p["snow"]), p=p["snow"], k=p["agree"], n=p["nmodels"], t=p["t50"], c=p["conf"])
        if p.get("best"):
            txt += " " + T("Il giorno più promettente per la neve è {d}.", d=p["best"])
        phases.append({"emoji": p["emoji"], "label": p["label"], "text": txt, "color": p["color"]})

    rows = sorted(top["rows"], key=lambda r: -r["snow"])
    models = []
    if rows and rows[0]["snow"] < 20:
        models.append(T("Nessun modello vede neve seria: il più ottimista, {m1}, arriva a {p1} scenari nevosi su 100.",
                        m1=rows[0]["name"], p1=rows[0]["snow"]))
    elif len(rows) >= 2:
        models.append(T("Tra {a} e {b} il modello più convinto è {m1} ({p1} scenari nevosi su 100), "
                        "il più scettico {m2} ({p2}).", a=top["from"], b=top["to"],
                        m1=rows[0]["name"], p1=rows[0]["snow"], m2=rows[-1]["name"], p2=rows[-1]["snow"]))
        models.append(T("Opinioni molto diverse: la previsione può ancora cambiare parecchio.")
                      if rows[0]["snow"] - rows[-1]["snow"] >= 40
                      else T("I modelli vanno abbastanza d'accordo: è un segnale da prendere sul serio."))

    weekend = []
    for b in bestpick or []:
        line = f"{b['name']}: {b['head'].rstrip('.')}."
        if not b.get("tie") and not b.get("red") and b["rows"]:
            line += " " + T("In testa: {l}.", l=", ".join(r["name"] for r in b["rows"][:3]))
        weekend.append(line)

    sts = sorted([s for s in _stations() if s.get("cm", 0) >= 2], key=lambda s: -s["cm"])[:6]
    if sts:
        ground = T("Al suolo, secondo le stazioni ufficiali: {l}.",
                   l=", ".join(T("{cm} cm a {st} ({e} m)", cm=s["cm"], st=s["name"].replace(" Nivo", ""), e=s["elev"])
                            for s in sts))
    else:
        ground = T("Per ora le stazioni ufficiali non misurano neve al suolo significativa.")

    return {"date": today, "title": title, "lead": lead, "phases": phases, "models": models,
            "weekend": weekend, "ground": ground, "chart": tv.get("chart", ""),
            "pub": nice_date(today)}


def save(lang: str, art: dict) -> None:
    d = DIR / art["date"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lang}.json").write_text(json.dumps(art, ensure_ascii=False))


def load_all(lang: str, keep: int = 30) -> list[dict]:
    if not DIR.exists():
        return []
    out = []
    for d in sorted(DIR.iterdir(), reverse=True)[:keep]:
        f = d / f"{lang}.json"
        if not f.exists():
            f = d / "it.json"
        if f.exists():
            out.append(json.loads(f.read_text()))
    return out
