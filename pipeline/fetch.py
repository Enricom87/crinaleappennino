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
SURFACE_VARS = ("temperature_2m,relative_humidity_2m,precipitation,freezing_level_height,wind_gusts_10m,"
                "cape,cloud_cover,cloud_cover_low")
# ensemble per la tendenza: chiave, modello Open-Meteo, temperatura usata, giorni richiesti
TREND_MODELS = [
    ("ecmwf", "ecmwf_ifs025", "temperature_850hPa", 15),
    ("aifs", "ecmwf_aifs025", "temperature_850hPa", 15),
    ("gfs", "gfs05", "temperature_850hPa", 35),
    ("gem", "gem_global", "temperature_850hPa", 35),
    ("weathernext", "google_weathernext2_ensemble", "temperature_850hPa", 16),
    ("icon", "icon_seamless", "temperature_2m", 8),
    ("ukmo", "ukmo_global_ensemble_20km", "temperature_2m", 11),
    ("ch2", "meteoswiss_icon_ch2", "temperature_2m", 6),
]
PROFILE_MODELS = ["italia_meteo_arpae_icon_2i", "meteofrance_arome_france", "ecmwf_ifs025", "icon_global"]
PROFILE_VARS = ",".join(f"{v}_{p}hPa" for p in (925, 850, 700)
                        for v in ("temperature", "relative_humidity", "geopotential_height")) + ",precipitation"
SYNOPTIC_VARS = "temperature_850hPa,wind_direction_700hPa,wind_speed_700hPa,geopotential_height_500hPa,precipitation"


LIMITED = False  # superato il limite orario o giornaliero: si salta il resto e si tengono i dati precedenti


def _get(url: str, params: dict, retries: int = 4) -> dict | list:
    global LIMITED
    if LIMITED:
        raise RuntimeError("limite Open-Meteo raggiunto, salto")
    if API_KEY:
        params = {**params, "apikey": API_KEY}
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=90)
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(20 * (attempt + 1))
            continue
        if r.status_code == 429:
            msg = r.text[:200]
            print(f"limite di richieste Open-Meteo: {msg}", flush=True)
            if "inute" not in msg or attempt == retries - 1:  # limite orario/giornaliero: inutile aspettare
                LIMITED = True
                r.raise_for_status()
            time.sleep(65)
            continue
        if r.status_code in (500, 502, 503, 504) and attempt < retries - 1:
            time.sleep(20)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("unreachable")


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _fetch_merged(url: str, ids: list[str], pts: list[dict], base: dict, models: list[str],
                  chunk: int, suffix_single: bool = True) -> dict:
    """Una richiesta per modello e per gruppo di punti; unisce le serie orarie per punto."""
    out: dict[str, dict] = {}
    for m in models:
        for grp in _chunks(list(zip(ids, pts)), chunk):
            gids, gpts = [g[0] for g in grp], [g[1] for g in grp]
            try:
                data = _as_list(_get(url, {**_coords(gpts), **base, "models": m}))
            except Exception as e:  # un modello o un gruppo che fallisce non blocca il resto
                print(f"saltato {m} per {gids}: {e}")
                continue
            for pid, d in zip(gids, data):
                h = d.get("hourly", {})
                dst = out.setdefault(pid, {"hourly": {"time": h.get("time", [])}})["hourly"]
                for k, v in h.items():
                    if k == "time":
                        continue
                    key = k if (not suffix_single or k.endswith("_" + m)) else f"{k}_{m}"
                    dst[key] = v
            time.sleep(2)
    return out


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
        "global": (FORECAST_URL, {"hourly": SURFACE_VARS, "forecast_days": 15, "past_days": 2}, GLOBAL_MODELS, 8, True),
        "lam": (FORECAST_URL, {"hourly": SURFACE_VARS, "forecast_days": 3}, LAM_MODELS, 12, True),
        # profilo verticale per la quota neve calcolata col bulbo umido (vedi pipeline/snowlevel.py)
        "profile": (FORECAST_URL, {"hourly": PROFILE_VARS, "forecast_days": 7}, PROFILE_MODELS, 12, True),
        "ensemble": (ENSEMBLE_URL, {"hourly": "temperature_2m,precipitation,freezing_level_height", "forecast_days": 15},
                     ENSEMBLE_MODELS, 3, False),
    }
    only = [x for x in os.environ.get("FETCH_ONLY", "").split(",") if x]
    if only:  # aggiornamento leggero: solo i modelli dei primi giorni, il resto viene dalla cache dell'ultimo giro
        jobs = {k: v for k, v in jobs.items() if k in only}
    for name, (url, base, models, chunk, suffix) in jobs.items():
        out = _fetch_merged(url, ids, pts, base, models, chunk, suffix)
        if LIMITED or not out:
            print(f"{name}: tengo i dati precedenti", flush=True)
            continue
        (raw_dir / f"{name}.json").write_text(json.dumps(out))
        print(f"{name}: {len(out)} punti", flush=True)
        time.sleep(5)

    if only:
        return
    syn = config["synoptic"]
    syn_pts = [dict(syn["west"], elev=0), dict(syn["center"], elev=1500), dict(syn["east"], elev=0)]
    try:
        data = _as_list(_get(FORECAST_URL, {**_coords(syn_pts), "hourly": SYNOPTIC_VARS,
                                            "models": "ecmwf_ifs025,gfs_global", "forecast_days": 15}))
        (raw_dir / "synoptic.json").write_text(json.dumps(dict(zip(["west", "center", "east"], data))))
    except Exception as e:
        print(f"configurazione sinottica non disponibile: {e}")
    # tendenza: tutti gli ensemble disponibili sopra il crinale (vedi pipeline/trend.py)
    ens_dir = raw_dir / "ens_trend"
    ens_dir.mkdir(exist_ok=True)
    for key, model, tvar, days in TREND_MODELS:
        try:
            time.sleep(2)
            d = _get(ENSEMBLE_URL, {**_coords([dict(syn["center"], elev=1500)]), "models": model,
                                    "hourly": f"{tvar},precipitation" + (",wind_direction_700hPa" if tvar == "temperature_850hPa" else ""),
                                    "forecast_days": days})
            (ens_dir / f"{key}.json").write_text(json.dumps(_as_list(d)[0]))
            print(f"tendenza {key}: ok")
        except Exception as e:
            print(f"tendenza {key} non disponibile: {e}")


RUN_META = {  # quando è partita e quando è uscita l'ultima corsa di ogni modello (per dirlo sul sito)
    "ecmwf": "https://api.open-meteo.com/data/ecmwf_ifs025/static/meta.json",
    "ens": "https://ensemble-api.open-meteo.com/data/ecmwf_ifs025_ensemble/static/meta.json",
    "gfs": "https://api.open-meteo.com/data/ncep_gfs025/static/meta.json",
    "icon2i": "https://api.open-meteo.com/data/italia_meteo_arpae_icon_2i/static/meta.json",
    "arome": "https://api.open-meteo.com/data/meteofrance_arome_france0025/static/meta.json",
}


def fetch_runs(raw_dir: Path) -> None:
    out = {}
    for k, url in RUN_META.items():
        try:
            j = requests.get(url, timeout=20).json()
            out[k] = {"init": j["last_run_initialisation_time"], "avail": j["last_run_availability_time"],
                      "every": j.get("update_interval_seconds", 21600)}
        except Exception as e:  # noqa: BLE001
            print(f"orario corsa {k}: {e}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "runs.json").write_text(json.dumps(out))


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads((root / "config" / "locations.json").read_text())
    fetch_runs(root / "data" / "raw")
    fetch_all(cfg, root / "data" / "raw")
    if not (root / "data" / "raw" / "global.json").exists():
        raise SystemExit("dati dei modelli non scaricati (limite Open-Meteo?): il sito resta quello di prima")
    print("ok")
