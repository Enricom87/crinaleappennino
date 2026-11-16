"""Testi automatici in italiano, generati da regole (niente AI a pagamento)."""
from __future__ import annotations

from datetime import date

GIORNI = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
        "settembre", "ottobre", "novembre", "dicembre"]


def nice_date(d: str, short: bool = False) -> str:
    x = date.fromisoformat(d)
    if short:
        return f"{GIORNI[x.weekday()][:3]} {x.day}"
    return f"{GIORNI[x.weekday()]} {x.day} {MESI[x.month - 1]}"


def cm(v: float) -> str:
    if v < 0.5:
        return "0 cm"
    if v < 2:
        return "1-2 cm"
    lo, hi = int(v * 0.7), int(v * 1.3 + 0.999)
    return f"{lo}-{hi} cm"


def snow_word(v: float) -> str:
    if v < 0.5:
        return "niente neve"
    if v < 3:
        return "una spolverata"
    if v < 10:
        return "una nevicata debole"
    if v < 25:
        return "una nevicata moderata"
    return "una nevicata abbondante"


def window_sum(rows: list[dict], a: int, b: int, key: str = "snow") -> float:
    return sum(r[key] for r in rows if a <= r["idx"] < b)


def best_days(rows: list[dict], a: int, b: int, min_cm: float = 1.0) -> list[str]:
    return [r["date"] for r in rows if a <= r["idx"] < b and r["snow"] >= min_cm]


def location_text(loc: dict, pts: dict[str, dict], syn_rows: list[dict]) -> dict:
    """Restituisce titolo, sintesi e paragrafi per una località."""
    ids = loc["points"]
    base, top = pts[ids[0]], pts[ids[-1]]
    b3, t3 = window_sum(base["days"], 0, 3), window_sum(top["days"], 0, 3)
    t10 = window_sum(top["days"], 3, 10)
    pr = top.get("probs", {})
    p7 = pr.get("d7", {}).get("p10")

    # titolo
    if t3 >= 5:
        days = best_days(top["days"], 0, 3)
        when = nice_date(days[0]) if days else "nei prossimi giorni"
        if b3 >= 1:
            title = f"Neve in arrivo da {when}: {cm(t3)} a {top['elev']} m, {cm(b3)} a {base['elev']} m"
        else:
            title = f"Neve in arrivo da {when}, solo in quota: {cm(t3)} a {top['elev']} m"
        level = "alert"
    elif t10 >= 10:
        days = best_days(top["days"], 3, 10, 3)
        when = nice_date(days[0]) if days else "la prossima settimana"
        title = f"Possibile nevicata da {when}: modelli da confermare"
        level = "watch"
    elif t3 + t10 >= 1:
        title = "Al massimo qualche fiocco in quota"
        level = "low"
    else:
        title = "Niente neve in vista nei prossimi dieci giorni"
        level = "none"

    paras = []
    # prossimi 3 giorni
    rain3 = window_sum(base["days"], 0, 3, "precip")
    fl = [r["fl_min"] for r in base["days"] if r["idx"] < 3 and r["fl_min"] is not None]
    fl_txt = f", con quota zero termico minima intorno ai {round(min(fl), -2):.0f} m" if fl else ""
    if t3 < 0.5 and rain3 >= 5:
        paras.append(f"Prossimi 3 giorni: precipitazioni ({rain3:.0f} mm) ma troppo miti per la neve, "
                     f"anche in vetta{fl_txt}.")
    elif t3 < 0.5:
        paras.append(f"Prossimi 3 giorni: tempo senza neve{fl_txt}.")
    else:
        paras.append(f"Prossimi 3 giorni: {snow_word(t3)} in quota ({cm(t3)} a {top['elev']} m), "
                     f"{cm(b3)} a {base['elev']} m{fl_txt}. Riferimento: modelli ad alta risoluzione "
                     f"(ICON-2I, ICON-CH2, AROME, ICON-D2) per oggi e domani.")

    # tendenza
    spread = [r for r in top["days"] if 3 <= r["idx"] < 10]
    if spread:
        hi = max(r["snow_max"] for r in spread)
        lo = sum(min(r["per_model"].values()) for r in spread if r["per_model"])
        if t10 < 1 and hi < 5:
            paras.append("Tendenza 4-10 giorni: i modelli globali non vedono nevicate significative.")
        else:
            agree = "concordi" if (hi - lo) < max(8, t10) else "in disaccordo"
            paras.append(f"Tendenza 4-10 giorni: {snow_word(t10)} in quota secondo la media dei modelli "
                         f"(circa {cm(t10)}), ma ECMWF, GFS e ICON sono {agree}: fino a {hi:.0f} cm "
                         f"nello scenario più nevoso.")

    # probabilità
    if pr.get("d7"):
        p = pr["d7"]
        paras.append(f"Probabilità a 7 giorni a {top['elev']} m (ensemble ECMWF, {pr['members']} scenari): "
                     f"almeno 1 cm {p['p1']}%, almeno 10 cm {p['p10']}%, almeno 20 cm {p['p20']}%.")

    # innevamento
    sm_ids = loc.get("snowmaking_points") or []
    if sm_ids:
        nights = []
        for r in pts[sm_ids[0]]["days"]:
            if r["idx"] < 7 and r["tw2"] >= 4:
                nights.append((r["date"], r["tw2"], r["tw4"]))
        if nights:
            lst = ", ".join(f"{nice_date(d, True)} ({h2} h)" for d, h2, _ in nights[:4])
            paras.append(f"Innevamento artificiale: notti utili nei prossimi 7 giorni — {lst}.")
        else:
            paras.append("Innevamento artificiale: nei prossimi 7 giorni le notti restano troppo miti o umide.")

    # vento in cresta
    gust = [(r["date"], r["gust"]) for r in top["days"] if r["idx"] < 5 and r["gust"] and r["gust"] >= 60]
    if gust:
        d, g = max(gust, key=lambda x: x[1])
        paras.append(f"Vento: raffiche fino a {g} km/h in cresta {nice_date(d)}; possibili chiusure degli impianti in quota.")

    # configurazione
    syn = [s for s in syn_rows if s.get("ec") and s["ec"]["precip"] >= 1][:3]
    if syn:
        s = syn[0]
        e = s["ec"]
        paras.append(f"Configurazione ({nice_date(s['date'])}): {s['name']}, flusso {e['flow']} in quota, "
                     f"temperatura a 1.500 m circa {(0 if round(e['t850']) == 0 else round(e['t850'])):+d} °C → {e['thermal']} per la neve.")

    return {"title": title, "level": level, "paragraphs": paras,
            "snow3_top": round(t3, 1), "snow3_base": round(b3, 1), "snow10_top": round(t10, 1), "p7": p7}


def overview_text(locs: list[dict]) -> str:
    ranked = sorted(locs, key=lambda l: -(l["text"]["snow3_top"] * 2 + l["text"]["snow10_top"]))
    top = ranked[0]
    if top["text"]["level"] in ("none", "low"):
        return ("Nessuna nevicata significativa in vista sull'Appennino tosco-emiliano nei prossimi giorni. "
                "Seguiamo ogni mattina i modelli ad alta risoluzione per segnalarvi la prima occasione.")
    names = ", ".join(l["name"].split(" · ")[0] for l in ranked[:3])
    return (f"{top['text']['title']}. Le località più favorite: {names}. "
            "Dettagli quota per quota nelle schede qui sotto.")
