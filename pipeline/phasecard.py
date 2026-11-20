"""Le schede delle tendenze in home: una frase, un'etichetta se c'è qualcosa da segnare, tre numeri."""
from __future__ import annotations

from i18n import T, nice_date


def engine_phase(p: dict, engine: dict, reg_lv: dict, locs: list) -> None:
    """«Prossimi 5 giorni»: numeri e titolo dal motore fisico (gli stessi delle località), non dagli scenari.
    «Stazioni» = solo località con la base a quota da stazione (≤ 1.600 m, non Lago Scaffaiolo)."""
    low = {L["slug"] for L in locs if L["low_pt"]["elev"] <= 1600}
    st_eng = {k: v for k, v in engine.items() if k in low} or engine
    base = max((sum(e["base"] or 0 for e in v) for v in st_eng.values()), default=0)
    top = max((sum(e["top"] or 0 for e in v) for v in engine.values()), default=0)
    mm = max((sum(e["mm"] or 0 for e in v) for v in engine.values()), default=0)
    by_day: dict[str, float] = {}
    for v in engine.values():
        for e in v:
            by_day[e["date"]] = max(by_day.get(e["date"], 0), e["top"] or 0)
    snowiest = max(by_day, key=by_day.get) if by_day and max(by_day.values()) >= 1 else None
    qn = int(round(reg_lv[snowiest] / 100) * 100) if snowiest in reg_lv else None  # stessa quota dell'etichetta
    if base >= 3:
        e, h = "❄️", T("Neve fino alle stazioni")
    elif top >= 5:
        e, h = "🌨️", T("Neve in quota")
    elif top >= 1:
        e, h = "🌨️", T("Spolverata sulle cime")
    elif mm >= 10:
        e, h = "🌧️", T("Perturbato, neve solo sulle vette più alte")
    else:
        e, h = "☀️", T("Tempo asciutto")
    p["engine"] = {"base": round(base), "top": round(top), "qn": qn}
    p["card"] = {"emoji": e, "head": h, "tag": None, "conf": T("calcolo fisico ora per ora")}


def decorate(tv: dict | None, locs: list | None, engine: dict | None = None, reg_lv: dict | None = None) -> dict | None:
    if not tv or not tv.get("phases"):
        return tv
    from articles import local_snow
    ls = local_snow(locs or [], "")
    sl = next((L.get("snowline") for L in (locs or []) if L.get("slug") == "abetone" and L.get("snowline")), None) or []
    for i, p in enumerate(tv["phases"]):
        mix = {lab: v for lab, _c, v in p.get("mix", [])}
        snow, low, cold = p.get("snow", 0), p.get("snow_low", 0), p.get("cold_tail", 0) or 0
        mild = mix.get(T("Asciutto e mite"), 0)
        wet = mix.get(T("Perturbato, neve solo in alta quota"), 0)
        if low >= 30:
            e, h = "❄️", T("Neve fino alle stazioni")
        elif snow >= 40:
            e, h = "🌨️", T("Neve in quota probabile")
        elif cold >= 25:
            e, h = "🥶", T("Arriva il freddo")
        elif snow >= 15:
            e, h = "🌨️", T("Si rinfresca, neve possibile in quota")
        elif cold >= 15:
            e, h = "🧊", T("Segnale di freddo da seguire")
        elif mild >= wet and mild >= 30:
            e, h = "☀️", T("Pausa più asciutta e mite")
        elif wet >= 30:
            e, h = "🌦️", T("Variabile, neve solo sulle cime")
        else:
            e, h = "⛅", T("Tempo nella norma")
        tag = None
        if i == 0 and ls:
            z = next((d.get("late") or d.get("lv") for d in sl if d["date"] == ls["date"] and not d["dry"]), None)
            day = nice_date(ls["date"]).split(" ")[0]
            tag = ("snow", T("{d} neve dai {z} m", d=day.capitalize(), z=z) if z else T("{d} neve sulle cime", d=day.capitalize()))
        elif p.get("best") and snow >= 15:
            tag = ("snow", T("Da segnare: {d}", d=p["best"]))
        if cold >= 15 and p.get("cold_day") and (not tag or i > 1):
            tag = ("cold", T("Freddo verso {d}", d=p["cold_day"]))
        conf = p.get("conf")
        p["card"] = {"emoji": e, "head": h, "tag": tag,
                     "conf": {T("alta"): T("affidabile"), T("media"): T("abbastanza affidabile"),
                              T("bassa"): T("ancora incerta")}.get(conf, conf)}
        if i == 0 and engine:
            engine_phase(p, engine, reg_lv or {}, locs or [])
            p["card"]["tag"] = tag
    return tv
