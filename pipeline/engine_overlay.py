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
                         valle=j == 0 and cfg["is_valle_chiusa"])
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
    return {slug: [{"date": g["data"], "qn": g["quota_neve_media_m"], "qn_min": g["quota_neve_min_m"],
                    "base": g["base"]["neve_cm"], "top": g["cima"]["neve_cm"],
                    "gust": g["cima"]["raffica_max_kmh"], "mm": g["precip_mm"]}
                   for g in r["giornaliero"] if g["data"] >= today][:DAYS]
            for slug, r in per_loc.items()}
