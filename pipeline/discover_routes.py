"""Elenca i percorsi OpenStreetMap della zona (escursionismo CAI, MTB, bici, scialpinismo, ciaspole).

Gira su GitHub Actions (serve Internet) e salva data/osm_index.json: un indice leggero
con id, nome, tipo, numero CAI e quote, da cui scegliere i percorsi da pubblicare.
Dati © OpenStreetMap contributors, licenza ODbL.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests

BBOX = "44.05,10.15,44.36,10.96"  # sud, ovest, nord, est: dal Cerreto al Corno alle Scale
ENDPOINTS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
QUERIES = {
    "escursionismo": f'relation["route"="hiking"]({BBOX});',
    "mtb": f'relation["route"="mtb"]({BBOX});',
    "bici": f'relation["route"="bicycle"]({BBOX});',
    "scialpinismo": f'relation["piste:type"="skitour"]({BBOX});way["piste:type"="skitour"]({BBOX});',
    "ciaspole": f'relation["piste:type"="hike"]({BBOX});way["piste:type"="hike"]({BBOX});',
    "running": f'relation["route"="running"]({BBOX});',
}


def overpass(q: str) -> dict:
    body = f"[out:json][timeout:120];({q});out tags center;"
    for url in ENDPOINTS * 2:
        try:
            r = requests.post(url, data={"data": body}, timeout=180,
                              headers={"User-Agent": "crinaleappennino.it (previsioni neve e percorsi)"})
            if r.ok:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(15)
    raise RuntimeError("Overpass non raggiungibile")


def main() -> None:
    out = []
    for kind, q in QUERIES.items():
        for e in overpass(q).get("elements", []):
            t = e.get("tags", {})
            c = e.get("center", {})
            out.append({"kind": kind, "type": e["type"], "id": e["id"], "name": t.get("name", ""),
                        "ref": t.get("ref", ""), "operator": t.get("operator", ""), "network": t.get("network", ""),
                        "from": t.get("from", ""), "to": t.get("to", ""), "difficulty": t.get("cai_scale") or
                        t.get("mtb:scale") or t.get("piste:difficulty", ""), "lat": c.get("lat"), "lon": c.get("lon")})
        print(kind, sum(1 for x in out if x["kind"] == kind))
        time.sleep(5)
    p = Path(__file__).resolve().parents[1] / "data" / "osm_index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main()
