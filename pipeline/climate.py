"""Storico delle stagioni invernali (1 dicembre – 31 marzo) per località, dal 1991/92.
Rianalisi ERA5 via Open-Meteo, riportata alla quota del punto. Per ogni stagione: neve caduta (totale e per mese),
giorni con neve, giorni di ghiaccio (max ≤ 0), giorni di gelo (min ≤ 0), minima assoluta, temperatura media,
neve al suolo a Natale. Si scarica solo ciò che manca; la stagione in corso si aggiorna finché non si chiude."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "seasons.json"
URL = "https://archive-api.open-meteo.com/v1/archive"
FIRST = 1991          # stagione 1991/92
MAX_CALLS = 200       # per run (~3,5 chiamate pesate ciascuna): resta lontano dai limiti del piano gratuito
LAG = 6               # la rianalisi arriva con ~5 giorni di ritardo
VARS = "temperature_2m_max,temperature_2m_min,snowfall_sum,snow_depth_max"
MONTHS = ("12", "01", "02", "03")


def summarize(d: dict) -> dict:
    tx, tn, sf, sd, days = (d["temperature_2m_max"], d["temperature_2m_min"], d["snowfall_sum"],
                            d["snow_depth_max"], d["time"])
    ok = [i for i in range(len(days)) if tx[i] is not None and tn[i] is not None]
    if len(ok) < 20:
        return {}
    xmas = next((i for i, t in enumerate(days) if t.endswith("-12-25")), None)
    return {
        "n": len(ok),
        "snow": round(sum(x or 0 for x in sf), 1),
        "months": {m: round(sum(sf[i] or 0 for i, t in enumerate(days) if t[5:7] == m), 1) for m in MONTHS},
        "snow_days": sum(1 for x in sf if (x or 0) >= 1),
        "ice": sum(1 for i in ok if tx[i] <= 0),
        "frost": sum(1 for i in ok if tn[i] <= 0),
        "tmin": round(min(tn[i] for i in ok), 1),
        "tmean": round(sum((tx[i] + tn[i]) / 2 for i in ok) / len(ok), 1),
        "xmas": xmas is not None and (sd[xmas] or 0) >= 0.02,
    }


def main() -> None:
    cfg = json.loads((ROOT / "config" / "locations.json").read_text())
    pts = cfg["points"]
    try:
        data = json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        data = {}
    today = dt.date.today()
    avail = today - dt.timedelta(days=LAG)
    last = today.year if today.month == 12 else today.year - 1
    s = requests.Session()
    calls, stop = 0, False
    for L in cfg["locations"]:
        if stop:
            break
        p = pts[L["points"][0]]
        rec = data.setdefault(L["slug"], {"years": {}})
        rec.update(point=p["name"], elev=p["elev"])
        for y in range(FIRST, last + 1):
            start, end = dt.date(y, 12, 1), dt.date(y + 1, 3, 31)
            partial = end > avail
            have = rec["years"].get(str(y))
            if have and not have.get("partial"):
                continue
            if have and have.get("partial") == min(end, avail).isoformat():
                continue
            if avail < start:
                continue
            if calls >= MAX_CALLS:
                stop = True
                break
            q = {"latitude": p["lat"], "longitude": p["lon"], "elevation": p["elev"],
                 "start_date": start.isoformat(), "end_date": min(end, avail).isoformat(), "daily": VARS,
                 "models": "era5_seamless", "timezone": "Europe/Rome"}
            calls += 1
            try:
                r = s.get(URL, params=q, timeout=60)
                if r.status_code == 429:
                    print("storico: limite Open-Meteo raggiunto, riprendo al prossimo run")
                    stop = True
                    break
                r.raise_for_status()
                sm = summarize(r.json()["daily"])
                if sm:
                    if partial:
                        sm["partial"] = min(end, avail).isoformat()
                    rec["years"][str(y)] = sm
            except Exception as ex:  # noqa: BLE001
                print(f"storico {L['slug']} {y}/{y + 1}: {ex}")
            time.sleep(0.3)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    have = sum(len(v["years"]) for v in data.values())
    print(f"storico stagioni: {calls} chiamate, {have} stagioni-località in archivio")


if __name__ == "__main__":
    main()
