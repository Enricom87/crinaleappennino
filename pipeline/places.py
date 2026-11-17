"""Rifugi, strutture per dormire e noleggi sci vicino alle località, da OpenStreetMap
(© OpenStreetMap contributors, licenza ODbL). Si aggiorna al massimo una volta a settimana."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3.util.connection as _conn

_conn.HAS_IPV6 = False  # i runner GitHub a volte non hanno IPv6 verso Overpass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "places.json"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
BBOX = "43.98,10.15,44.45,11.00"
# query piccole e separate: i server pubblici rispondono molto meglio
FILTERS = ['["tourism"~"^(alpine_hut|wilderness_hut)$"]', '["tourism"="hotel"]',
           '["tourism"~"^(guest_house|hostel|chalet|apartment)$"]',
           '["shop"="ski"]', '["rental"~"ski"]', '["amenity"="ski_school"]']
Q = lambda f: f"[out:json][timeout:60];nwr{f}({BBOX});out center tags;"


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


def to_place(e: dict, f: str) -> dict | None:
    t = e.get("tags", {})
    k, name = kind(t), (t.get("name") or "").strip()
    lat = e.get("lat") or (e.get("center") or {}).get("lat")
    lon = e.get("lon") or (e.get("center") or {}).get("lon")
    if not k or not name or lat is None:
        return None
    web = t.get("website") or t.get("contact:website") or t.get("url") or ""
    if web and not web.startswith("http"):
        web = "https://" + web
    return {"id": f"{e['type'][0]}{e['id']}", "kind": k, "name": name, "lat": lat, "lon": lon, "q": f,
            "ele": t.get("ele", ""), "web": web, "phone": t.get("phone") or t.get("contact:phone") or "",
            "stars": t.get("stars", ""), "osm": f"https://www.openstreetmap.org/{e['type']}/{e['id']}"}


def main() -> None:
    """Ogni categoria si aggiorna per conto suo (una volta a settimana); se un server è occupato
    si tiene il dato precedente e si riprova al giro dopo."""
    try:
        old = json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        old = {"places": [], "ok": {}}
    ok, places = dict(old.get("ok") or {}), list(old.get("places") or [])
    now = datetime.now(timezone.utc)
    changed = False
    for f in FILTERS:
        last = ok.get(f)
        if last and (now - datetime.fromisoformat(last)).days < 7:
            continue
        for url in OVERPASS:
            try:
                r = requests.post(url, data={"data": Q(f)}, timeout=90, headers={"User-Agent": "crinaleappennino.it"})
                r.raise_for_status()
                new = [p for p in (to_place(e, f) for e in r.json()["elements"]) if p]
                places = [p for p in places if p.get("q") != f] + new
                ok[f] = now.isoformat()
                changed = True
                print(f"strutture: {f} → {len(new)}")
                break
            except Exception as ex:  # noqa: BLE001
                print(f"strutture: {url} {f} non disponibile ({str(ex)[:100]})")
                time.sleep(3)
        time.sleep(2)
    if changed:
        OUT.write_text(json.dumps({"fetched": now.isoformat(), "ok": ok, "places": places}, ensure_ascii=False, indent=0))
    print(f"strutture: {len(places)} in archivio, categorie aggiornate {len(ok)}/{len(FILTERS)}")


if __name__ == "__main__":
    main()
