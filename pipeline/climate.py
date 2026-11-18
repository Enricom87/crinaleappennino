"""Storico di dicembre per località (rianalisi ERA5 via Open-Meteo, corretta per la quota del punto).
Per ogni anno dal 1991: neve caduta, giorni con neve, giorni di ghiaccio (max ≤ 0), giorni di gelo (min ≤ 0),
minima assoluta, spessore massimo, neve a Natale. Si scarica solo ciò che manca; l'anno in corso si aggiorna
durante dicembre."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "climate.json"
URL = "https://archive-api.open-meteo.com/v1/archive"
FIRST = 1991
MAX_CALLS = 420  # per run: ~1 chiamata pesata ciascuna, lontano dal limite giornaliero
VARS = "temperature_2m_max,temperature_2m_min,snowfall_sum,snow_depth_max,precipitation_sum"


def summarize(d: dict) -> dict:
    tx, tn = d["temperature_2m_max"], d["temperature_2m_min"]
    sf, sd, pr = d["snowfall_sum"], d["snow_depth_max"], d["precipitation_sum"]
    days = d["time"]
    ok = [i for i in range(len(days)) if tx[i] is not None and tn[i] is not None]
    if len(ok) < 25:
        return {}
    xmas = days.index(days[0][:8] + "25") if any(t.endswith("-25") for t in days) else None
    return {
        "n": len(ok),
        "snow": round(sum(x or 0 for x in sf), 1),
        "snow_days": sum(1 for x in sf if (x or 0) >= 1),
        "ice": sum(1 for i in ok if tx[i] <= 0),
        "frost": sum(1 for i in ok if tn[i] <= 0),
        "tmin": round(min(tn[i] for i in ok), 1),
        "tmean": round(sum((tx[i] + tn[i]) / 2 for i in ok) / len(ok), 1),
        "depth": round(max((x or 0) for x in sd) * 100),
        "xmas": xmas is not None and (sd[xmas] or 0) >= 0.02,
        "rain": round(sum(x or 0 for x in pr), 1),
    }


def main() -> None:
    cfg = json.loads((ROOT / "config" / "locations.json").read_text())
    pts = cfg["points"]
    try:
        data = json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        data = {}
    today = dt.date.today()
    last = today.year if today.month == 12 else today.year - 1
    s = requests.Session()
    calls = 0
    for L in cfg["locations"]:
        p = pts[L["points"][0]]
        rec = data.setdefault(L["slug"], {"point": p["name"], "elev": p["elev"], "years": {}})
        rec.update(point=p["name"], elev=p["elev"])
        for y in range(FIRST, last + 1):
            cur = y == today.year and today.month == 12
            if str(y) in rec["years"] and not cur:
                continue
            if calls >= MAX_CALLS:
                break
            end = min(dt.date(y, 12, 31), today - dt.timedelta(days=6)) if cur else dt.date(y, 12, 31)
            if end < dt.date(y, 12, 1):
                continue
            q = {"latitude": p["lat"], "longitude": p["lon"], "elevation": p["elev"],
                 "start_date": f"{y}-12-01", "end_date": end.isoformat(), "daily": VARS,
                 "models": "era5_seamless", "timezone": "Europe/Rome"}
            for att in range(3):
                calls += 1
                try:
                    r = s.get(URL, params=q, timeout=60)
                    if r.status_code == 429:
                        time.sleep(30 * (att + 1))
                        continue
                    r.raise_for_status()
                    sm = summarize(r.json()["daily"])
                    if sm:
                        if cur:
                            sm["partial"] = end.isoformat()
                        rec["years"][str(y)] = sm
                    break
                except Exception as ex:  # noqa: BLE001
                    print(f"storico {L['slug']} {y}: {ex}")
                    time.sleep(3)
            time.sleep(0.4)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    have = sum(len(v["years"]) for v in data.values())
    print(f"storico dicembre: {calls} chiamate, {have} anni-località in archivio")


if __name__ == "__main__":
    main()
