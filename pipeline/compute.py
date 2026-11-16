"""Calcoli: neve stimata, bulbo umido, aggregati giornalieri, probabilità da ensemble,
classificazione della configurazione sinottica."""
from __future__ import annotations

import math
import re
import statistics as st
from collections import defaultdict
from datetime import date, datetime, timedelta

LAM_WEIGHTS = {"italia_meteo_arpae_icon_2i": 2.0, "meteoswiss_icon_ch2": 1.0,
               "icon_d2": 1.0, "meteofrance_arome_france": 1.0}
GLOBAL_MODELS = ["ecmwf_ifs025", "gfs_global", "icon_global"]
MODEL_LABELS = {"italia_meteo_arpae_icon_2i": "ICON-2I", "meteoswiss_icon_ch2": "ICON-CH2",
                "icon_d2": "ICON-D2", "meteofrance_arome_france": "AROME",
                "ecmwf_ifs025": "ECMWF", "gfs_global": "GFS", "icon_global": "ICON"}
LAM_DAYS = 2  # oggi + domani dai LAM, poi globali


# ---------- fisica di base ----------

def snow_fraction(t: float | None, fl: float | None = None, elev: float | None = None) -> float:
    """Frazione nevosa: temperatura a 2 m e, se c'è, quota dello zero termico.

    La neve arriva di norma fino a circa 300 m sotto lo zero termico; tra 300 e 500 m
    sotto è mista. Si prende il valore più prudente tra i due criteri."""
    if t is None:
        return 0.0
    ft = 1.0 if t <= 0.5 else 0.5 if t <= 1.5 else 0.0
    if fl is None or elev is None:
        return ft
    gap = fl - elev
    ff = 1.0 if gap <= 300 else 0.5 if gap <= 500 else 0.0
    return min(ft, ff)


def wet_bulb(t: float | None, rh: float | None) -> float | None:
    """Temperatura di bulbo umido, formula di Stull (2011)."""
    if t is None or rh is None:
        return None
    rh = max(5.0, min(100.0, rh))
    return (t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
            + math.atan(t + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


# ---------- lettura risposte Open-Meteo ----------

def split_models(hourly: dict, models: list[str]) -> dict[str, dict[str, list]]:
    """Restituisce {modello: {variabile: serie}}; gestisce chiavi con e senza suffisso."""
    out: dict[str, dict[str, list]] = {}
    for m in models:
        series = {}
        for k, v in hourly.items():
            if k.endswith("_" + m):
                series[k[: -len(m) - 1]] = v
        if not series and len(models) == 1:
            series = {k: v for k, v in hourly.items() if k != "time"}
        if series and any(x is not None for x in series.get("temperature_2m", [None])):
            out[m] = series
    return out


def split_members(hourly: dict, var: str) -> list[list]:
    pat = re.compile(rf"^{var}(_member\d+)?(_[a-z0-9_]+)?$")
    return [v for k, v in hourly.items() if pat.match(k) and not k.startswith(var + "_8")]


# ---------- aggregati ----------

def _day(ts: str) -> str:
    return ts[:10]


def per_model_daily(times: list[str], s: dict[str, list], elev: float | None = None) -> dict[str, dict]:
    """Aggregati giornalieri per un modello."""
    days: dict[str, dict] = defaultdict(lambda: {"precip": 0.0, "snow": 0.0, "t": [], "fl": [],
                                                 "gust": [], "valid": 0})
    T, P = s.get("temperature_2m", []), s.get("precipitation", [])
    FL, G = s.get("freezing_level_height", []), s.get("wind_gusts_10m", [])
    for i, ts in enumerate(times):
        t = T[i] if i < len(T) else None
        if t is None:
            continue
        d = days[_day(ts)]
        p = (P[i] if i < len(P) else 0) or 0.0
        d["precip"] += p
        fl = FL[i] if i < len(FL) else None
        d["snow"] += p * snow_fraction(t, fl, elev)
        d["t"].append(t)
        d["valid"] += 1
        if i < len(FL) and FL[i] is not None:
            d["fl"].append(FL[i])
        if i < len(G) and G[i] is not None:
            d["gust"].append(G[i])
    out = {}
    for k, d in days.items():
        if d["valid"] < 18:  # giorno incompleto per quel modello
            continue
        out[k] = {"precip": d["precip"], "snow": d["snow"], "tmin": min(d["t"]), "tmax": max(d["t"]),
                  "fl_min": min(d["fl"]) if d["fl"] else None,
                  "gust": max(d["gust"]) if d["gust"] else None}
    return out


def snowmaking_nights(times: list[str], s: dict[str, list]) -> dict[str, dict]:
    """Ore notturne (18-08) con bulbo umido ≤ -2 e ≤ -4 °C; la notte prende la data della sera."""
    T, RH = s.get("temperature_2m", []), s.get("relative_humidity_2m", [])
    nights: dict[str, dict] = defaultdict(lambda: {"tw2": 0, "tw4": 0})
    for i, ts in enumerate(times):
        dt = datetime.fromisoformat(ts)
        if dt.hour >= 18:
            key = dt.date().isoformat()
        elif dt.hour < 8:
            key = (dt.date() - timedelta(days=1)).isoformat()
        else:
            continue
        tw = wet_bulb(T[i] if i < len(T) else None, RH[i] if i < len(RH) else None)
        if tw is None:
            continue
        if tw <= -2:
            nights[key]["tw2"] += 1
        if tw <= -4:
            nights[key]["tw4"] += 1
    return dict(nights)


def blend_point(glob: dict, lam: dict, today: str, elev: float | None = None) -> list[dict]:
    """Tabella giornaliera con valore di consenso e forbice tra modelli."""
    g_models = split_models(glob["hourly"], GLOBAL_MODELS)
    l_models = split_models(lam["hourly"], list(LAM_WEIGHTS)) if lam else {}
    g_daily = {m: per_model_daily(glob["hourly"]["time"], s, elev) for m, s in g_models.items()}
    l_daily = {m: per_model_daily(lam["hourly"]["time"], s, elev) for m, s in l_models.items()} if lam else {}
    nights_src = g_models.get("ecmwf_ifs025") or next(iter(g_models.values()), {})
    nights = snowmaking_nights(glob["hourly"]["time"], nights_src) if nights_src else {}

    all_days = sorted({d for md in g_daily.values() for d in md} | {d for md in l_daily.values() for d in md})
    rows = []
    for i, d in enumerate(all_days):
        if d < today:
            continue
        idx = (date.fromisoformat(d) - date.fromisoformat(today)).days
        lam_vals = {m: v[d] for m, v in l_daily.items() if d in v}
        glob_vals = {m: v[d] for m, v in g_daily.items() if d in v}
        use_lam = idx < LAM_DAYS and lam_vals
        src = lam_vals if use_lam else glob_vals
        if not src:
            continue
        weights = {m: (LAM_WEIGHTS.get(m, 1.0) if use_lam else 1.0) for m in src}


        def wmean(key):
            vals = [(src[m][key], weights[m]) for m in src if src[m][key] is not None]
            if not vals:
                return None
            return sum(v * w for v, w in vals) / sum(w for _, w in vals)

        every = {**glob_vals, **lam_vals}
        snows = [v["snow"] for v in every.values()]
        rows.append({
            "date": d, "idx": idx, "source": "LAM" if use_lam else "globali",
            "models": [MODEL_LABELS.get(m, m) for m in src],
            "snow": round(wmean("snow"), 1), "snow_min": round(min(snows), 1), "snow_max": round(max(snows), 1),
            "precip": round(wmean("precip"), 1), "tmin": round(wmean("tmin"), 1), "tmax": round(wmean("tmax"), 1),
            "fl_min": round(wmean("fl_min")) if wmean("fl_min") is not None else None,
            "gust": round(wmean("gust")) if wmean("gust") is not None else None,
            "tw2": nights.get(d, {}).get("tw2", 0), "tw4": nights.get(d, {}).get("tw4", 0),
            "per_model": {MODEL_LABELS.get(m, m): round(v["snow"], 1) for m, v in every.items()},
        })
    return rows


def ensemble_probs(ens: dict, today: str, elev: float | None = None) -> dict:
    """Probabilità di accumulo (neve stimata) su 72 ore, 7 giorni e tutto l'orizzonte."""
    h = ens["hourly"]
    times = h["time"]
    T = split_members(h, "temperature_2m")
    P = split_members(h, "precipitation")
    FL = split_members(h, "freezing_level_height")
    n = min(len(T), len(P))
    start = datetime.fromisoformat(today + "T00:00")
    windows = {"h72": start + timedelta(hours=72), "d7": start + timedelta(days=7), "all": start + timedelta(days=16)}
    cums = {w: [] for w in windows}
    last_valid = None
    for m in range(n):
        acc = {w: 0.0 for w in windows}
        for i, ts in enumerate(times):
            t, p = T[m][i], P[m][i]
            if t is None or p is None:
                continue
            dt = datetime.fromisoformat(ts)
            if dt < start:
                continue
            last_valid = ts if (last_valid is None or ts > last_valid) else last_valid
            fl = FL[m][i] if m < len(FL) and i < len(FL[m]) else None
            s = p * snow_fraction(t, fl, elev)
            for w, end in windows.items():
                if dt < end:
                    acc[w] += s
        for w in windows:
            cums[w].append(acc[w])
    out = {"members": n, "until": last_valid}
    for w, vals in cums.items():
        if not vals:
            continue
        vals.sort()
        q = lambda p: round(vals[min(len(vals) - 1, int(p * (len(vals) - 1)))], 1)
        out[w] = {"p1": round(100 * sum(v >= 1 for v in vals) / len(vals)),
                  "p10": round(100 * sum(v >= 10 for v in vals) / len(vals)),
                  "p20": round(100 * sum(v >= 20 for v in vals) / len(vals)),
                  "q10": q(0.1), "q50": q(0.5), "q90": q(0.9)}
    return out


# ---------- configurazione sinottica ----------

FLOW_LABELS = [((180, 270), "libeccio/ostro", "stau sul versante toscano"),
               ((270, 360), "maestrale/tramontana", "rovesci sul versante toscano"),
               ((0, 120), "grecale/levante", "stau sul versante emiliano, aria fredda"),
               ((120, 180), "scirocco", "flusso mite da sud-est")]


def flow_of(direction: float | None) -> tuple[str, str]:
    if direction is None:
        return ("n.d.", "")
    d = direction % 360
    for (a, b), name, note in FLOW_LABELS:
        if a <= d < b:
            return name, note
    return ("n.d.", "")


def thermal_class(t850: float | None) -> str:
    if t850 is None:
        return "n.d."
    if t850 <= -3:
        return "favorevole"
    if t850 <= 0:
        return "marginale"
    return "sfavorevole"


def synoptic_days(syn: dict, today: str) -> list[dict]:
    c = syn["center"]["hourly"]
    w = syn["west"]["hourly"]
    e = syn["east"]["hourly"]
    times = c["time"]
    by_day: dict[str, list[int]] = defaultdict(list)
    for i, ts in enumerate(times):
        if ts[:10] >= today:
            by_day[ts[:10]].append(i)
    rows = []
    for d, idxs in sorted(by_day.items()):
        row = {"date": d}
        for m, lab in (("ecmwf_ifs025", "ec"), ("gfs_global", "gfs")):
            T = c.get(f"temperature_850hPa_{m}") or []
            D = c.get(f"wind_direction_700hPa_{m}") or []
            P = c.get(f"precipitation_{m}") or []
            Z = c.get(f"geopotential_height_500hPa_{m}") or []
            ZW = w.get(f"geopotential_height_500hPa_{m}") or []
            ZE = e.get(f"geopotential_height_500hPa_{m}") or []
            wet = [i for i in idxs if i < len(P) and (P[i] or 0) >= 0.3]
            sel = wet or idxs
            tv = [T[i] for i in sel if i < len(T) and T[i] is not None]
            dv = [D[i] for i in sel if i < len(D) and D[i] is not None]
            if not tv:
                continue
            t850 = round(st.mean(tv), 1)
            # media vettoriale della direzione
            sx = sum(math.sin(math.radians(x)) for x in dv)
            cx = sum(math.cos(math.radians(x)) for x in dv)
            direction = round(math.degrees(math.atan2(sx, cx)) % 360) if dv else None
            noon = idxs[min(len(idxs) - 1, 12)]
            zs = {"west": ZW[noon] if noon < len(ZW) else None, "center": Z[noon] if noon < len(Z) else None,
                  "east": ZE[noon] if noon < len(ZE) else None}
            trough = None
            if all(v is not None for v in zs.values()):
                trough = min(zs, key=zs.get)
            flow, note = flow_of(direction)
            row[lab] = {"t850": t850, "dir": direction, "flow": flow, "flow_note": note,
                        "thermal": thermal_class(t850), "trough": trough,
                        "precip": round(sum((P[i] or 0) for i in idxs if i < len(P)), 1)}
        if "ec" in row or "gfs" in row:
            rows.append(row)
    return rows


def name_configuration(row: dict) -> str:
    """Nome della configurazione tipica (euristica dichiarata)."""
    r = row.get("ec") or row.get("gfs")
    if not r or r["precip"] < 1:
        return "tempo asciutto"
    flow, th, tr = r["flow"], r["thermal"], r["trough"]
    if flow == "libeccio/ostro" and th in ("favorevole", "marginale"):
        return "libeccio su aria fredda"
    if flow == "libeccio/ostro":
        return "libeccio mite"
    if flow == "grecale/levante" and tr in ("center", "east"):
        return "irruzione fredda da nord-est"
    if flow == "grecale/levante":
        return "minimo sul Tirreno con richiamo orientale"
    if flow == "maestrale/tramontana":
        return "maestrale post-frontale"
    if flow == "scirocco":
        return "scirocco mite"
    return "configurazione mista"
