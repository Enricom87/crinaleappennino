"""Download dei dati dei modelli da Open-Meteo.

Senza chiave usa l'API gratuita (solo uso non commerciale).
Con la variabile d'ambiente OPEN_METEO_API_KEY usa l'API commerciale.
Tutte le risposte grezze vengono salvate in data/raw/ così il resto della
pipeline può girare anche offline (e i test usano gli stessi file).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

API_KEY = os.environ.get("OPEN_METEO_API_KEY", "").strip()
FORECAST_URL = ("https://customer-api.open-meteo.com/v1/forecast" if API_KEY
                else "https://api.open-meteo.com/v1/forecast")
ENSEMBLE_URL = ("https://customer-ensemble-api.open-meteo.com/v1/ensemble" if API_KEY
                else "https://ensemble-api.open-meteo.com/v1/ensemble")

LAM_MODELS = ["italia_meteo_arpae_icon_2i", "icon_d2", "meteoswiss_icon_ch2", "meteofrance_arome_france"]
GLOBAL_MODELS = ["ecmwf_ifs025", "gfs_global", "icon_global"]
ENSEMBLE_MODELS = ["ecmwf_ifs025"]
SURFACE_VARS = "temperature_2m,relative_humidity_2m,precipitation,freezing_level_height,wind_gusts_10m"
SYNOPTIC_VARS = "temperature_850hPa,wind_direction_700hPa,wind_speed_700hPa,geopotential_height_500hPa,precipitation"


def _get(url: str, params: dict, retries: int = 3) -> dict | list:
    if API_KEY:
        params = {**params, "apikey": API_KEY}
    for attempt in range(retries):
        r = requests.get(url, params=params, timeout=90)
        if r.status_code == 429 and attempt < retries - 1:
            time.sleep(70)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def _coords(points: list[dict]) -> dict:
    return {
        "latitude": ",".join(f"{p['lat']:.4f}" for p in points),
        "longitude": ",".join(f"{p['lon']:.4f}" for p in points),
        "elevation": ",".join(str(p["elev"]) for p in points),
        "timezone": "Europe/Rome",
    }


def _as_list(resp) -> list:
    return resp if isinstance(resp, list) else [resp]


def fetch_all(config: dict, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    ids = list(config["points"].keys())
    pts = [config["points"][i] for i in ids]

    jobs = {
        "global": (FORECAST_URL, {**_coords(pts), "hourly": SURFACE_VARS,
                                  "models": ",".join(GLOBAL_MODELS), "forecast_days": 15}),
        "lam": (FORECAST_URL, {**_coords(pts), "hourly": SURFACE_VARS,
                               "models": ",".join(LAM_MODELS), "forecast_days": 3}),
        "ensemble": (ENSEMBLE_URL, {**_coords(pts), "hourly": "temperature_2m,precipitation",
                                    "models": ",".join(ENSEMBLE_MODELS), "forecast_days": 15}),
    }
    for name, (url, params) in jobs.items():
        data = _as_list(_get(url, params))
        out = {pid: d for pid, d in zip(ids, data)}
        (raw_dir / f"{name}.json").write_text(json.dumps(out))
        time.sleep(5)

    syn = config["synoptic"]
    syn_pts = [dict(syn["west"], elev=0), dict(syn["center"], elev=1500), dict(syn["east"], elev=0)]
    data = _as_list(_get(FORECAST_URL, {**_coords(syn_pts), "hourly": SYNOPTIC_VARS,
                                        "models": "ecmwf_ifs025,gfs_global", "forecast_days": 15}))
    (raw_dir / "synoptic.json").write_text(json.dumps(dict(zip(["west", "center", "east"], data))))


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config" / "locations.json").read_text())
    fetch_all(cfg, root / "data" / "raw")
    print("ok")
