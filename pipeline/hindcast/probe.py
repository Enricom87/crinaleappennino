"""Fattibilità dello storico: per i punti di Crinale, da quando esistono le previsioni archiviate dei modelli
(Open-Meteo Historical Forecast API) e quali stazioni Arpae con l'altezza della neve sono vicine.
Gira su GitHub Actions (da lì Open-Meteo e Arpae sono raggiungibili). Scrive data/hindcast/probe.json."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "hindcast"
HF = "https://historical-forecast-api.open-meteo.com/v1/forecast"
MODELS = ["ecmwf_ifs025", "icon_global", "icon_eu", "gfs025", "italia_meteo_arpae_icon_2i",
          "meteofrance_arome_france", "meteoswiss_icon_ch2", "icon_d2", "ukmo_global_deterministic_10km"]
WINTERS = [("2022-11-01", "2023-04-15"), ("2023-11-01", "2024-04-15"),
           ("2024-11-01", "2025-04-15"), ("2025-11-01", "2026-04-15")]
CKAN = "https://dati.arpae.it/api/3/action"


def get(url, **params):
    for t in range(4):
        try:
            r = requests.get(url, params=params, timeout=90)
            if r.status_code == 429:
                time.sleep(60)
                continue
            return r.json()
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5)
    return {"error": str(err)}


def models_probe(points: dict) -> dict:
    # tre punti rappresentativi: Passo dell'Abetone, Lago della Ninfa, Monte Cimone
    sample = {k: points[k] for k in ("abetone-passo", "lago-ninfa", "monte-cimone") if k in points}
    out = {}
    for pid, p in sample.items():
        for m in MODELS:
            per_w = []
            for a, b in WINTERS:
                j = get(HF, latitude=p["lat"], longitude=p["lon"], elevation=p.get("elev"), models=m,
                        daily="precipitation_sum,snowfall_sum", start_date=a, end_date=b, timezone="Europe/Rome")
                d = j.get("daily") or {}
                pr = d.get("precipitation_sum") or []
                ok = [x for x in pr if x is not None]
                first = next((t for t, x in zip(d.get("time", []), pr) if x is not None), None)
                per_w.append({"winter": a[:4], "days": len(pr), "with_data": len(ok), "first": first,
                              "precip_mm": round(sum(ok), 1), "snowfall_cm": round(sum(x for x in (d.get("snowfall_sum") or []) if x), 1),
                              "error": j.get("reason") or j.get("error")})
                time.sleep(1.5)
            out.setdefault(pid, {})[m] = per_w
            print(pid, m, [(w["winter"], w["with_data"], w["first"]) for w in per_w], flush=True)
    return out


def arpae_probe() -> dict:
    res = {"search": [], "packages": {}}
    for q in ("neve", "altezza neve", "stazioni meteo", "nivometri"):
        j = get(f"{CKAN}/package_search", q=q, rows=20)
        for p in (j.get("result") or {}).get("results", []):
            res["search"].append({"q": q, "name": p.get("name"), "title": p.get("title"),
                                  "resources": [(r.get("name"), r.get("format"), r.get("url")) for r in p.get("resources", [])][:15]})
    return res


def main() -> None:
    cfg = json.loads((ROOT / "config" / "locations.json").read_text())
    points = cfg["points"] if isinstance(cfg["points"], dict) else {p["id"]: p for p in cfg["points"]}
    OUT.mkdir(parents=True, exist_ok=True)
    out = {"models": models_probe(points), "arpae": arpae_probe()}
    (OUT / "probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("ok")


if __name__ == "__main__":
    main()
