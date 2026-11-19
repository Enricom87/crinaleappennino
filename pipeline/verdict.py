"""Il verdetto del weekend: una risposta secca (sali / aspetta / lascia perdere) per chi deve decidere,
con il perché, quanto fidarsi e cosa fare. I numeri restano nelle sezioni tecniche."""
from __future__ import annotations

from datetime import date, timedelta

from cards import certainty
import i18n
from i18n import T, cap, day_name


def low(s: str) -> str:
    return s.lower() if i18n.LANG in ("it", "fr", "es") else s


def weekend_dates(today: str) -> list[str]:
    t = date.fromisoformat(today)
    wd = t.weekday()  # 0 lunedì … 5 sabato, 6 domenica
    if wd == 5:
        ds = [t, t + timedelta(days=1)]
    elif wd == 6:
        ds = [t]
    else:
        sat = t + timedelta(days=5 - wd)
        ds = [sat, sat + timedelta(days=1)]
    return [d.isoformat() for d in ds]


def zq(base: dict | None, top: dict | None) -> int:
    """Quota da cui nevica quel giorno, presa dalla quota neve del profilo e tenuta tra base e vetta."""
    lv = (base or {}).get("lv") or (top or {}).get("lv")
    lo, hi = (base or {}).get("elev") or 1000, (top or {}).get("elev") or 2100
    if lv is None:
        lv = (lo + hi) / 2
    return int(round(min(max(lv, lo + 100), hi - 100) / 100) * 100)


def day_verdict(m: dict, snow_top: float, summer: bool, base: dict | None = None, top: dict | None = None) -> tuple[str, str]:
    """Colore (green/yellow/red) e motivo per un giorno. base = {name, elev, snow, precip} del punto più basso."""
    rain, gust, storm = m.get("rain") or 0, m.get("gust") or 0, m.get("storm") or 0
    base_rain = bool(base and top and base["name"] != top["name"] and base["precip"] >= 2 and base["snow"] < 3)
    if not summer and base_rain and snow_top >= 1 and gust < 70:
        # piove dove si scia: stessa valutazione per tutte le località, qualunque sia l'altezza della vetta
        return "yellow", T("neve in quota dai {z} m in su ({n} cm al {nt}, {et} m)",
                           z=zq(base, top), n=round(snow_top), nt=top["name"], et=top["elev"])
    if not summer and snow_top >= 5 and gust < 70:
        if not base or not top or base["name"] == top["name"]:
            return "green", T("neve fresca ({n} cm in vetta)", n=round(snow_top))
        if base["snow"] >= 3:
            return "green", T("neve fresca anche in basso: {b} cm a {nb}, {n} cm al {nt}",
                              b=round(base["snow"]), nb=base["name"], n=round(snow_top), nt=top["name"])
        return "green", T("neve fresca in quota dai {z} m in su ({n} cm al {nt}, {et} m)",
                          z=zq(base, top), n=round(snow_top), nt=top["name"], et=top["elev"])
    if m["verdict"] in ("ottima", "buona"):
        why = T("sole") if (m.get("cloud") or 0) < 40 else T("asciutto, con qualche nuvola")
        return "green", why
    if m["verdict"] == "mattina":
        return "yellow", T("bello la mattina, temporali dalle {h}", h=m["back_by"] or 13)
    if m["verdict"] == "attenzione":
        if gust >= 50:
            return "yellow", T("vento forte in cresta ({g} km/h)", g=round(gust))
        return "yellow", T("tempo incerto, qualche pioggia")
    if rain >= 5:
        if not summer and top and snow_top >= 1:
            return "yellow", T("neve in quota dai {z} m in su (circa {s} cm al {nt}, {et} m)",
                               z=zq(base, top), s=round(snow_top), nt=top["name"], et=top["elev"])
        return "red", T("pioggia ({n} mm)", n=round(rain))
    if gust >= 70:
        return "red", T("vento molto forte in cresta ({g} km/h)", g=round(gust))
    if storm >= 2:
        return "red", T("temporali")
    return "red", T("brutto tempo")


def weekend(L: dict, today: str, summer: bool) -> dict | None:
    by_date = {m["date"]: m for m in (L.get("mtn") or [])}
    top = L.get("mtn_top") or {}
    snow_by = {d["date"]: d.get("snow", 0) or 0 for d in top.get("days", [])}
    lowp = L.get("low_pt") or {}
    base_by = {d["date"]: {"name": lowp.get("name"), "elev": lowp.get("elev"), "snow": d.get("snow") or 0,
                           "precip": d.get("precip") or 0, "lv": d.get("lv")} for d in lowp.get("days", [])}
    days = []
    for d in weekend_dates(today):
        m = by_date.get(d)
        if not m:
            continue
        col, why = day_verdict(m, snow_by.get(d, 0), summer, base_by.get(d), top)
        days.append({"date": d, "name": cap(day_name(d)), "color": col, "why": why, "idx": m["idx"],
                     "snow": snow_by.get(d, 0), "snow_base": (base_by.get(d) or {}).get("snow", 0)})
    if not days:
        return None
    colors = [x["color"] for x in days]
    sure = certainty(max(x["idx"] for x in days))
    greens = [x for x in days if x["color"] == "green"]
    if len(greens) == len(days):
        color, title = "green", T("Si sale!")
        advice = T("Prenota pure: il weekend si annuncia buono.") if sure["key"] != "trend" else \
            T("Si annuncia buono, ma è ancora presto: ricontrolla giovedì prima di prenotare.")
    elif greens:
        color = "green"
        title = T("Si sale {d}", d=low(greens[0]["name"]))
        advice = T("Scegli {d}: è il giorno migliore del weekend.", d=low(greens[0]["name"]))
    elif "yellow" in colors:
        color, title = "yellow", T("Si può, con attenzione")
        advice = T("Parti presto e tieni d'occhio il cielo.")
    else:
        color, title = "red", T("Meglio rimandare")
        advice = T("Il weekend non si annuncia bene in quota.")
    if sure["key"] != "sure" and color != "green":
        advice += " " + T("La previsione può ancora cambiare: ti avvisiamo noi se migliora.")
    note = ""
    li = L.get("liftinfo") or {}
    if not summer and li.get("total") and li.get("open") == 0 and not li.get("stale"):
        note = T("Oggi gli impianti risultano chiusi: ottimo per ciaspole e passeggiate, non ancora per sciare.")
    return {"color": color, "title": title, "advice": advice, "days": days, "sure": sure, "note": note,
            "uncertain": sure["key"] != "sure"}
