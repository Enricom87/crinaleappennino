"""Tracciati dei percorsi: geometria (OpenStreetMap o file), quote, statistiche.

Scarica solo le geometrie che mancano in data/routes/ e le salva, così i percorsi
non vengono riscaricati a ogni aggiornamento. Dati OSM © OpenStreetMap contributors (ODbL).
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "routes"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
ELEV_URL = "https://api.open-meteo.com/v1/elevation"
UA = {"User-Agent": "crinaleappennino.it (previsioni neve e percorsi)"}


def haversine(a, b) -> float:
    (lo1, la1), (lo2, la2) = a[:2], b[:2]
    r = 6371000
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def fetch_osm_api(rel_id: int) -> list[list[list[float]]]:
    """Geometria di una relazione dall'API principale di OpenStreetMap (relation/full)."""
    r = requests.get(f"https://api.openstreetmap.org/api/0.6/relation/{rel_id}/full.json", headers=UA, timeout=60)
    r.raise_for_status()
    els = r.json()["elements"]
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in els if e["type"] == "node"}
    ways = {e["id"]: e["nodes"] for e in els if e["type"] == "way"}
    rel = next(e for e in els if e["type"] == "relation" and e["id"] == rel_id)
    lines = []
    for m in rel.get("members", []):
        if m["type"] == "way" and m["ref"] in ways:
            ln = [list(nodes[n]) for n in ways[m["ref"]] if n in nodes]
            if len(ln) > 1:
                lines.append(ln)
    return lines


def fetch_osm_many(rel_ids: list[int]) -> dict[int, list[list[list[float]]]]:
    out = {}
    for rid in rel_ids:  # API principale: poche richieste, una alla volta
        try:
            out[rid] = fetch_osm_api(rid)
            print(f"osm api {rid}: {len(out[rid])} tratti", flush=True)
        except Exception as e:
            print(f"osm api {rid}: {e}", flush=True)
        time.sleep(2)
    missing = [r for r in rel_ids if not out.get(r)]
    if missing:
        try:
            out.update(fetch_overpass(missing))
        except Exception as e:
            print(f"overpass: {e}", flush=True)
    return out


def fetch_overpass(rel_ids: list[int]) -> dict[int, list[list[list[float]]]]:
    """Una sola richiesta Overpass per tutte le relazioni mancanti."""
    q = f"[out:json][timeout:180];relation(id:{','.join(map(str, rel_ids))});out geom;"
    last = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": q}, headers=UA, timeout=240)
            print(f"overpass {url}: {r.status_code}", flush=True)
            if r.ok:
                out = {}
                for el in r.json().get("elements", []):
                    out[el["id"]] = [[[g["lon"], g["lat"]] for g in m["geometry"]]
                                     for m in el.get("members", []) if m.get("type") == "way" and m.get("geometry")]
                return out
            last = r.status_code
        except requests.RequestException as e:
            last = e
            print(f"overpass {url}: {e}", flush=True)
        time.sleep(20)
    raise RuntimeError(f"Overpass non raggiungibile: {last}")


def add_elevation(lines: list[list[list[float]]]) -> None:
    """Quote dal modello del terreno (Copernicus DEM via Open-Meteo), a gruppi di 100 punti."""
    pts = [p for ln in lines for p in ln if len(p) < 3]
    for i in range(0, len(pts), 100):
        grp = pts[i:i + 100]
        params = {"latitude": ",".join(f"{p[1]:.5f}" for p in grp),
                  "longitude": ",".join(f"{p[0]:.5f}" for p in grp)}
        for attempt in range(3):
            r = requests.get(ELEV_URL, params=params, timeout=30)
            if r.status_code != 429:
                break
            time.sleep(65)  # limite al minuto dell'API gratuita
        r.raise_for_status()
        for p, z in zip(grp, r.json()["elevation"]):
            p.append(round(z))
        time.sleep(3)


def thin(line: list[list[float]], step: float = 60.0) -> list[list[float]]:
    out, acc = [line[0]], 0.0
    for a, b in zip(line, line[1:]):
        acc += haversine(a, b)
        if acc >= step:
            out.append(b)
            acc = 0.0
    if out[-1] is not line[-1]:
        out.append(line[-1])
    return out


def stats(lines: list[list[list[float]]]) -> dict:
    length = sum(haversine(a, b) for ln in lines for a, b in zip(ln, ln[1:]))
    zs = [p[2] for ln in lines for p in ln if len(p) > 2]
    gain = 0.0
    for ln in lines:  # dislivello positivo con soglia di 5 m per filtrare il rumore del modello del terreno
        ref = None
        for p in ln:
            if len(p) < 3:
                continue
            if ref is None:
                ref = p[2]
            elif p[2] - ref >= 5:
                gain += p[2] - ref
                ref = p[2]
            elif ref - p[2] >= 5:
                ref = p[2]
    allp = [p for ln in lines for p in ln]
    longest = max(lines, key=len)
    return {"km": round(length / 1000, 1), "z_min": min(zs) if zs else None, "z_max": max(zs) if zs else None,
            "gain": round(gain / 10) * 10, "start": longest[0][:2],
            "bbox": [min(p[0] for p in allp), min(p[1] for p in allp), max(p[0] for p in allp), max(p[1] for p in allp)]}


def ensure_geometries(cfg: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    todo = [r for r in cfg["routes"] if not (DIR / f"{r['slug']}.geojson").exists() and "osm" in r["source"]]
    if not todo:
        print("nessun tracciato nuovo")
        return
    geoms = fetch_osm_many([r["source"]["osm"] for r in todo])
    for r in todo:
        lines = [thin(ln) for ln in geoms.get(r["source"]["osm"], []) if len(ln) > 1]
        if not lines:
            print(f"saltato {r['slug']}: nessuna geometria", flush=True)
            continue
        try:
            add_elevation(lines)
        except Exception as e:  # senza quote il percorso resta da scaricare al giro dopo
            print(f"saltato {r['slug']}: quote non disponibili ({e})", flush=True)
            continue
        gj = {"type": "Feature", "properties": {"source": "osm", "osm_relation": r["source"]["osm"],
                                                "credit": "© OpenStreetMap contributors (ODbL)"},
              "geometry": {"type": "MultiLineString", "coordinates": lines}}
        (DIR / f"{r['slug']}.geojson").write_text(json.dumps(gj))
        print(f"scaricato {r['slug']}: {sum(len(x) for x in lines)} punti", flush=True)


def load_routes(cfg: dict) -> list[dict]:
    out = []
    for r in cfg["routes"]:
        path = DIR / f"{r['slug']}.geojson"
        if not path.exists():
            continue
        gj = json.loads(path.read_text())
        lines = gj["geometry"]["coordinates"]
        out.append({**r, "geojson": gj, "stats": stats(lines), "credit": gj["properties"].get("credit", "")})
    return out


def to_gpx(route: dict) -> str:
    segs = []
    for ln in route["geojson"]["geometry"]["coordinates"]:
        pts = "".join(f'<trkpt lat="{p[1]}" lon="{p[0]}">' + (f"<ele>{p[2]}</ele>" if len(p) > 2 else "") + "</trkpt>"
                      for p in ln)
        segs.append(f"<trkseg>{pts}</trkseg>")
    name = route["name"].replace("&", "e").replace("<", "").replace(">", "")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="crinaleappennino.it" '
            'xmlns="http://www.topografix.com/GPX/1/1">'
            f"<metadata><name>{name}</name><desc>{route['credit']}</desc></metadata>"
            f"<trk><name>{name}</name>{''.join(segs)}</trk></gpx>")


if __name__ == "__main__":
    ensure_geometries(json.loads((ROOT / "config" / "routes.json").read_text()))
