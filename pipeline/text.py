"""Testi automatici, generati da regole (niente AI a pagamento). Lingua corrente: i18n.set_lang()."""
from __future__ import annotations

from datetime import date

from i18n import DAYS, T, nice_date  # noqa: F401  (nice_date riesportato per gli altri moduli)

GIORNI = DAYS["it"]


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
        return T("niente neve")
    if v < 3:
        return T("una spolverata")
    if v < 10:
        return T("una nevicata debole")
    if v < 25:
        return T("una nevicata moderata")
    return T("una nevicata abbondante")


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
    v = dict(t3=cm(t3), b3=cm(b3), ztop=top["elev"], zbase=base["elev"],
             ntop=top["name"], nbase=base["name"])
    if t3 >= 5:
        days = best_days(top["days"], 0, 3)
        when = nice_date(days[0]) if days else T("nei prossimi giorni")
        if b3 >= 3:
            title = pick([T("❄️ Si imbianca tutto: {t3} in vetta e {b3} giù in paese da {when}", when=when, **v),
                          T("❄️ Ci siamo, arriva la neve! {t3} al {ntop} e {b3} a {nbase} da {when}", when=when, **v),
                          T("❄️ Prepara gli sci: da {when} {t3} in quota e neve fino a {zbase} m", when=when, **v)], *k)
        elif b3 >= 1:
            title = T("❄️ Arriva la neve da {when}: {t3} al {ntop} ({ztop} m), solo una spolverata a {nbase} ({zbase} m)", when=when, **v)
        else:
            rain_b = window_sum(base["days"], 0, 3, "precip") >= 2
            title = (T("⛰️ Neve solo in vetta: {t3} al {ntop} ({ztop} m) da {when}, a {nbase} ({zbase} m) piove", when=when, **v)
                     if rain_b else
                     T("⛰️ Neve solo in vetta: {t3} al {ntop} ({ztop} m) da {when}, niente a {nbase} ({zbase} m)", when=when, **v))
        if t3 >= 25:
            title = (T("🔥 Nevicata seria in arrivo: {t3} al {ntop} ({ztop} m) da {when}", when=when, **v) if b3 >= 3 else
                     T("🔥 Nevicata seria in vetta: {t3} al {ntop} ({ztop} m) da {when}, molta meno a {nbase} ({zbase} m)", when=when, **v))
        level = "alert"
    elif t10 >= 10:
        days = best_days(top["days"], 3, 10, 3)
        when = nice_date(days[0]) if days else T("la prossima settimana")
        bd = {d["date"]: d.get("snow") or 0 for d in base["days"]}
        b10 = bd.get(days[0], 0) if days else 0  # neve alla base nello stesso giorno indicato nel titolo
        title = (T("👀 Occhio a {when}: i modelli vedono neve fino a {nbase} ({zbase} m), da confermare", when=when, **v)
                 if b10 >= 2 else
                 T("👀 Occhio a {when}: possibile neve solo in vetta, al {ntop} ({ztop} m); a {nbase} ({zbase} m) per ora poco o niente", when=when, **v))
        level = "watch"
    elif t3 + t10 >= 1:
        title = pick([T("Solo qualche fiocco in quota, niente di più (per ora)"),
                      T("Spolverata in vetta e poco altro: la neve vera si fa attendere"),
                      T("Qualche fiocco qua e là: non è ancora il momento delle pelli")], *k)
        level = "low"
    else:
        title = pick([T("Sci nel cassetto: niente neve all'orizzonte per 10 giorni"),
                      T("Niente neve in vista: meglio scarponi da trekking che da sci"),
                      T("Calma piatta: nessuna nevicata nei prossimi 10 giorni")], *k)
        level = "none"

    paras = []
    # prossimi 3 giorni
    rain3 = window_sum(base["days"], 0, 3, "precip")
    fl = [r["fl_min"] for r in base["days"] if r["idx"] < 3 and r["fl_min"] is not None]
    fl_txt = T(", con quota zero termico minima intorno ai {fl} m", fl=f"{round(min(fl), -2):.0f}") if fl else ""
    if t3 < 0.5 and rain3 >= 5:
        paras.append(T("Nei prossimi 3 giorni piove ({rain} mm), ma fa troppo caldo per la neve, "
                       "anche in vetta{fl_txt}. Ombrello sì, sci no.", rain=f"{rain3:.0f}", fl_txt=fl_txt))
    elif t3 < 0.5:
        paras.append(T("Nei prossimi 3 giorni niente neve{fl_txt}.", fl_txt=fl_txt))
    else:
        paras.append(T("Cosa ti aspetta nei prossimi 3 giorni: {word} in quota, {t3} a {ztop} m "
                       "e {b3} a {zbase} m{fl_txt}. Per oggi e domani ci fidiamo dei modelli più "
                       "dettagliati (ICON-2I, ICON-CH2, AROME, ICON-D2), quelli che vedono le valli una per una.",
                       word=snow_word(t3), fl_txt=fl_txt, **v))

    # tendenza
    spread = [r for r in top["days"] if 3 <= r["idx"] < 10]
    if spread:
        hi = max(r["snow_max"] for r in spread)
        lo = sum(min(r["per_model"].values()) for r in spread if r["per_model"])
        if t10 < 1 and hi < 5:
            paras.append(T("E dopo? Dal quarto al decimo giorno i grandi modelli non vedono nevicate degne di nota."))
        else:
            agree = T("sono d'accordo") if (hi - lo) < max(8, t10) else T("litigano")
            paras.append(T("E dopo? Tra 4 e 10 giorni la media dei modelli dice {word} in quota "
                           "(circa {t10}). ECMWF, GFS e ICON {agree}: lo scenario più generoso arriva a "
                           "{hi} cm.", word=snow_word(t10), t10=cm(t10), agree=agree, hi=f"{hi:.0f}"))

    # probabilità
    if pr.get("d7"):
        p = pr["d7"]
        paras.append(T("Le probabilità vere a {ztop} m, su {n} scenari ECMWF per i prossimi 7 giorni: "
                       "almeno 1 cm {p1}%, almeno 10 cm {p10}%, almeno 20 cm {p20}%.",
                       ztop=top["elev"], n=pr["members"], p1=p["p1"], p10=p["p10"], p20=p["p20"]))

    # innevamento
    sm_ids = loc.get("snowmaking_points") or []
    if sm_ids:
        nights = []
        for r in pts[sm_ids[0]]["days"]:
            if r["idx"] < 7 and r["tw2"] >= 4:
                nights.append((r["date"], r["tw2"], r["tw4"]))
        if nights:
            lst = ", ".join(T("{d} ({h} h)", d=nice_date(d, True), h=h2) for d, h2, _ in nights[:4])
            paras.append(T("Buone notizie per le piste: notti abbastanza fredde per sparare neve — {lst}.", lst=lst))
        else:
            paras.append(T("Cannoni spenti: per 7 giorni le notti restano troppo miti o umide per fare neve."))

    # vento in cresta
    gust = [(r["date"], r["gust"]) for r in top["days"] if r["idx"] < 5 and r["gust"] and r["gust"] >= 60]
    if gust:
        d, g = max(gust, key=lambda x: x[1])
        paras.append(T("Tieni il cappello: {d} raffiche fino a {g} km/h in cresta, gli impianti in quota potrebbero fermarsi.",
                       d=nice_date(d), g=g))

    # configurazione
    syn = [s for s in syn_rows if s.get("ec") and s["ec"]["precip"] >= 1][:3]
    if syn:
        s = syn[0]
        e = s["ec"]
        paras.append(T("Per gli appassionati ({d}): {name}, flusso {flow} in quota, "
                       "circa {t} °C a 1.500 m: {thermal} per la neve.",
                       d=nice_date(s["date"]), name=T(s["name"]), flow=T(e["flow"]),
                       t=f"{(0 if round(e['t850']) == 0 else round(e['t850'])):+d}", thermal=T(e["thermal"])))

    return {"title": title, "level": level, "paragraphs": paras,
            "snow3_top": round(t3, 1), "snow3_base": round(b3, 1), "snow10_top": round(t10, 1), "p7": p7,
            "snow10_base": round(window_sum(base["days"], 0, 10), 1),
            "top_name": top["name"], "top_elev": top["elev"]}


def overview_text(locs: list[dict]) -> str:
    """Il riassunto in home. Si confrontano le località solo dove si scia (punto basso): le vette hanno
    altezze diverse e metterle in classifica farebbe sembrare che nevichi in una stazione e piova nell'altra."""
    best_top = max(locs, key=lambda l: l["text"]["snow3_top"] * 2 + l["text"]["snow10_top"])
    if best_top["text"]["level"] in ("none", "low"):
        return T("Per ora l'Appennino resta a secco di neve. Noi guardiamo i modelli ogni mattina: "
                 "appena spunta la prima occasione te lo diciamo qui (e per email, se ti iscrivi).")
    ranked = sorted(locs, key=lambda l: -l["text"]["snow10_base"])
    if ranked[0]["text"]["snow10_base"] < 3:
        peaks = {}
        for l in locs:
            if l["text"]["snow10_top"] >= 3:
                peaks[l["text"]["top_name"]] = l["text"]["top_elev"]
        if not peaks:
            return T("Per ora l'Appennino resta a secco di neve. Noi guardiamo i modelli ogni mattina: "
                     "appena spunta la prima occasione te lo diciamo qui (e per email, se ti iscrivi).")
        names = ", ".join(n for n, _ in sorted(peaks.items(), key=lambda x: -x[1])[:4])
        zmin = int(min(peaks.values()) // 100 * 100)
        return T("Nei prossimi giorni neve solo sulle cime più alte, sopra i {z} m circa ({names}). "
                 "Alle stazioni, per ora, pioggia o niente: decide la quota neve, guarda la tua località quota per quota.",
                 z=zmin, names=names)
    top = ranked[0]
    names = ", ".join(l["name"].split(" · ")[0] for l in ranked[:3] if l["text"]["snow10_base"] >= 3)
    return T("{title}. Chi se la gode di più: {names}. "
             "Scegli la tua località e guarda quanta ne arriva, quota per quota.", title=top["text"]["title"], names=names)
