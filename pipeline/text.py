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


def pick(options: list[str], *keys) -> str:
    """Sceglie una variante in modo stabile (stessa località e giorno = stesso testo), così il sito non sembra un robot."""
    h = sum(ord(c) for c in "|".join(str(k) for k in keys))
    return options[h % len(options)]


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

    # titolo: un aggancio che dice subito la cosa giusta, mai più di quanto dicono i dati
    k = (loc["slug"], date.today().isoformat())
    if t3 >= 5:
        days = best_days(top["days"], 0, 3)
        when = nice_date(days[0]) if days else "nei prossimi giorni"
        if b3 >= 3:
            title = pick([f"❄️ Si imbianca tutto: {cm(t3)} in vetta e {cm(b3)} giù in paese da {when}",
                          f"❄️ Ci siamo, arriva la neve! {cm(t3)} a {top['elev']} m da {when}",
                          f"❄️ Prepara gli sci: da {when} {cm(t3)} in quota e neve fino a {base['elev']} m"], *k)
        elif b3 >= 1:
            title = pick([f"❄️ Arriva la neve da {when}: {cm(t3)} in vetta, una spolverata a {base['elev']} m",
                          f"❄️ Fiocchi in arrivo! {cm(t3)} a {top['elev']} m da {when}"], *k)
        else:
            title = pick([f"❄️ Neve solo in alto: {cm(t3)} sopra i {round((top['elev'] - 200) / 100) * 100} m da {when}",
                          f"⛰️ In vetta torna il bianco: {cm(t3)} da {when}, sotto piove"], *k)
        if t3 >= 25:
            title = f"🔥 Nevicata seria in arrivo: {cm(t3)} a {top['elev']} m da {when}"
        level = "alert"
    elif t10 >= 10:
        days = best_days(top["days"], 3, 10, 3)
        when = nice_date(days[0]) if days else "la prossima settimana"
        title = pick([f"👀 Occhio a {when}: i modelli fiutano neve (da confermare)",
                      f"🤞 Segnale di neve per {when}: incrociamo le dita",
                      f"📡 Qualcosa si muove per {when}: possibile nevicata in quota"], *k)
        level = "watch"
    elif t3 + t10 >= 1:
        title = pick(["Solo qualche fiocco in quota, niente di più (per ora)",
                      "Spolverata in vetta e poco altro: la neve vera si fa attendere",
                      "Qualche fiocco qua e là: non è ancora il momento delle pelli"], *k)
        level = "low"
    else:
        title = pick(["Sci nel cassetto: niente neve all'orizzonte per 10 giorni",
                      "Niente neve in vista: meglio scarponi da trekking che da sci",
                      "Calma piatta: nessuna nevicata nei prossimi 10 giorni"], *k)
        level = "none"

    paras = []
    # prossimi 3 giorni
    rain3 = window_sum(base["days"], 0, 3, "precip")
    fl = [r["fl_min"] for r in base["days"] if r["idx"] < 3 and r["fl_min"] is not None]
    fl_txt = f", con quota zero termico minima intorno ai {round(min(fl), -2):.0f} m" if fl else ""
    if t3 < 0.5 and rain3 >= 5:
        paras.append(f"Nei prossimi 3 giorni piove ({rain3:.0f} mm), ma fa troppo caldo per la neve, "
                     f"anche in vetta{fl_txt}. Ombrello sì, sci no.")
    elif t3 < 0.5:
        paras.append(f"Nei prossimi 3 giorni niente neve{fl_txt}.")
    else:
        paras.append(f"Cosa ti aspetta nei prossimi 3 giorni: {snow_word(t3)} in quota, {cm(t3)} a {top['elev']} m "
                     f"e {cm(b3)} a {base['elev']} m{fl_txt}. Per oggi e domani ci fidiamo dei modelli più "
                     f"dettagliati (ICON-2I, ICON-CH2, AROME, ICON-D2), quelli che vedono le valli una per una.")

    # tendenza
    spread = [r for r in top["days"] if 3 <= r["idx"] < 10]
    if spread:
        hi = max(r["snow_max"] for r in spread)
        lo = sum(min(r["per_model"].values()) for r in spread if r["per_model"])
        if t10 < 1 and hi < 5:
            paras.append("E dopo? Dal quarto al decimo giorno i grandi modelli non vedono nevicate degne di nota.")
        else:
            agree = "sono d'accordo" if (hi - lo) < max(8, t10) else "litigano"
            paras.append(f"E dopo? Tra 4 e 10 giorni la media dei modelli dice {snow_word(t10)} in quota "
                         f"(circa {cm(t10)}). ECMWF, GFS e ICON {agree}: lo scenario più generoso arriva a "
                         f"{hi:.0f} cm.")

    # probabilità
    if pr.get("d7"):
        p = pr["d7"]
        paras.append(f"Le probabilità vere a {top['elev']} m, su {pr['members']} scenari ECMWF per i prossimi 7 giorni: "
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
            paras.append(f"Buone notizie per le piste: notti abbastanza fredde per sparare neve — {lst}.")
        else:
            paras.append("Cannoni spenti: per 7 giorni le notti restano troppo miti o umide per fare neve.")

    # vento in cresta
    gust = [(r["date"], r["gust"]) for r in top["days"] if r["idx"] < 5 and r["gust"] and r["gust"] >= 60]
    if gust:
        d, g = max(gust, key=lambda x: x[1])
        paras.append(f"Tieni il cappello: {nice_date(d)} raffiche fino a {g} km/h in cresta, gli impianti in quota potrebbero fermarsi.")

    # configurazione
    syn = [s for s in syn_rows if s.get("ec") and s["ec"]["precip"] >= 1][:3]
    if syn:
        s = syn[0]
        e = s["ec"]
        paras.append(f"Per gli appassionati ({nice_date(s['date'])}): {s['name']}, flusso {e['flow']} in quota, "
                     f"circa {(0 if round(e['t850']) == 0 else round(e['t850'])):+d} °C a 1.500 m: {e['thermal']} per la neve.")

    return {"title": title, "level": level, "paragraphs": paras,
            "snow3_top": round(t3, 1), "snow3_base": round(b3, 1), "snow10_top": round(t10, 1), "p7": p7}


def overview_text(locs: list[dict]) -> str:
    ranked = sorted(locs, key=lambda l: -(l["text"]["snow3_top"] * 2 + l["text"]["snow10_top"]))
    top = ranked[0]
    if top["text"]["level"] in ("none", "low"):
        return ("Per ora l'Appennino resta a secco di neve. Noi guardiamo i modelli ogni mattina: "
                "appena spunta la prima occasione te lo diciamo qui (e per email, se ti iscrivi).")
    names = ", ".join(l["name"].split(" · ")[0] for l in ranked[:3])
    return (f"{top['text']['title']}. Chi se la gode di più: {names}. "
            "Scegli la tua località e guarda quanta ne arriva, quota per quota.")
