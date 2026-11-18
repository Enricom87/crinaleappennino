"""Il quadro generale per le tendenze a 2–4 settimane: NAO, AO e vortice polare.

- NAO e AO: indici giornalieri osservati e previsti dall'ensemble GEFS (31 scenari, 16 giorni),
  pubblicati dal Climate Prediction Center della NOAA (dati pubblici).
- Vortice polare: vento medio da ovest a 10 hPa (~30 km) lungo il 60° parallelo, calcolato da GFS su
  24 punti tramite Open-Meteo. Sotto i 15 m/s è debole; sotto zero è un riscaldamento stratosferico
  improvviso, che nelle settimane seguenti aumenta le probabilità di irruzioni fredde in Europa.

Non cambia i numeri della tendenza: li spiega e indica la direzione in cui potrebbero muoversi."""
from __future__ import annotations

import csv
import io
import json
import math
import statistics as st
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "teleconn.json"
CPC = "https://ftp.cpc.ncep.noaa.gov/cwlinks/"
FILES = {"nao": ("norm.daily.nao.gefs.z500.120days.csv", "nao_index"),
         "ao": ("norm.daily.ao.gefs.z1000.120days.csv", "ao_index")}
OM = "https://api.open-meteo.com/v1/gfs"


def cpc(key: str) -> dict:
    fname, col = FILES[key]
    txt = requests.get(CPC + fname, timeout=60).text
    rows = list(csv.DictReader(io.StringIO(txt)))
    issue = max(r["time"] for r in rows if r["lead"] != "0") if any(r["lead"] != "0" for r in rows) else None
    obs = {r["valid_time"]: float(r[col]) for r in rows if r["lead"] == "0" and r.get("member", "0") == "0"}
    fc = defaultdict(list)
    for r in rows:
        if r["lead"] != "0" and r["time"] == issue:
            fc[r["valid_time"]].append(float(r[col]))
    last = sorted(obs)[-10:]
    return {"issue": issue, "obs": {d: round(obs[d], 2) for d in last},
            "fc": {d: {"mean": round(st.mean(v), 2), "neg": round(sum(1 for x in v if x <= -0.5) / len(v), 2),
                       "pos": round(sum(1 for x in v if x >= 0.5) / len(v), 2), "n": len(v)}
                   for d, v in sorted(fc.items())}}


def vortex() -> dict:
    lons = list(range(-180, 180, 15))
    q = {"latitude": ",".join(["60"] * len(lons)), "longitude": ",".join(map(str, lons)),
         "hourly": "wind_speed_10hPa,wind_direction_10hPa", "models": "gfs_global", "forecast_days": 16,
         "past_days": 5, "wind_speed_unit": "ms", "timezone": "GMT"}
    data = requests.get(OM, params=q, timeout=120).json()
    data = data if isinstance(data, list) else [data]
    by_day = defaultdict(list)
    for d in data:
        h = d["hourly"]
        for t, sp, di in zip(h["time"], h["wind_speed_10hPa"], h["wind_direction_10hPa"]):
            if sp is None or di is None or not t.endswith("12:00"):
                continue
            by_day[t[:10]].append(-sp * math.sin(math.radians(di)))  # componente da ovest (positiva = vortice)
    return {d: round(st.mean(v), 1) for d, v in sorted(by_day.items()) if len(v) >= len(lons) // 2}


def main() -> None:
    try:
        old = json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        old = {}
    out = dict(old)
    for k in FILES:
        try:
            out[k] = cpc(k)
        except Exception as ex:  # noqa: BLE001
            print(f"quadro generale: {k} non disponibile ({ex})")
    try:
        out["vortex"] = vortex()
    except Exception as ex:  # noqa: BLE001
        print(f"quadro generale: vortice non disponibile ({ex})")
    out["updated"] = date.today().isoformat()
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    nao = out.get("nao", {}).get("fc", {})
    print("quadro generale:", "NAO", [v["mean"] for v in list(nao.values())[-5:]], "vortice", list(out.get("vortex", {}).values())[-3:])


# ---------- lettura per il sito ----------

def load() -> dict:
    try:
        return json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _tail(fc: dict, today: str, a: int, b: int) -> list[dict]:
    t = date.fromisoformat(today)
    keep = {(t + timedelta(days=i)).isoformat() for i in range(a, b)}
    return [v for d, v in fc.items() if d in keep]


def view(today: str) -> dict | None:
    """Frasi in chiaro nella lingua corrente, più un indicatore complessivo (-2 sfavorevole … +2 favorevole
    al freddo e alla neve sull'Appennino settentrionale)."""
    from i18n import T, nice_date
    tc = load()
    if not tc:
        return None
    lines, score = [], 0
    nao = tc.get("nao", {}).get("fc", {})
    wk2 = _tail(nao, today, 7, 16)
    if wk2:
        m = st.mean(v["mean"] for v in wk2)
        neg = round(100 * st.mean(v["neg"] for v in wk2))
        pos = round(100 * st.mean(v["pos"] for v in wk2))
        if m <= -0.5:
            score += 1
            lines.append(T("NAO negativa nella seconda settimana ({n} scenari su 100): la corrente atlantica scende "
                           "verso sud e apre la strada a saccature e minimi sul Mediterraneo, la situazione che più "
                           "spesso porta neve sul crinale.", n=neg))
        elif m >= 0.5:
            score -= 1
            lines.append(T("NAO positiva nella seconda settimana ({n} scenari su 100): l'anticiclone delle Azzorre "
                           "tende a coprire il Mediterraneo, con tempo più asciutto e mite in Appennino.", n=pos))
        else:
            lines.append(T("NAO vicina a zero nella seconda settimana: nessuna spinta chiara né verso il freddo né "
                           "verso l'anticiclone ({a} scenari negativi, {b} positivi su 100).", a=neg, b=pos))
    ao = tc.get("ao", {}).get("fc", {})
    wk2 = _tail(ao, today, 7, 16)
    if wk2:
        m = st.mean(v["mean"] for v in wk2)
        if m <= -1:
            score += 1
            lines.append(T("Oscillazione Artica in forte calo: l'aria fredda polare tende a scivolare verso le medie "
                           "latitudini, Europa compresa."))
        elif m >= 1:
            score -= 1
            lines.append(T("Oscillazione Artica positiva: il freddo resta chiuso intorno al Polo."))
    vx = tc.get("vortex", {})
    fut = [(d, v) for d, v in vx.items() if d >= today]
    if fut:
        dmin, vmin = min(fut, key=lambda x: x[1])
        now = fut[0][1]
        if vmin < 0:
            score += 2
            lines.append(T("Vortice polare in crisi: GFS vede l'inversione dei venti in stratosfera intorno a {d} "
                           "(riscaldamento stratosferico improvviso). Nelle 2–4 settimane successive aumentano le "
                           "probabilità di irruzioni fredde verso l'Europa, anche se non è una garanzia.", d=nice_date(dmin)))
        elif vmin < 15:
            score += 1
            lines.append(T("Vortice polare debole (vento in stratosfera fino a {v} m/s intorno a {d}): è più facile che "
                           "l'aria fredda si stacchi dal Polo nelle settimane successive.", v=round(vmin), d=nice_date(dmin)))
        elif now >= 40:
            score -= 1
            lines.append(T("Vortice polare forte ({v} m/s): di solito tiene il freddo chiuso al nord.", v=round(now)))
        else:
            lines.append(T("Vortice polare nella norma ({v} m/s): nessun segnale particolare dalla stratosfera.", v=round(now)))
    if not lines:
        return None
    if score >= 2:
        head = T("Il quadro generale spinge verso il freddo: le prossime corse dei modelli potrebbero aumentare la neve.")
    elif score == 1:
        head = T("Il quadro generale è leggermente favorevole al freddo.")
    elif score <= -1:
        head = T("Il quadro generale non aiuta: prevalgono i segnali di tempo mite e anticiclonico.")
    else:
        head = T("Il quadro generale è neutro: nessuna spinta decisa.")
    return {"head": head, "lines": lines, "score": score,
            "nao": [(d, v["mean"]) for d, v in nao.items()], "vortex": list(vx.items())}


if __name__ == "__main__":
    main()
