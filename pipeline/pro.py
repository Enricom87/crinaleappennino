"""Spunto dai meteorologi: il Bollettino Montagna del Consorzio LaMMA (servizio meteo della Regione
Toscana) dà per i prossimi 3 giorni la quota neve scritta da previsori umani. È un ingresso interno
del nostro calcolo, non un contenuto da ripubblicare: (1) frena la neve dei modelli molto sotto quella
quota, (2) corregge la nostra stima della quota neve, che sul sito è nostra (vedi snowline())."""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pro.json"
URL = "https://www.lamma.toscana.it/meteo/bollettini-meteo/montagna"
ZONES = {"pistoiese": "div-app_pt", "garfagnana": "div-app_lu"}  # id dei riquadri nella pagina LaMMA
# zona LaMMA di riferimento per ogni località (il crinale è lo stesso: la quota neve vale anche sul versante emiliano)
ZONE_FOR = {"abetone": "pistoiese", "doganaccia": "pistoiese", "cimone": "pistoiese", "le-polle": "pistoiese",
            "cimoncino": "pistoiese", "lago-santo": "pistoiese", "corno-alle-scale": "pistoiese",
            "lago-scaffaiolo": "pistoiese", "garfagnana": "garfagnana", "cerreto-laghi": "garfagnana",
            "febbio": "garfagnana"}
MONTHS = {m: i for i, m in enumerate(["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
                                      "agosto", "settembre", "ottobre", "novembre", "dicembre"], 1)}
MARGIN = 200  # m: tolleranza sotto la quota neve del LaMMA (la neve «bagnata» scende un po' più in basso)


def parse(html: str, year: int) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for key, div_id in ZONES.items():
        box = soup.find(id=div_id)
        if not box:
            continue
        txt = re.sub(r"\s+", " ", box.get_text(" "))
        days = {}
        for part in re.split(r"Previsione per ", txt)[1:]:
            m = re.match(r"\w+\s+(\d{1,2})\s+(\w+)", part)
            if not m or m.group(2).lower() not in MONTHS:
                continue
            d = date(year, MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
            snow = [int(x) for x in re.findall(r"Quota neve:\s*(\d+)\s*m", part)]
            fl = [int(x) for x in re.findall(r"Zero termico:\s*(\d+)\s*m", part)]
            sky = re.search(r"stato del cielo e fenomeni:\s*(.+?)(?:venti:|$)", part)
            if snow:
                days[d] = {"snow_level": min(snow), "fl": min(fl) if fl else None,
                           "sky": sky.group(1).strip() if sky else ""}
        if days:
            out[key] = days
    return out


def main() -> None:
    try:
        r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0 (compatible; crinaleappennino.it)"})
        r.raise_for_status()
        data = parse(r.text, date.today().year)
    except Exception as ex:  # noqa: BLE001
        print(f"LaMMA: bollettino non disponibile ({ex})")
        return
    if not data:
        print("LaMMA: bollettino non interpretato, tengo l'ultimo")
        return
    OUT.write_text(json.dumps({"source": {"name": "Consorzio LaMMA", "url": URL}, "zones": data},
                              ensure_ascii=False, indent=1))
    print("LaMMA: " + "; ".join(f"{k} " + ", ".join(f"{d[5:]} {v['snow_level']} m" for d, v in z.items())
                                 for k, z in data.items()))


def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        return {}


def apply(base_locs: list[dict], pts: dict) -> dict:
    """Toglie la neve prevista dai modelli nei punti molto sotto la quota neve del LaMMA.
    Ritorna, per località, le note da mostrare: {slug: {date: snow_level}}."""
    pro = load().get("zones") or {}
    notes: dict[str, dict] = {}
    done = set()
    for loc in base_locs:
        z = pro.get(ZONE_FOR.get(loc["slug"], ""))
        if not z:
            continue
        notes[loc["slug"]] = {d: v["snow_level"] for d, v in z.items()}
        for pid in loc["points"]:
            if pid in done or pid not in pts:
                continue
            done.add(pid)
            p = pts[pid]
            for d in p["days"]:
                lv = z.get(d["date"], {}).get("snow_level")
                if lv and p["elev"] < lv - MARGIN and (d.get("snow") or 0) > 0:
                    d["snow_model"] = d["snow"]
                    for k in ("snow", "snow_min", "snow_max"):
                        if k in d:
                            d[k] = 0.0
                    d["pro_capped"] = lv
            for h in p.get("hours", []):
                lv = z.get(h["time"][:10], {}).get("snow_level")
                if lv and p["elev"] < lv - MARGIN and h.get("snow"):
                    h["snow"] = 0.0
    return notes


if __name__ == "__main__":
    main()


def snowline(loc: dict, pts: dict, today: str, zone_days: dict | None = None, n: int = 5,
             levels: dict | None = None, offset: int = 0) -> list[dict]:
    """La nostra quota neve per i prossimi giorni, nel punto più alto della località: calcolata dal profilo
    verticale col bulbo umido (pipeline/snowlevel.py), o in mancanza zero termico − 300 m; corretta dalla
    taratura con le segnalazioni; se c'è il bollettino dei previsori pesa per il 30%.
    Arrotondata a 100 m. Nei giorni senza precipitazioni la quota neve non ha senso: «asciutto»."""
    from i18n import day_short
    top = max((pts[p] for p in loc["points"] if p in pts), key=lambda p: p["elev"])
    out = []
    for d in top["days"]:
        if d["date"] < today or len(out) >= n:
            continue
        lv = None
        prof = ((levels or {}).get(top["id"]) or {}).get(d["date"])
        if prof:
            lv = prof["lv"] + offset
        elif d.get("fl_min") is not None:
            lv = d["fl_min"] - 300 + offset
        pro_lv = (zone_days or {}).get(d["date"], {}).get("snow_level")
        if pro_lv and lv is not None:
            lv = 0.7 * lv + 0.3 * pro_lv
        elif pro_lv:
            lv = pro_lv
        dry = (d.get("precip") or 0) < 1
        out.append({"date": d["date"], "name": day_short(d["date"]), "dry": dry,
                    "lv": int(round(max(lv, 300) / 100) * 100) if lv is not None else None})
    return out
