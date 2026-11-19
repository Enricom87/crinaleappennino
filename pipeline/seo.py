"""Titolo, descrizione e FAQ (visibili in pagina + JSON-LD FAQPage) delle località, con i numeri del
motore fisico dei primi 5 giorni. Tutto ciò che va nel JSON-LD è anche scritto nella pagina."""
from __future__ import annotations

import json

from i18n import T, cap, nice_date


def _r100(z):
    return int(round(z / 100.0) * 100)


def location_seo(L: dict, site: dict, summer: bool) -> dict:
    eng = L.get("engine") or []
    low, top = L["low_pt"], L["mtn_top"]
    name = L["name"].split(" · ")[0]
    t_cm = round(sum(e["top"] or 0 for e in eng))
    b_cm = round(sum(e["base"] or 0 for e in eng))
    wet = [e for e in eng if (e.get("mm") or 0) >= 1 and e.get("qn") is not None]
    snowy = [e for e in eng if (e["top"] or 0) >= 1]
    first = snowy[0] if snowy else None
    qn = _r100(first["qn"]) if first and first.get("qn") is not None else None
    when = nice_date(first["date"]) if first else None

    if summer or not eng:
        title = desc = None
    elif t_cm >= 1:
        title = T("Neve {name}: {t} cm in vetta, quota neve {qn} m · {site}",
                  name=name, t=t_cm, qn=qn or top["elev"], site=site["name"])
        desc = T("{name}: {t} cm previsti in vetta ({ztop} m) e {b} cm alla base nei prossimi 5 giorni, neve da "
                 "{qn} m. Impianti e webcam aggiornati 5 volte al giorno.",
                 name=name, t=t_cm, ztop=top["elev"], b=b_cm, qn=qn or top["elev"])
    else:
        title = T("Neve {name} oggi e nei prossimi 5 giorni: quota neve, impianti e tendenze · {site}",
                  name=name, site=site["name"])
        desc = (T("{name}: nessuna nevicata prevista nei prossimi 5 giorni, piogge e quota neve sopra i {qn} m. "
                  "Impianti, webcam e tendenze fino a 30 giorni, aggiornati 5 volte al giorno.",
                  name=name, qn=_r100(min(e["qn"] for e in wet))) if wet else
                T("{name}: nessuna nevicata prevista nei prossimi 5 giorni. Impianti, webcam e tendenze fino "
                  "a 30 giorni per sapere quando torna la neve, aggiornati 5 volte al giorno.", name=name))

    faq = []
    if eng and not summer:
        if t_cm >= 1:
            a = T("Nei prossimi 5 giorni il nostro calcolo prevede circa {t} cm in vetta ({ntop}, {ztop} m) e {b} cm "
                  "alla base ({nbase}, {zbase} m). La prima nevicata è attesa {when}.",
                  t=t_cm, ntop=top["name"], ztop=top["elev"], b=b_cm, nbase=low["name"], zbase=low["elev"], when=when)
        else:
            a = T("Nei prossimi 5 giorni non sono previste nevicate né in vetta ({ntop}, {ztop} m) né alla base ({nbase}, {zbase} m). "
                  "Per capire quando potrebbe tornare la neve guarda le tendenze a 30 giorni.",
                  ntop=top["name"], ztop=top["elev"], nbase=low["name"], zbase=low["elev"])
        faq.append((T("{name}: quanta neve è prevista?", name=name), a))
        if wet:
            e = wet[0]
            a = T("{when} la quota neve è prevista intorno ai {qn} m", when=cap(nice_date(e["date"])), qn=_r100(e["qn"]))
            if e.get("qn_min") is not None and e["qn"] - e["qn_min"] >= 150:
                a += T(", fino a {z} m durante i rovesci più intensi", z=_r100(e["qn_min"]))
            a += T(". La calcoliamo con la temperatura di bulbo umido, l'effetto delle precipitazioni forti e il "
                   "freddo che ristagna nelle conche.")
        else:
            a = T("Nei prossimi 5 giorni non sono previste precipitazioni significative, quindi nessuna quota neve "
                  "da segnalare.")
        faq.append((T("{name}: a che quota nevica?", name=name), a))
        li = L.get("liftinfo") or {}
        if li.get("total") and not li.get("off"):
            a = T("Secondo il gestore ({src}) oggi sono aperti {o} impianti su {n}. Lo stato viene ricontrollato a "
                  "ogni aggiornamento; fanno fede solo i comunicati ufficiali.", src=li["name"], o=li["open"],
                  n=li["total"])
            faq.append((T("{name}: gli impianti sono aperti?", name=name), a))
        faq.append((T("Ogni quanto si aggiornano le previsioni?"),
                    T("Cinque volte al giorno, con le ultime uscite dei modelli meteo. I primi 5 giorni vengono da un "
                      "calcolo fisico costruito per l'Appennino tosco-emiliano, i giorni successivi da circa 300 "
                      "scenari dei principali centri meteo.")))
    ld = None
    if faq:
        ld = json.dumps({"@context": "https://schema.org", "@type": "FAQPage",
                         "mainEntity": [{"@type": "Question", "name": q,
                                         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
                        ensure_ascii=False).replace("</", "<\\/")
    return {"title": title, "desc": desc, "faq": faq, "ld": ld}
