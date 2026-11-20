"""Primi 5 giorni (0–120 h) delle 11 località dal motore fisico-statistico (appennino_engine.py).

Il motore lavora su quota base e cima di ogni località. Il sito ha punti a quote diverse (es. Val di
Luce 1540 m tra Abetone 1388 m e Gomito 1892 m): per ogni punto rifacciamo il calcolo del motore alla
quota del punto, sulla risposta Open-Meteo della sua località (data/raw/engine_raw.json):
- punto più alto della località → blocco «cima» (con erosione del vento se la cresta è esposta);
- altri punti → blocco «base» (cuscinetto freddo solo per il punto più basso delle valli chiuse).
Sostituisce neve, pioggia, quota neve e raffiche dei giorni 0–4 e delle ore della striscia oraria.
Restano dal calcolo di prima temperature, nuvole e temporali; le tendenze oltre il 5° giorno non cambiano.
La neve del metodo precedente resta in per_model["Crinale v1"]: la pagella confronta i due."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import appennino_engine as eng

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "engine_raw.json"
OUT = ROOT / "data" / "raw" / "engine.json"
DAYS = 5
CONCHE = {"val-di-luce"}  # conche chiuse che non sono il punto più basso della località (cuscinetto freddo)


ROADS: dict[str, list[str]] = {}  # slug -> giorni con neve possibile su strada alla quota della stazione/passo
QUALITY: dict[str, dict] = {}  # slug -> qualità della neve prevista in cima nei primi 5 giorni


def quality(r: dict, cfg: dict, today: str) -> dict | None:
    """Che neve sarà, dalle ore di nevicata in cima: densità (SLR, che il motore ricava dal bulbo umido),
    vento durante la nevicata e settore del flusso. Solo se cadono almeno 2 cm."""
    rows = [h for h in r["orario"] if h["time"][:10] >= today and (h["cima"]["neve_cm"] or 0) > 0][:24 * DAYS]
    cm = sum(h["cima"]["neve_cm"] for h in rows)
    if cm < 2:
        return None
    slr = sum(h["cima"]["slr"] * h["cima"]["neve_cm"] for h in rows) / cm
    gust = max((h["cima"]["raffica_kmh"] or 0) for h in rows)
    lib = sum(h["cima"]["neve_cm"] for h in rows if h.get("settore_850") == "libeccio") / cm
    if gust >= 60 and cfg.get("is_cresta_esposta"):
        key, label = "vento", "🌬️ Ventata in cresta"
    elif slr >= 12:
        key, label = "polvere", "✨ Farinosa, polvere"
    elif slr >= 9:
        key, label = "asciutta", "❄️ Asciutta e leggera"
    elif lib >= 0.5:
        key, label = "pesante", "💧 Pesante, da Libeccio"
    else:
        key, label = "umida", "💧 Umida e pesante"
    return {"key": key, "label": label, "slr": round(slr, 1), "gust": round(gust)}


def load() -> dict:
    try:
        return json.loads(RAW.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _run(code: str, raw, elev: float, cresta: bool, valle: bool) -> dict:
    cfg = copy.deepcopy(eng.LOCALITA_CONFIG[code])
    cfg.update(quota_base=elev, quota_cima=elev, is_cresta_esposta=cresta, is_valle_chiusa=valle)
    key = f"_pt_{code}_{int(elev)}_{int(cresta)}_{int(valle)}"
    eng.LOCALITA_CONFIG[key] = cfg
    try:
        return eng.elabora_localita(key, raw)
    finally:
        eng.LOCALITA_CONFIG.pop(key, None)


def apply(base_locs: list[dict], pts: dict, cal: dict, today: str) -> dict:
    """Aggiorna pts in place. Ritorna {slug: giornaliero del motore per base e cima della località}."""
    raw_all = load()
    if not raw_all:
        print("motore fisico: nessun dato, resta il calcolo di prima")
        return {}
    acc: dict[str, list[dict]] = {}  # pid -> uscite del motore (un punto in comune a più località: media)
    per_loc = {}
    for loc in base_locs:
        code = loc["slug"].replace("-", "_")
        raw = raw_all.get(code)
        if raw is None or code not in eng.LOCALITA_CONFIG:
            continue
        cfg = eng.LOCALITA_CONFIG[code]
        try:
            per_loc[loc["slug"]] = eng.elabora_localita(code, raw)
        except Exception as e:  # noqa: BLE001
            print(f"motore fisico: {loc['slug']} saltata ({e})")
            continue
        ids = loc["points"]
        for j, pid in enumerate(ids):
            if pid not in pts:
                continue
            top = j == len(ids) - 1 and len(ids) > 1
            try:
                r = _run(code, raw, pts[pid]["elev"], cresta=top and cfg["is_cresta_esposta"],
                         valle=not top and cfg["is_valle_chiusa"] and (j == 0 or pid in CONCHE))
            except Exception as e:  # noqa: BLE001
                print(f"motore fisico: {pid} saltato ({e})")
                continue
            f = (cal.get(loc["slug"]) or {}).get("snow", 1.0)
            acc.setdefault(pid, []).append({"r": r, "blk": "cima" if top else "base", "f": f})
    n = 0
    for pid, outs in acc.items():
        p = pts[pid]
        days = {d["date"]: d for d in p["days"]}
        hours = {h["time"]: h for h in p.get("hours", [])}
        # giorni
        by_day: dict[str, list] = {}
        for o in outs:
            for g in o["r"]["giornaliero"]:
                by_day.setdefault(g["data"], []).append((g, o["blk"], o["f"]))
        for date_, lst in by_day.items():
            d = days.get(date_)
            if d is None or d["idx"] >= DAYS:
                continue
            k = len(lst)
            snow = sum(g[b]["neve_cm"] * f for g, b, f in lst) / k
            rain = sum(g["precip_mm"] for g, _, _ in lst) / k
            gust = [g[b]["raffica_max_kmh"] for g, b, _ in lst if g[b]["raffica_max_kmh"] is not None]
            qn = [g["quota_neve_media_m"] for g, _, _ in lst if g["quota_neve_media_m"] is not None]
            qmin = [g["quota_neve_min_m"] for g, _, _ in lst if g["quota_neve_min_m"] is not None]
            d.setdefault("per_model", {})["Crinale v1"] = d.get("snow", 0)
            d["snow"] = round(snow, 1)
            d["snow_min"] = round(min(d.get("snow_min", snow), snow), 1)
            d["snow_max"] = round(max(d.get("snow_max", snow), snow), 1)
            d["precip"] = round(rain, 1)
            if gust:
                d["gust"] = round(max(gust))
            d["engine"] = {"qn": round(sum(qn) / len(qn)) if qn else None,
                           "qn_min": min(qmin) if qmin else None,
                           "snow": round(snow, 1), "gust": round(max(gust)) if gust else None}
            n += 1
        # ore (striscia delle prossime 48 h)
        for o in outs:
            col = o["r"]["orario"]
            for h in col:
                hr = hours.get(h["time"])
                if hr is None:
                    continue
                pr = h["precip_mm"] or 0
                sn = (h[o["blk"]]["neve_cm"] or 0) * o["f"]
                hr["precip"] = round(pr, 1)
                hr["snow"] = round(sn, 1)
                hr["rain"] = round(pr if sn == 0 else max(pr - sn / max(h[o["blk"]]["slr"] or 10, 1) * 10, 0), 1)
                if h[o["blk"]]["raffica_kmh"] is not None:
                    hr["gust"] = round(h[o["blk"]]["raffica_kmh"])
            break  # per le ore basta la prima località che contiene il punto
    print(f"motore fisico: {len(acc)} punti, {n} giorni-punto dai primi {DAYS} giorni")
    QUALITY.clear()
    ROADS.clear()
    for slug, r in per_loc.items():
        # neve su strada: un'ora con almeno 1 mm/h e quota neve alla quota della base (stazione o passo) o più giù
        qb = eng.LOCALITA_CONFIG[slug.replace("-", "_")]["quota_base"]
        days_ = sorted({h["time"][:10] for h in r["orario"] if h["time"][:10] >= today and (h["precip_mm"] or 0) >= 1
                        and h["quota_neve_m"] is not None and h["quota_neve_m"] <= qb})
        if days_:
            ROADS[slug] = days_[:DAYS]
        q = quality(r, eng.LOCALITA_CONFIG[slug.replace("-", "_")], today)
        if q:
            QUALITY[slug] = q
    return {slug: [{"date": g["data"], "qn": g["quota_neve_media_m"], "qn_min": g["quota_neve_min_m"],
                    "base": g["base"]["neve_cm"], "top": g["cima"]["neve_cm"],
                    "gust": g["cima"]["raffica_max_kmh"], "mm": g["precip_mm"]}
                   for g in r["giornaliero"] if g["data"] >= today][:DAYS]
            for slug, r in per_loc.items()}
