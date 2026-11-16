"""Bollettino per chi va in montagna senza neve: temporali, caldo, zero termico, vento in cresta.

Per ogni punto e giorno, da modelli ad area limitata (oggi e domani) e globali (fino a 5 giorni):
- temporali del pomeriggio: CAPE (energia per la convezione) e pioggia tra le 11 e le 20, quota di modelli d'accordo;
- ora di inizio probabile, e quindi "rientro entro le…";
- temperatura massima, zero termico massimo, raffica massima;
- un giudizio sintetico: ottima / buona / attenzione / sconsigliata.
Tutte le ore sono in ora italiana (le richieste a Open-Meteo usano timezone Europe/Rome).
"""
from __future__ import annotations

from datetime import date
from statistics import median

from compute import GLOBAL_MODELS, LAM_WEIGHTS, split_models

DAYS = 5
LAM_DAYS = 2
PM = range(11, 21)          # ore del pomeriggio in cui nascono i temporali di calore
STORM_LABELS = {0: "assenti", 1: "isolati", 2: "possibili", 3: "probabili"}
VERDICTS = {
    "ottima": "Giornata top",
    "buona": "Si va",
    "attenzione": "Occhio",
    "mattina": "Solo al mattino",
    "sconsigliata": "Meglio di no",
}


def _hours_by_day(times: list[str]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for i, t in enumerate(times):
        out.setdefault(t[:10], []).append(i)
    return out


def _v(s: dict, key: str, i: int):
    arr = s.get(key)
    return arr[i] if arr and i < len(arr) else None


def model_day(times: list[str], s: dict, idx: list[int]) -> dict | None:
    """Indicatori di un modello per un giorno."""
    t = [x for x in (_v(s, "temperature_2m", i) for i in idx) if x is not None]
    if len(t) < 12:
        return None
    pm = [i for i in idx if int(times[i][11:13]) in PM]
    cape_pm = [x for x in (_v(s, "cape", i) for i in pm) if x is not None]
    rain_pm = sum(x for x in (_v(s, "precipitation", i) for i in pm) if x)
    start = None
    for i in pm:
        if (_v(s, "precipitation", i) or 0) >= 0.3 and (_v(s, "cape", i) or 0) >= 200:
            start = int(times[i][11:13])
            break
    day_clouds = [x for x in (_v(s, "cloud_cover", i) for i in idx if 8 <= int(times[i][11:13]) <= 16) if x is not None]
    gusts = [x for x in (_v(s, "wind_gusts_10m", i) for i in idx) if x is not None]
    fls = [x for x in (_v(s, "freezing_level_height", i) for i in idx) if x is not None]
    return {
        "cape": max(cape_pm) if cape_pm else None,
        "rain_pm": rain_pm,
        "rain": sum(x for x in (_v(s, "precipitation", i) for i in idx) if x),
        "start": start,
        "tmax": max(t), "tmin": min(t),
        "gust": max(gusts) if gusts else None,
        "fl_max": max(fls) if fls else None,
        "cloud": sum(day_clouds) / len(day_clouds) if day_clouds else None,
    }


def storm_level(days: list[dict]) -> int:
    """0-3 dal consenso dei modelli. Senza CAPE (modello che non la fornisce) conta solo la pioggia pomeridiana."""
    n = len(days)
    strong = sum(1 for d in days if (d["cape"] or 0) >= 800 and d["rain_pm"] >= 1)
    some = sum(1 for d in days if (d["cape"] or 0) >= 300 and d["rain_pm"] >= 0.5)
    weak = sum(1 for d in days if (d["cape"] or 0) >= 150 and d["rain_pm"] >= 0.2)
    if strong / n >= 0.5:
        return 3
    if some / n >= 0.5 or strong:
        return 2
    if weak or some:
        return 1
    return 0


def verdict(level: int, gust: float | None, rain: float, cloud: float | None) -> str:
    if level >= 3 or (gust or 0) >= 70 or rain >= 10:
        return "sconsigliata"
    if level == 2 or (gust or 0) >= 50 or rain >= 3:
        return "attenzione"
    if level == 1 or (cloud or 0) > 60 or rain >= 0.5:
        return "buona"
    return "ottima"


def mountain_days(glob: dict, lam: dict | None, today: str) -> list[dict]:
    g_models = split_models(glob["hourly"], GLOBAL_MODELS)
    l_models = split_models(lam["hourly"], list(LAM_WEIGHTS)) if lam else {}
    g_hours = _hours_by_day(glob["hourly"]["time"])
    l_hours = _hours_by_day(lam["hourly"]["time"]) if lam else {}
    rows = []
    for d in sorted(g_hours):
        idx_day = (date.fromisoformat(d) - date.fromisoformat(today)).days
        if idx_day < 0 or idx_day >= DAYS:
            continue
        per = []
        if idx_day < LAM_DAYS and d in l_hours:
            per = [x for x in (model_day(lam["hourly"]["time"], s, l_hours[d]) for s in l_models.values()) if x]
        src = "LAM" if per else "globali"
        if not per:
            per = [x for x in (model_day(glob["hourly"]["time"], s, g_hours[d]) for s in g_models.values()) if x]
        if not per:
            continue
        lvl = storm_level(per)
        starts = [p["start"] for p in per if p["start"] is not None]
        start = int(median(starts)) if starts and lvl >= 1 else None
        med = lambda k: median([p[k] for p in per if p[k] is not None]) if any(p[k] is not None for p in per) else None
        gust, rain, cloud = med("gust"), med("rain"), med("cloud")
        v = verdict(lvl, gust, rain or 0, cloud)
        back_by = max(start - 1, 9) if start is not None and lvl >= 2 else None
        if v in ("sconsigliata", "attenzione") and lvl >= 2 and back_by and back_by >= 12 and (gust or 0) < 50:
            v = "mattina"  # il problema sono solo i temporali del pomeriggio
        rows.append({
            "date": d, "idx": idx_day, "source": src,
            "storm": lvl, "storm_label": STORM_LABELS[lvl], "start": start,
            "back_by": back_by,
            "tmax": round(med("tmax")), "tmin": round(med("tmin")),
            "fl_max": round(med("fl_max") / 50) * 50 if med("fl_max") is not None else None,
            "gust": round(gust) if gust is not None else None,
            "rain": round(rain or 0, 1), "cloud": round(cloud) if cloud is not None else None,
            "verdict": v, "verdict_label": VERDICTS[v],
        })
    return rows


def summer_text(loc_name: str, top: dict, rows: list[dict]) -> list[str]:
    """Due o tre frasi per la scheda della località, dal punto più alto."""
    from i18n import T, cap, nice_date
    if not rows:
        return []
    out = []
    t0 = rows[0]
    first = T("{d} in quota ({name}, {z} m): {verdict}", d=cap(nice_date(t0["date"])), name=top["name"],
              z=top["elev"], verdict=T(t0["verdict_label"]).lower())
    if t0["storm"] >= 2 and t0["back_by"]:
        first += T(": temporali {lvl} dal primo pomeriggio, parti presto e rientra entro le {h}",
                   lvl=T(t0["storm_label"]), h=t0["back_by"])
    elif t0["storm"] == 1:
        first += T(", con qualche cumulo pomeridiano che potrebbe scappare in un rovescio")
    if t0["gust"] and t0["gust"] >= 50:
        first += T("; sulle creste il vento soffia fino a {g} km/h", g=t0["gust"])
    out.append(first + T("."))
    good = [r for r in rows[1:] if r["verdict"] == "ottima"]
    bad = [r for r in rows[1:] if r["verdict"] == "sconsigliata"]
    if good:
        out.append(T("Segnati queste date: {dates}, le giornate migliori in arrivo.",
                     dates=", ".join(nice_date(r["date"]) for r in good[:3])))
    if bad:
        out.append(T("Lascia perdere {dates}: meglio un rifugio che una cresta.",
                     dates=", ".join(nice_date(r["date"]) for r in bad[:3])))
    hot = [r for r in rows if r["fl_max"] and r["fl_max"] >= 4000]
    if hot:
        out.append(T("Fa caldo anche lassù: zero termico a {z} m. Borraccia piena e partenza all'alba.", z=hot[0]["fl_max"]))
    return out


def overview_mtn(locs: list[dict]) -> str:
    """Frase per la home nella stagione senza neve: come va oggi in quota, località per località."""
    from i18n import T, cap
    import i18n
    groups: dict[str, list[str]] = {}
    back = []
    for L in locs:
        r = (L.get("mtn") or [None])[0]
        if not r:
            continue
        name = L["name"].split(" · ")[0]
        groups.setdefault(r["verdict"], []).append(name)
        if r["back_by"]:
            back.append(r["back_by"])
    parts = []
    for v in ("ottima", "buona", "mattina", "attenzione", "sconsigliata"):
        if groups.get(v):
            names = ", ".join(groups[v])
            word = {"ottima": "giornata top", "buona": "si va", "mattina": "solo al mattino",
                    "attenzione": "occhio", "sconsigliata": "meglio restare a valle"}[v]
            if i18n.LANG == "it":
                prep = "ad" if names[:1] in "AaEe" else "a"
                parts.append(f"{word} {prep} {names}")
            else:
                parts.append(T("{word}: {names}", word=T(word), names=names))
    if not parts:
        return ""
    s = T("Oggi in quota: {parts}.", parts="; ".join(parts))
    if back:
        s += T(" Dove sono attesi temporali, rientro consigliato entro le {h}.", h=min(back))
    return cap(s)
