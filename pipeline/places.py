"""Rifugi, strutture per dormire e noleggi sci vicino alle località, da OpenStreetMap
(© OpenStreetMap contributors, licenza ODbL). Si aggiorna al massimo una volta a settimana."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "places.json"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
BBOX = "43.98,10.15,44.45,11.00"
Q = f"""[out:json][timeout:120];
(
  nwr["tourism"~"^(alpine_hut|wilderness_hut|hotel|guest_house|hostel|chalet|apartment)$"]({BBOX});
  nwr["shop"="ski"]({BBOX});
  nwr["rental"~"ski"]({BBOX});
  nwr["amenity"="ski_school"]({BBOX});
  nwr["sport"="skiing"]["amenity"="school"]({BBOX});
);
out center tags;"""


def kind(t: dict) -> str | None:
    tour = t.get("tourism")
    if tour == "alpine_hut":
        return "rifugio"
    if tour == "wilderness_hut":
        return "bivacco"
    if tour in ("hotel", "guest_house", "hostel", "chalet", "apartment"):
        return "dormire"
    if t.get("shop") == "ski" or "ski" in (t.get("rental") or ""):
        return "noleggio"
    if t.get("amenity") in ("ski_school", "school"):
        return "scuola"
    return None


def main() -> None:
    try:
        old = json.loads(OUT.read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(old["fetched"])).days
        if age < 7:
            print(f"strutture: dati di {age} giorni fa, li tengo")
            return
    except Exception:  # noqa: BLE001
        pass
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": Q}, timeout=180, headers={"User-Agent": "crinaleappennino.it"})
            r.raise_for_status()
            els = r.json()["elements"]
            break
        except Exception as ex:  # noqa: BLE001
            print(f"strutture: {url} non disponibile ({ex})")
            time.sleep(5)
    else:
        print("strutture: tengo l'ultimo file")
        return
    out = []
    for e in els:
        t = e.get("tags", {})
        k, name = kind(t), (t.get("name") or "").strip()
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if not k or not name or lat is None:
            continue
        web = t.get("website") or t.get("contact:website") or t.get("url") or ""
        if web and not web.startswith("http"):
            web = "https://" + web
        out.append({"id": f"{e['type'][0]}{e['id']}", "kind": k, "name": name, "lat": lat, "lon": lon,
                    "ele": t.get("ele", ""), "web": web, "phone": t.get("phone") or t.get("contact:phone") or "",
                    "stars": t.get("stars", ""), "osm": f"https://www.openstreetmap.org/{e['type']}/{e['id']}"})
    OUT.write_text(json.dumps({"fetched": datetime.now(timezone.utc).isoformat(), "places": out},
                              ensure_ascii=False, indent=0))
    print(f"strutture: {len(out)} da OpenStreetMap")


if __name__ == "__main__":
    main()
