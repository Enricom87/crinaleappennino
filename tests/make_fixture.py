"""Genera dati finti con la stessa forma delle risposte Open-Meteo (solo per collaudo offline)."""
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config" / "locations.json").read_text())
random.seed(7)
start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)


def times(days):
    return [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M") for h in range(days * 24)]


def series(elev, days, bias=0.0, wet=1.0):
    T, P, RH, FL, G = [], [], [], [], []
    for h in range(days * 24):
        d = h / 24
        base = 8 - 0.0065 * (elev - 1400) * 1 - 0.9 * max(0, d - 5) + bias  # raffreddamento dal 6° giorno
        t = base + 3 * math.sin((h % 24 - 9) / 24 * 2 * math.pi)
        rain = 0.0
        if 1 <= d < 2 or 9 <= d < 11:
            rain = max(0, random.gauss(1.2, 0.8)) * wet
        T.append(round(t, 1)); P.append(round(rain, 1))
        RH.append(95 if rain else 70); FL.append(round(max(600, 1400 + t * 160)))
        G.append(round(30 + (50 if 9 <= d < 10 else 0) + random.random() * 10))
    return T, P, RH, FL, G


raw = ROOT / "data" / "raw"
raw.mkdir(parents=True, exist_ok=True)
glob, lam, ens = {}, {}, {}
for pid, p in cfg["points"].items():
    h = {"time": times(15)}
    for m, b in (("ecmwf_ifs025", 0), ("gfs_global", 1.5), ("icon_global", -0.5)):
        T, P, RH, FL, G = series(p["elev"], 15, b)
        h.update({f"temperature_2m_{m}": T, f"precipitation_{m}": P, f"relative_humidity_2m_{m}": RH,
                  f"freezing_level_height_{m}": FL, f"wind_gusts_10m_{m}": G,
                  f"cape_{m}": [round(max(0, 900 * math.sin((i % 24 - 10) / 10 * math.pi)) * (1 if (i // 24) in (0, 3) else 0.2)) for i in range(len(T))],
                  f"cloud_cover_{m}": [40] * len(T)})
    glob[pid] = {"hourly": h}
    h = {"time": times(3)}
    for m in ("italia_meteo_arpae_icon_2i", "icon_d2", "meteoswiss_icon_ch2", "meteofrance_arome_france"):
        T, P, RH, FL, G = series(p["elev"], 3, random.uniform(-1, 1))
        h.update({f"temperature_2m_{m}": T, f"precipitation_{m}": P, f"relative_humidity_2m_{m}": RH,
                  f"freezing_level_height_{m}": FL, f"wind_gusts_10m_{m}": G,
                  f"cape_{m}": [round(max(0, 900 * math.sin((i % 24 - 10) / 10 * math.pi)) * (1 if (i // 24) in (0, 3) else 0.2)) for i in range(len(T))],
                  f"cloud_cover_{m}": [40] * len(T)})
    lam[pid] = {"hourly": h}
    h = {"time": times(15)}
    for k in range(51):
        T, P, *_ = series(p["elev"], 15, random.gauss(0, 2), random.uniform(0.3, 1.8))
        suf = "" if k == 0 else f"_member{k:02d}"
        h[f"temperature_2m{suf}"] = T
        h[f"precipitation{suf}"] = P
    ens[pid] = {"hourly": h}

syn = {}
for key, z0 in (("west", 5500), ("center", 5560), ("east", 5600)):
    h = {"time": times(15)}
    for m, b in (("ecmwf_ifs025", 0), ("gfs_global", 1.5)):
        h[f"temperature_850hPa_{m}"] = [round(4 - 0.9 * max(0, i / 24 - 5) + b, 1) for i in range(360)]
        h[f"wind_direction_700hPa_{m}"] = [230 if i < 200 else 20 for i in range(360)]
        h[f"wind_speed_700hPa_{m}"] = [40] * 360
        h[f"geopotential_height_500hPa_{m}"] = [z0 - (i // 24) * 8 for i in range(360)]
        h[f"precipitation_{m}"] = [1.0 if 24 <= i < 48 or 216 <= i < 264 else 0 for i in range(360)]
    syn[key] = {"hourly": h}

for name, obj in (("global", glob), ("lam", lam), ("ensemble", ens), ("synoptic", syn)):
    (raw / f"{name}.json").write_text(json.dumps(obj))
print("fixture ok")
