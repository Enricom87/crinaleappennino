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


def local_snow(locs: list[dict], today: str) -> dict | None:
    """Nei prossimi 5 giorni comandano i modelli ad alta risoluzione della previsione locale:
    trova il giorno con più neve prevista in vetta e dove."""
    best = None
    for L in locs or []:
        if not L.get("pts"):
            continue
        top = max(L["pts"], key=lambda p: p["elev"])
        for d in top["days"][:5]:
            cm = d.get("snow") or 0
            if cm >= 3 and (best is None or cm > best["cm"]):
                best = {"date": d["date"], "cm": round(cm), "where": top["name"], "elev": top["elev"]}
    return best


def compose(tv: dict, synv: dict, bestpick: list, today: str, locs: list | None = None) -> dict | None:
    if not tv or not tv.get("phases"):
        return None
    ph = tv["phases"]
    ls = local_snow(locs, today)
    top = max(ph[:3], key=lambda p: p["snow"])
    cold = max((p for p in ph if p.get("cold_tail", 0) >= 15), key=lambda p: p["cold_tail"], default=None)
    if top["snow"] >= 50 and top.get("snow_low", 0) >= 30:
        title = T("Neve fino alle stazioni tra {a} e {b}: {k} modelli su {n} ci credono",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 50:
        title = T("Neve in quota tra {a} e {b}: {k} modelli su {n} ci credono, sotto rischia di essere pioggia",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 25:
        title = T("Qualche spiraglio di neve tra {a} e {b}", a=top["from"], b=top["to"])
    elif ls and cold:
        title = T("Neve in vetta {d}, poi un segnale di freddo verso {c}: cosa aspettarsi nelle prossime settimane",
                  d=nice_date(ls["date"]), c=cold["cold_day"])
    elif cold:
        title = T("Neve ancora lontana, ma un segnale di freddo verso {c}: cosa aspettarsi nelle prossime settimane",
                  c=cold["cold_day"])
    elif ls:
        title = T("Neve in vetta {d}, poi niente di serio: cosa aspettarsi nelle prossime settimane",
                  d=nice_date(ls["date"]))
    else:
        title = T("Niente neve seria all'orizzonte: cosa aspettarsi nelle prossime settimane")
    lead = []
    if ls:
        lead.append(T("Per i prossimi giorni comandano i modelli ad alta risoluzione: vedono una nevicata {d}, "
                      "circa {cm} cm a {w} ({e} m). È un episodio breve, da confermare nei prossimi aggiornamenti.",
                      d=nice_date(ls["date"]), cm=ls["cm"], w=ls["where"], e=ls["elev"]))
    lead += [tv["head"] if not ls else (T("Oltre quell'episodio, lo sguardo lungo dei modelli globali non vede altra neve seria.") if not cold else
                  T("Oltre quell'episodio niente neve seria per ora, ma una parte degli scenari porta aria fredda verso {c}: è il segnale da seguire nei prossimi aggiornamenti.", c=cold["cold_day"])),
            T("Abbiamo messo insieme {sc} scenari da {n} modelli meteo diversi, fino a {u}.",
              sc=tv["nscen"], n=tv["nmodels"], u=tv["until"])]
    if synv and synv.get("head"):
        lead.append(synv["head"])

    phases = []
    for p in ph:
        txt = T("Dal {a} al {b}: prevale {type} ({sh} scenari su 100). Neve: {w} ({p} su 100). "
                "Temperatura tipica in quota intorno a {t} °C, affidabilità {c}.",
                a=p["from"], b=p["to"], type=low(p["type"]), sh=p["share"],
                w=prob_word(p["snow"]), p=p["snow"], t=p["t50"], c=p["conf"])
        if p["nmodels"]:
            txt += " " + (T("Nessun modello dà la neve almeno a 30 scenari su 100.") if p["agree"] == 0 else
                          T("{k} modelli su {n} danno la neve ad almeno 30 scenari su 100.", k=p["agree"], n=p["nmodels"]))
        if p.get("best"):
            txt += " " + T("Il giorno più promettente per la neve è {d}.", d=p["best"])
        if p.get("cold_tail", 0) >= 10:
            txt += " " + T("Occhio al freddo: in {c} scenari su 100 a 1500 m si scende sotto −2 °C (i più freddi fino a {t} °C), "
                           "soprattutto intorno a {d}.", c=p["cold_tail"], t=p["tmin10"], d=p["cold_day"])
        if p is ph[0] and ls and p["snow"] < 25:
            txt += " " + T("I modelli globali, a maglie larghe, non colgono la nevicata in vetta di {d} che vedono "
                           "quelli ad alta risoluzione: in questi casi fidati della previsione locale.",
                           d=nice_date(ls["date"]))
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

    sl = next((L.get("snowline") for L in (locs or []) if L.get("slug") == "abetone" and L.get("snowline")), None)
    pros = []
    wet = [d for d in (sl or []) if not d["dry"] and d["lv"]]
    if wet:
        pros.append(T("La nostra stima della quota neve sul crinale nei giorni con precipitazioni: {l}.",
                      l=", ".join(f"{d['name']} {d['lv']} m" for d in wet)))
        low_ = min(wet, key=lambda d: d["lv"])
        if low_["lv"] <= 1500:
            pros.append(T("Il giorno più interessante è {d}: con la neve intorno ai {lv} m si imbiancano anche le stazioni.",
                          d=low_["name"], lv=low_["lv"]))
        else:
            pros.append(T("Quote ancora alte: la neve, se arriva, resta sopra i {lv} m.", lv=low_["lv"]))
    return {"date": today, "title": title, "lead": lead, "phases": phases, "models": models, "pros": pros,
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
