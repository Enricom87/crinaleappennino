"""Oltre lo sci: attività ed eventi vicino a ogni località, ordinati in base al meteo del weekend
(se piove, prima il piano B al chiuso; se nevica, prima le ciaspole)."""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path

import i18n
from i18n import T, nice_date

ROOT = Path(__file__).resolve().parent.parent
_ACT = json.loads((ROOT / "config" / "activities.json").read_text())["items"]
_EV_FILE = ROOT / "data" / "events.json"
RADIUS_EV = 10  # km in linea d'aria: oltre si finisce dall'altra parte del crinale


def km(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def center(loc: dict, points: dict) -> tuple:
    ps = [points[p] for p in loc["points"] if p in points]
    return (sum(p["lat"] for p in ps) / len(ps), sum(p["lon"] for p in ps) / len(ps))


TAGS = {"rain": ("☔", "Perfetto se piove"), "snow": ("❄️", "Con la neve"),
        "dry": ("☀️", "Col bel tempo"), "any": ("🧭", "Sempre")}


def activities(loc: dict, points: dict, summer: bool, wk: dict | None, snow: bool) -> dict:
    c = center(loc, points)
    lang = i18n.LANG
    bad = bool(wk and wk["color"] == "red")
    out = []
    for a in _ACT:
        if a["season"] == ("summer" if not summer else "winter"):
            continue
        if loc["slug"] not in a.get("locs", [loc["slug"]]):
            continue
        d = km(c, (a["lat"], a["lon"]))
        if a["when"] == "snow" and not snow:
            continue
        rank = d
        if bad:
            rank += {"rain": -100, "any": -20, "snow": 40, "dry": 60}[a["when"]]
        elif snow and a["when"] == "snow":
            rank -= 50
        icon, tag = TAGS[a["when"]]
        out.append({"name": a["name"], "text": a["text"].get(lang) or a["text"]["en"], "km": round(d),
                    "icon": icon, "tag": T(tag), "when": a["when"], "rank": rank,
                    "map": "https://www.google.com/maps/search/?api=1&query="
                           + (a["name"] + " " + f"{a['lat']},{a['lon']}").replace(" ", "+")})
    out.sort(key=lambda x: x["rank"])
    lead = T("Il weekend si annuncia brutto in quota: ecco il piano B.") if bad else \
        (T("Idee per la giornata nei dintorni.") if summer else
         T("C'è neve: ecco cosa fare oltre lo sci.") if any(x["when"] == "snow" for x in out) else T("Idee per la giornata, oltre lo sci."))
    return {"list": out[:6], "lead": lead, "bad": bad}


def _events_raw() -> dict:
    try:
        return json.loads(_EV_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {"events": {}, "source": None}


def events(loc: dict, points: dict, today: str, days: int = 30) -> dict:
    raw = _events_raw()
    lang = "it" if i18n.LANG == "it" else "en"
    evs = raw.get("events", {}).get(lang) or raw.get("events", {}).get("it") or []
    c = center(loc, points)
    t0 = date.fromisoformat(today)
    end = (t0 + timedelta(days=days)).isoformat()
    out = []
    for e in evs:
        if e["to"] < today or e["from"] > end:
            continue
        d = km(c, (e["lat"], e["lon"]))
        if d > RADIUS_EV:
            continue
        if e["from"] == e["to"]:
            when = nice_date(e["from"], short=True)
        elif e["from"] <= today:
            when = T("fino al {d}", d=nice_date(e["to"], short=True))
        else:
            when = T("dal {a} al {b}", a=nice_date(e["from"], short=True), b=nice_date(e["to"], short=True))
        out.append({**e, "km": round(d), "when": when})
    out.sort(key=lambda e: (max(e["from"], today), e["km"]))
    return {"list": out[:6], "source": raw.get("source")}
