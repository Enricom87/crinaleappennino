"""Articoli «Tendenza»: ogni lunedì e giovedì un pezzo scritto in automatico dai dati del sito
(scenari dei modelli, quota del freddo, weekend, neve misurata), in tutte le lingue.
Ogni articolo è una fotografia: si salva in data/articles/<data>/<lingua>.json e non si riscrive."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from cards import prob_word
from i18n import T, nice_date
from verdict import low

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "articles"
OBS = ROOT / "data" / "snowobs.json"
PUB_DAYS = (0, 3)  # lunedì, giovedì


VERSION = 5  # se cambia il modo di scrivere, l'articolo di oggi si riscrive al prossimo aggiornamento


def due(today: str) -> bool:
    now = datetime.now(ZoneInfo("Europe/Rome"))
    exists = (DIR / today).exists()
    if exists:
        try:
            if json.loads((DIR / today / "it.json").read_text()).get("v", 1) < VERSION:
                return True
        except Exception:  # noqa: BLE001
            return True
    first_ever = not DIR.exists() or not any(DIR.iterdir())
    return not exists and (first_ever or (date.fromisoformat(today).weekday() in PUB_DAYS and now.hour >= 6))


def _stations() -> list[dict]:
    try:
        return json.loads(OBS.read_text()).get("stations", [])
    except Exception:  # noqa: BLE001
        return []


def local_snow(locs: list[dict], today: str) -> dict | None:
    """Nei prossimi 5 giorni comandano i modelli ad alta risoluzione della previsione locale:
    trova il giorno con più neve prevista in vetta e dove."""
    best = None
    for L in locs or []:
        if not L.get("pts"):
            continue
        top = max(L["pts"], key=lambda p: p["elev"])
        for d in top["days"][:5]:
            cm = d.get("snow") or 0
            if cm >= 3 and (best is None or cm > best["cm"]):
                best = {"date": d["date"], "cm": round(cm), "where": top["name"], "elev": top["elev"]}
    return best


def compose(tv: dict, synv: dict, bestpick: list, today: str, locs: list | None = None, telev: dict | None = None) -> dict | None:
    return compose_v5(tv, synv, bestpick, today, locs, telev)


def compose_old(tv: dict, synv: dict, bestpick: list, today: str, locs: list | None = None, telev: dict | None = None) -> dict | None:
    if not tv or not tv.get("phases"):
        return None
    ph = tv["phases"]
    ls = local_snow(locs, today)
    top = max(ph[:3], key=lambda p: p["snow"])
    cold = max((p for p in ph if p.get("cold_tail", 0) >= 15), key=lambda p: p["cold_tail"], default=None)
    if top["snow"] >= 50 and top.get("snow_low", 0) >= 30:
        title = T("Neve fino alle stazioni tra {a} e {b}: {k} modelli su {n} ci credono",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 50:
        title = T("Neve in quota tra {a} e {b}: {k} modelli su {n} ci credono, sotto rischia di essere pioggia",
                  a=top["from"], b=top["to"], k=top["agree"], n=top["nmodels"])
    elif top["snow"] >= 25:
        title = T("Qualche spiraglio di neve tra {a} e {b}", a=top["from"], b=top["to"])
    elif ls and cold:
        title = T("Neve in vetta {d}, poi un segnale di freddo verso {c}: cosa aspettarsi nelle prossime settimane",
                  d=nice_date(ls["date"]), c=cold["cold_day"])
    elif cold:
        title = T("Neve ancora lontana, ma un segnale di freddo verso {c}: cosa aspettarsi nelle prossime settimane",
                  c=cold["cold_day"])
    elif ls:
        title = T("Neve in vetta {d}, poi niente di serio: cosa aspettarsi nelle prossime settimane",
                  d=nice_date(ls["date"]))
    else:
        title = T("Niente neve seria all'orizzonte: cosa aspettarsi nelle prossime settimane")
    lead = []
    if ls:
        lead.append(T("Per i prossimi giorni comandano i modelli ad alta risoluzione: vedono una nevicata {d}, "
                      "circa {cm} cm a {w} ({e} m). È un episodio breve, da confermare nei prossimi aggiornamenti.",
                      d=nice_date(ls["date"]), cm=ls["cm"], w=ls["where"], e=ls["elev"]))
    lead += [tv["head"] if not ls else (T("Oltre quell'episodio, lo sguardo lungo dei modelli globali non vede altra neve seria.") if not cold else
                  T("Oltre quell'episodio niente neve seria per ora, ma una parte degli scenari porta aria fredda verso {c}: è il segnale da seguire nei prossimi aggiornamenti.", c=cold["cold_day"])),
            T("Abbiamo messo insieme {sc} scenari da {n} modelli meteo diversi, fino a {u}.",
              sc=tv["nscen"], n=tv["nmodels"], u=tv["until"])]
    if synv and synv.get("head"):
        lead.append(synv["head"])

    phases = []
    for p in ph:
        if p["share"] >= 50:
            txt = T("Dal {a} al {b}: prevale {type} ({sh} scenari su 100).", a=p["from"], b=p["to"],
                    type=low(p["type"]), sh=p["share"])
        else:  # nessun tipo di tempo ha la maggioranza: lo diciamo, invece di far sembrare deciso il più frequente
            parts = sorted(p.get("mix", []), key=lambda x: -x[2])[:3]
            txt = T("Dal {a} al {b} gli scenari sono divisi: {list}.", a=p["from"], b=p["to"],
                    list=", ".join(T("{type} {n} su 100", type=low(n), n=v) for n, _c, v in parts))
        txt += " " + T("Neve: {w} ({p} su 100). Temperatura tipica in quota intorno a {t} °C, affidabilità {c}.",
                       w=prob_word(p["snow"]), p=p["snow"], t=p["t50"], c=p["conf"])
        if p["nmodels"]:
            txt += " " + (T("Nessun modello dà la neve almeno a 30 scenari su 100.") if p["agree"] == 0 else
                          T("{k} modelli su {n} danno la neve ad almeno 30 scenari su 100.", k=p["agree"], n=p["nmodels"]))
        if p.get("best"):
            txt += " " + T("Il giorno più promettente per la neve è {d}.", d=p["best"])
        if p.get("cold_tail", 0) >= 10:
            txt += " " + T("Occhio al freddo: in {c} scenari su 100 a 1500 m si scende sotto −2 °C (i più freddi fino a {t} °C), "
                           "soprattutto intorno a {d}.", c=p["cold_tail"], t=p["tmin10"], d=p["cold_day"])
        if p is ph[0] and ls and p["snow"] < 25:
            txt += " " + T("I modelli globali, a maglie larghe, non colgono la nevicata in vetta di {d} che vedono "
                           "quelli ad alta risoluzione: in questi casi fidati della previsione locale.",
                           d=nice_date(ls["date"]))
        phases.append({"emoji": p["emoji"], "label": p["label"], "text": txt, "color": p["color"]})

    rows = sorted(top["rows"], key=lambda r: -r["snow"])
    models = []
    if rows and rows[0]["snow"] < 20:
        models.append(T("Nessun modello vede neve seria: il più ottimista, {m1}, arriva a {p1} scenari nevosi su 100.",
                        m1=rows[0]["name"], p1=rows[0]["snow"]))
    elif len(rows) >= 2:
        models.append(T("Tra {a} e {b} il modello più convinto è {m1} ({p1} scenari nevosi su 100), "
                        "il più scettico {m2} ({p2}).", a=top["from"], b=top["to"],
                        m1=rows[0]["name"], p1=rows[0]["snow"], m2=rows[-1]["name"], p2=rows[-1]["snow"]))
        models.append(T("Opinioni molto diverse: la previsione può ancora cambiare parecchio.")
                      if rows[0]["snow"] - rows[-1]["snow"] >= 40
                      else T("I modelli vanno abbastanza d'accordo: è un segnale da prendere sul serio."))

    weekend = []
    for b in bestpick or []:
        line = f"{b['name']}: {b['head'].rstrip('.')}."
        if not b.get("tie") and not b.get("red") and b["rows"]:
            line += " " + T("In testa: {l}.", l=", ".join(r["name"] for r in b["rows"][:3]))
        weekend.append(line)

    sts = sorted([s for s in _stations() if s.get("cm", 0) >= 2], key=lambda s: -s["cm"])[:6]
    if sts:
        ground = T("Al suolo, secondo le stazioni ufficiali: {l}.",
                   l=", ".join(T("{cm} cm a {st} ({e} m)", cm=s["cm"], st=s["name"].replace(" Nivo", ""), e=s["elev"])
                            for s in sts))
    else:
        ground = T("Per ora le stazioni ufficiali non misurano neve al suolo significativa.")

    sl = next((L.get("snowline") for L in (locs or []) if L.get("slug") == "abetone" and L.get("snowline")), None)
    pros = []
    wet = [d for d in (sl or []) if not d["dry"] and d["lv"]]
    if wet:
        pros.append(T("La nostra stima della quota neve sul crinale nei giorni con precipitazioni: {l}.",
                      l=", ".join(f"{d['name']} {d['lv']} m" for d in wet)))
        low_ = min(wet, key=lambda d: d["lv"])
        if low_["lv"] <= 1500:
            pros.append(T("Il giorno più interessante è {d}: con la neve intorno ai {lv} m si imbiancano anche le stazioni.",
                          d=low_["name"], lv=low_["lv"]))
        else:
            pros.append(T("Quote ancora alte: la neve, se arriva, resta sopra i {lv} m.", lv=low_["lv"]))
    big = [telev["head"]] + telev["lines"] if telev else []
    if telev and telev.get("score", 0) >= 1:
        cmax = max((p.get("cold_tail", 0) for p in ph), default=0)
        if cmax < 50:  # i due segnali vanno letti insieme, altrimenti sembrano in contraddizione
            big.append(T("Come si leggono insieme: il quadro generale dice che, nelle prossime settimane, il freddo è "
                         "più probabile del solito; i modelli per ora lo vedono in {c} scenari su 100, mentre gli altri "
                         "restano su tempo perturbato e mite, con neve solo in alta quota. Se il freddo si conferma, quel "
                         "numero salirà nei prossimi aggiornamenti: è il segnale da seguire.", c=cmax))
    return {"v": VERSION, "date": today, "title": title, "lead": lead, "phases": phases, "models": models, "pros": pros, "big": big,
            "weekend": weekend, "ground": ground, "chart": tv.get("chart", ""),
            "pub": nice_date(today)}


# ---------- v5: scritto come un pezzo da leggere, non come un elenco di numeri ----------

def frac(p: int) -> str:
    """Una quota di scenari detta a parole."""
    if p < 5:
        return T("quasi nessuno scenario")
    if p < 15:
        return T("circa uno scenario su dieci")
    if p < 25:
        return T("circa uno scenario su cinque")
    if p < 40:
        return T("circa uno scenario su tre")
    if p < 60:
        return T("circa la metà degli scenari")
    if p < 80:
        return T("due scenari su tre")
    return T("quasi tutti gli scenari")


def prose(label: str) -> str:
    """Il tipo di tempo detto come lo si direbbe a voce."""
    m = {T("Neve fino alle stazioni"): T("neve fino alle stazioni"),
         T("Neve in quota"): T("neve in quota"),
         T("Perturbato, neve solo in alta quota"): T("perturbazioni con neve solo sulle cime più alte"),
         T("Freddo e asciutto"): T("freddo secco"),
         T("Asciutto, temperature nella norma"): T("giornate asciutte e nella norma"),
         T("Asciutto e mite"): T("giornate asciutte e miti")}
    return m.get(label, low(label))


def describe(p: dict) -> str:
    """Una fase della tendenza in due o tre frasi."""
    mix = sorted(p.get("mix", []), key=lambda x: -x[2])
    if p["share"] >= 50 or len(mix) < 2:
        out = T("Prevalgono {a}, con temperature in quota intorno ai {t} °C.", a=prose(p["type"]), t=p["t50"])
    else:
        out = T("Si alternano {a} e {b}, con temperature in quota intorno ai {t} °C.",
                a=prose(mix[0][0]), b=prose(mix[1][0]), t=p["t50"])
    if p["snow"] >= 5:
        out += " " + T("La neve, almeno sulle cime, compare in {f}", f=frac(p["snow"]))
        out += (T(": il giorno più promettente è {d}.", d=p["best"]) if p.get("best") else ".")
    else:
        out += " " + T("Per la neve è un periodo di pausa.")
    if p.get("cold_tail", 0) >= 10:
        out += " " + T("Da tenere d'occhio il freddo: in {f} l'aria a 1500 m scende sotto i −2 °C, soprattutto intorno a {d}.",
                       f=frac(p["cold_tail"]), d=p["cold_day"])
    return out


def compose_v5(tv: dict, synv: dict, bestpick: list, today: str, locs: list | None, telev: dict | None) -> dict | None:
    if not tv or not tv.get("phases"):
        return None
    ph = tv["phases"]
    ls = local_snow(locs, today)
    top = max(ph[:3], key=lambda p: p["snow"])
    cold = max((p for p in ph if p.get("cold_tail", 0) >= 15), key=lambda p: p["cold_tail"], default=None)
    sl = next((L.get("snowline") for L in (locs or []) if L.get("slug") == "abetone" and L.get("snowline")), None) or []
    z = None
    if ls:
        z = next((d.get("late") or d.get("lv") for d in sl if d["date"] == ls["date"] and not d["dry"]), None)

    # titolo
    if top["snow"] >= 50 and top.get("snow_low", 0) >= 30:
        title = T("Arriva la neve fino alle stazioni tra {a} e {b}", a=top["from"], b=top["to"])
    elif top["snow"] >= 50:
        title = T("Torna la neve in quota tra {a} e {b}", a=top["from"], b=top["to"])
    elif ls and cold:
        title = T("Neve sulle cime {d}, e verso {c} si affaccia l'inverno", d=nice_date(ls["date"]), c=cold["cold_day"])
    elif ls:
        title = T("Neve sulle cime {d}, poi una pausa", d=nice_date(ls["date"]))
    elif cold:
        title = T("Per la neve bisogna pazientare, ma verso {c} si affaccia l'inverno", c=cold["cold_day"])
    elif top["snow"] >= 25:
        title = T("Si apre uno spiraglio per la neve tra {a} e {b}", a=top["from"], b=top["to"])
    else:
        title = T("Neve ancora in pausa: cosa ci aspetta nelle prossime settimane")

    # in breve
    brief = []
    if ls:
        brief.append(T("❄️ {d}: neve sulle cime{z}, fino a circa {cm} cm sul {w} ({e} m).", d=cap1(nice_date(ls["date"])),
                       z=(T(" dai {z} m circa in su", z=z) if z else ""), cm=ls["cm"], w=ls["where"], e=ls["elev"]))
    if len(ph) > 1 and ph[1].get("best") and ph[1]["snow"] >= 10:
        brief.append(T("👀 {d} è il giorno da segnare la prossima settimana: la neve compare in {f}.",
                       d=cap1(ph[1]["best"]), f=frac(ph[1]["snow"])))
    if cold:
        brief.append(T("🥶 Verso {d} il freddo prende forza: per ora compare in {f}.", d=cold["cold_day"], f=frac(cold["cold_tail"])))
    if telev and telev.get("score", 0) >= 1:
        brief.append(T("🌍 Il quadro generale, tra Artico e stratosfera, spinge nella stessa direzione."))

    sections = []
    # weekend
    wk = []
    for b in bestpick or []:
        if ls and b["name"].lower() in nice_date(ls["date"]).lower():
            continue  # quel giorno lo racconta la frase sulla nevicata
        h = b["head"].replace(":", ",", 1)
        wk.append(T("{d} {h}", d=b["name"], h=h[0].lower() + h[1:]))
    if ls:
        wk.append(T("Il momento più interessante è {d}: sulle cime cade neve{z}, e sul {w} ({e} m) se ne possono accumulare "
                    "circa {cm} cm. È un passaggio veloce: lo confermeranno i prossimi aggiornamenti.",
                    d=nice_date(ls["date"]), z=(T(" dai {z} m circa in su", z=z) if z else ""), w=ls["where"],
                    e=ls["elev"], cm=ls["cm"]))
    if wk:
        sections.append({"h": T("I prossimi giorni"), "p": [" ".join(wk)]})
    for p in ph[1:]:
        sections.append({"h": T("Da {a} a {b}", a=p["from"], b=p["to"]), "p": [describe(p)]})

    # quadro generale, raccontato
    if telev and telev.get("flags"):
        f = telev["flags"]
        big = []
        vx = f.get("vortex") or {}
        if vx.get("kind") == "ssw":
            big.append(T("A metà novembre è successa una cosa rara: intorno a {d} i venti della stratosfera sopra il Polo "
                         "si sono invertiti. Di solito succede in pieno inverno, e così presto non era mai capitato. "
                         "Quando accade, nelle settimane successive l'aria fredda ha più occasioni di scendere verso "
                         "l'Europa.", d=vx["date"]))
        elif vx.get("kind") == "ssw_coming":
            big.append(T("I modelli vedono i venti della stratosfera sopra il Polo invertirsi intorno a {d}: quando "
                         "succede, nelle settimane seguenti l'aria fredda ha più occasioni di scendere verso l'Europa.",
                         d=vx["date"]))
        elif vx.get("kind") == "weak":
            big.append(T("Il vortice polare, il grande giro di venti che tiene il freddo chiuso al Polo, è stato debole "
                         "nelle ultime settimane: un indizio a favore di ondate di freddo più avanti."))
        if f.get("ao") == "neg":
            big.append(T("Anche l'Oscillazione Artica è in calo, e va nella stessa direzione."))
        elif f.get("ao") == "pos":
            big.append(T("L'Oscillazione Artica però resta positiva: per ora il freddo tende a restare al nord."))
        if f.get("nao") == "neg":
            big.append(T("Sull'Atlantico la corrente scende verso sud: è la situazione che più spesso porta perturbazioni "
                         "e neve sul nostro crinale."))
        elif f.get("nao") == "pos":
            big.append(T("Sull'Atlantico invece domina l'anticiclone delle Azzorre, che tende a portare tempo stabile."))
        else:
            big.append(T("L'Atlantico invece non dà ancora indicazioni chiare."))
        if telev.get("score", 0) >= 1:
            cmax = max((p.get("cold_tail", 0) for p in ph), default=0)
            win = (T(" tra {a} e {b}", a=vx["a"], b=vx["b"]) if vx.get("kind") == "ssw" else "")
            big.append(T("Tradotto: il freddo è più probabile del solito{w}, ma non è sicuro, e non sappiamo ancora se "
                         "arriverà fino a noi o si fermerà più a est. I modelli per ora lo vedono in {f}: se quel numero "
                         "sale nei prossimi giorni, ci siamo.", w=win, f=frac(cmax)))
        if big:
            sections.append({"h": T("Perché si parla di freddo"), "p": [" ".join(big)]})

    sts = sorted([s for s in _stations() if s.get("cm", 0) >= 2], key=lambda s: -s["cm"])[:6]
    ground = (T("Al suolo, secondo le stazioni ufficiali: {l}.",
                l=", ".join(T("{cm} cm a {st} ({e} m)", cm=s["cm"], st=s["name"].replace(" Nivo", ""), e=s["elev"])
                            for s in sts)) if sts else
              T("Le stazioni ufficiali per ora non misurano neve al suolo: la stagione deve ancora cominciare."))
    return {"v": VERSION, "date": today, "title": title, "brief": brief, "sections": sections, "ground": ground,
            "lead": [" ".join(b.split(" ", 1)[1] if b[:1] in "❄👀🥶🌍" else b for b in brief[:2])] if brief else [title],
            "chart": tv.get("chart", ""), "pub": nice_date(today),
            "nscen": tv["nscen"], "nmodels": tv["nmodels"]}


def cap1(x: str) -> str:
    return x[:1].upper() + x[1:] if x else x


def save(lang: str, art: dict) -> None:
    d = DIR / art["date"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lang}.json").write_text(json.dumps(art, ensure_ascii=False))


def load_all(lang: str, keep: int = 30) -> list[dict]:
    if not DIR.exists():
        return []
    out = []
    for d in sorted(DIR.iterdir(), reverse=True)[:keep]:
        f = d / f"{lang}.json"
        if not f.exists():
            f = d / "it.json"
        if f.exists():
            out.append(json.loads(f.read_text()))
    return out
