"""Neve al suolo MISURATA dalle stazioni nivometriche ufficiali di Arpae Emilia-Romagna
(open data, licenza CC BY). Il file realtime contiene le ultime ore di tutte le stazioni:
teniamo quelle di montagna che misurano l'altezza della neve (variabile B13013, in metri)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "snowobs.json"
URL = "https://dati-simc.arpae.it/opendata/osservati/meteo/realtime/realtime.jsonl"
SOURCE = {"name": "Arpae Emilia-Romagna", "license": "CC BY 4.0",
          "url": "https://dati.arpae.it/dataset/dati-dalle-stazioni-meteo-locali-della-rete-idrometeorologica-regionale"}
BOX = (44.0, 44.5, 10.0, 11.2)


def main() -> None:
    try:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
    except Exception as ex:  # noqa: BLE001
        print(f"neve misurata: fonte non disponibile ({ex}), tengo l'ultimo file")
        return
    st: dict[str, dict] = {}
    for line in r.text.splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        lat, lon = o["lat"] / 1e5, o["lon"] / 1e5
        if not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]):
            continue
        k = o.get("ident") or f"{lat:.4f},{lon:.4f}"
        s = st.setdefault(k, {"lat": lat, "lon": lon, "name": "", "elev": None, "obs": []})
        for d in o.get("data", []):
            v = d.get("vars", {})
            if "timerange" not in d:
                s["name"] = (v.get("B01019") or {}).get("v") or s["name"]
                s["elev"] = (v.get("B07030") or {}).get("v") or s["elev"]
            snow = (v.get("B13013") or {}).get("v")
            if snow is not None:
                s["obs"].append((o["date"], max(0.0, snow) * 100))
    stations = []
    for s in st.values():
        if not s["obs"]:
            continue
        s["obs"].sort()
        t_last, cm = s["obs"][-1]
        t0, cm0 = s["obs"][0]
        hours = (datetime.fromisoformat(t_last.replace("Z", "+00:00"))
                 - datetime.fromisoformat(t0.replace("Z", "+00:00"))).total_seconds() / 3600
        stations.append({"name": s["name"], "elev": round(s["elev"] or 0), "lat": s["lat"], "lon": s["lon"],
                         "cm": round(cm), "time": t_last, "delta": round(cm - cm0), "delta_h": round(hours),
                         "series": [[t, round(c, 1)] for t, c in s["obs"]]})
    OUT.write_text(json.dumps({"source": SOURCE, "stations": stations}, ensure_ascii=False, indent=1))
    print(f"neve misurata: {len(stations)} stazioni")


if __name__ == "__main__":
    main()
