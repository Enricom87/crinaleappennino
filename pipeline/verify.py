"""Pagella: quanto ci prendiamo, misurato e pubblico.

Ogni giorno (alla prima costruzione utile) archiviamo per sempre in data/verify.json:
- la nostra previsione di neve fresca per domani, dopodomani e tra 3 giorni alla quota della stazione
  di riferimento di ogni località, insieme ai singoli modelli grezzi (ECMWF, ICON-2I, AROME...)
  per confrontarci con chi non corregge niente;
- la quota neve prevista per gli stessi giorni;
- la neve fresca misurata dalle stazioni ufficiali Arpae (CC BY 4.0), giorno per giorno.
Poi calcoliamo i punteggi per anticipo: giorni con neve indovinati, falsi allarmi, nevicate mancate,
errore medio in cm. I giorni asciutti previsti asciutti non contano (sono facili)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from extras import STATION_FOR
from history import measured_new_snow

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "verify.json"
HIST = ROOT / "data" / "history.json"
REPORTS = ROOT / "data" / "reports.json"
SNOWY = 2.0      # cm: da qui in su è «giornata con neve»
RAW = ("ECMWF", "ICON-2I", "AROME", "Crinale v1")
START = "2026-11-18"
MIN_SNOWY = 10   # giornate con neve sotto cui i numeri sono ancora «in costruzione»


def _j(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def ok(f: float, m: float) -> bool:
    """Stessa regola della scheda «Avevamo detto»: entro 3 cm o il 40 %."""
    return (f < SNOWY and m < SNOWY) or abs(f - m) <= max(3, 0.4 * max(f, m))


def record(locs: list[dict], today: str) -> None:
    v = _j(FILE, {"fc": {}, "obs": {}})
    obs_stations = {L["slug"]: STATION_FOR.get(L["slug"]) for L in locs}
    elev_of = {x["name"]: x["elev"] for x in _j(ROOT / "data" / "snowobs.json", {}).get("stations", [])}
    for L in locs:
        st_name = obs_stations.get(L["slug"])
        if not st_name or not L.get("pts"):
            continue
        st_elev = elev_of.get(st_name)
        if st_elev is None:
            continue
        ref = min(L["pts"], key=lambda p: abs(p["elev"] - st_elev))
        fc = v["fc"].setdefault(L["slug"], {})
        if today in fc:
            continue
        days = {}
        for d in ref["days"]:
            if 1 <= d.get("idx", 0) <= 3:
                pm = d.get("per_model") or {}
                days[d["date"]] = {"our": round(d.get("snow") or 0, 1),
                                   "raw": {k: pm[k] for k in RAW if k in pm}}
        fc[today] = {"elev": ref["elev"], "station": st_name, "days": days,
                     "lv": {x["date"]: x["lv"] for x in (L.get("snowline") or []) if x.get("lv")}}
    # previsioni già salvate da history.json prima della pagella (solo la nostra, senza modelli grezzi)
    for slug, hf in _j(HIST, {"forecast": {}}).get("forecast", {}).items():
        fc = v["fc"].setdefault(slug, {})
        for made, rec in hf.items():
            if made in fc or made >= today:
                continue
            fc[made] = {"elev": rec["elev"], "station": rec["station"], "lv": rec.get("snowline", {}),
                        "days": {d: {"our": cm, "raw": {}} for d, cm in rec.get("days", {}).items() if d > made}}
    # neve misurata: dalla serie di 30 giorni di history.json a un archivio giornaliero permanente
    h = _j(HIST, {"obs": {}})
    t0 = date.fromisoformat(today)
    for st, series in h.get("obs", {}).items():
        o = v["obs"].setdefault(st, {})
        for i in range(1, 8):
            d = (t0 - timedelta(days=i)).isoformat()
            if d in o:
                continue
            m = measured_new_snow(series, d)
            if m is not None:
                o[d] = m
    FILE.write_text(json.dumps(v, ensure_ascii=False, separators=(",", ":")))


def _blank():
    return {"n": 0, "hit": 0, "miss": 0, "false": 0, "good": 0, "err": 0.0}


def scores(today: str) -> dict:
    v = _j(FILE, {"fc": {}, "obs": {}})
    leads = {1: {}, 2: {}, 3: {}}
    events, seen = [], set()
    for slug, fc in v.get("fc", {}).items():
        for made, rec in sorted(fc.items()):
            st = rec["station"]
            for d, x in rec.get("days", {}).items():
                if d >= today:
                    continue
                m = v.get("obs", {}).get(st, {}).get(d)
                if m is None:
                    continue
                lead = (date.fromisoformat(d) - date.fromisoformat(made)).days
                if lead not in leads or (st, d, lead) in seen:  # due località sulla stessa stazione: una volta
                    continue
                seen.add((st, d, lead))
                cands = {"our": x["our"], **x.get("raw", {})}
                for who, f in cands.items():
                    if f < SNOWY and m < SNOWY:
                        continue
                    s = leads[lead].setdefault(who, _blank())
                    s["n"] += 1
                    s["hit"] += f >= SNOWY and m >= SNOWY
                    s["miss"] += f < SNOWY <= m
                    s["false"] += m < SNOWY <= f
                    s["good"] += ok(f, m)
                    s["err"] += abs(f - m)
                if lead == 1 and (x["our"] >= SNOWY or m >= SNOWY):
                    events.append({"date": d, "slug": slug, "station": st.replace(" Nivo", ""),
                                   "our": round(x["our"]), "ecmwf": round(x.get("raw", {}).get("ECMWF", 0)),
                                   "obs": m, "ok": ok(x["our"], m)})
    out = {}
    for lead, by in leads.items():
        rows = {}
        for who, s in by.items():
            n = s["n"]
            rows[who] = {**s, "pct": round(100 * s["good"] / n) if n else None,
                         "mae": round(s["err"] / n, 1) if n else None}
        out[lead] = rows
    # quota neve: segnalazioni «nevica / piove» a una quota contro la quota prevista il giorno prima
    lvs = []
    for r in _j(REPORTS, []):
        if r.get("kind") not in ("nevica", "pioggia"):
            continue
        d = r["ts"][:10]
        made = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        lv = ((v["fc"].get(r.get("loc"), {}).get(made) or {}).get("lv") or {}).get(d)
        if lv is None:
            continue
        good = (r["elev"] >= lv - 150) if r["kind"] == "nevica" else (r["elev"] <= lv + 150)
        lvs.append(good)
    n1 = (out[1].get("our") or {}).get("n", 0)
    return {"leads": out, "events": sorted(events, key=lambda e: e["date"], reverse=True)[:20],
            "level": {"n": len(lvs), "good": sum(lvs)}, "snowy": n1, "ready": n1 >= MIN_SNOWY,
            "start": START, "days": len({d for fc in v.get("fc", {}).values() for d in fc})}
