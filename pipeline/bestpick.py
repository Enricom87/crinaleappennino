"""«Dove vado sabato?»: per ogni giorno del weekend la località migliore e le alternative,
con un motivo in chiaro. Punteggio semplice e spiegabile: tempo + neve fresca + impianti aperti."""
from __future__ import annotations

from i18n import T

BASE = {"green": 10, "yellow": 4, "red": 0}


def score(L: dict, d: dict, summer: bool) -> float:
    s = BASE[d["color"]]
    if summer or d["color"] == "red":
        return s
    li = L.get("liftinfo") or {}
    if li.get("open"):
        s += 4 + 2 * min(li["open"] / max(li.get("total") or 1, 1), 1)
    s += min(d.get("snow") or 0, 20) / 4
    return s


def best_pick(locs: list[dict], summer: bool) -> list[dict]:
    by_day: dict[str, list] = {}
    for L in locs:
        wk = L.get("weekend")
        if not wk:
            continue
        for d in wk["days"]:
            by_day.setdefault(d["date"], []).append((score(L, d, summer), L, d, wk["sure"]))
    out = []
    for date in sorted(by_day):
        rows = sorted(by_day[date], key=lambda x: -x[0])
        top = rows[0]
        if top[2]["color"] == "red":
            head = T("Brutto ovunque in quota: meglio un piano B al coperto.")
        elif len(rows) > 2 and rows[0][0] - rows[2][0] < 0.5:
            head = (T("Neve fresca un po' ovunque: scegli la località più comoda.")
                    if (top[2].get("snow") or 0) >= 5 and not summer
                    else T("Bel tempo un po' ovunque: scegli la località più comoda."))
        else:
            head = T("Il posto migliore è {loc}", loc=top[1]["name"].split(" · ")[0])
        out.append({
            "date": date, "name": top[2]["name"], "head": head, "sure": top[3], "red": top[2]["color"] == "red",
            "rows": [{"slug": L["slug"], "name": L["name"].split(" · ")[0], "color": d["color"], "why": d["why"],
                      "lifts": (None if summer or not (L.get("liftinfo") or {}).get("total")
                                else T("{o}/{t} impianti", o=L["liftinfo"]["open"], t=L["liftinfo"]["total"]))}
                     for _, L, d, _s in rows[:4]],
            "plan_b": rows[0][1]["slug"],
        })
    return out
