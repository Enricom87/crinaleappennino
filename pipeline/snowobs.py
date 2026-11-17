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


# Toscana: Centro Funzionale Regionale (CFR). Nivometri ("Livello [cm]") vicino alle località toscane.
CFR = "https://www.cfr.toscana.it"
CFR_SOURCE = {"name": "Centro Funzionale Regione Toscana", "license": "dati in tempo reale non validati", "url": CFR}
CFR_IDS = {"TOS02000351": "Boscolungo", "TOS02000221": "Casone di Profecchia", "TOS03000335": "Foce a Giovo"}


def cfr_stations(prev: dict) -> list[dict]:
    import re
    from datetime import timedelta, timezone as tz
    out = []
    ses = requests.Session()
    ses.headers.update({"User-Agent": "Mozilla/5.0 (compatible; crinaleappennino.it)",
                        "Referer": f"{CFR}/index.php?IDS=42&IDSS=1151", "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json, text/javascript, */*; q=0.01"})
    try:  # come il browser: prima la pagina (cookie di sessione), poi i dati
        ses.get(f"{CFR}/index.php", params={"IDS": "42", "IDSS": "1151"}, timeout=30)
    except Exception:  # noqa: BLE001
        pass
    for sid, name in CFR_IDS.items():
        try:
            rr = ses.get(f"{CFR}/monitoraggio/actions.php", params={"action": "station", "id": sid}, timeout=30)
            try:
                j = rr.json()
            except ValueError:
                print(f"neve misurata Toscana: risposta non JSON ({rr.status_code}): {rr.text[:160]!r}")
                continue
            nv = j.get("nivo")
            if not nv:
                continue
            # data in ora solare (UTC+1 fisso) → UTC
            t = datetime.strptime(nv["date"], "%d/%m/%Y %H:%M:%S").replace(tzinfo=tz(timedelta(hours=1)))
            t_iso = t.astimezone(tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            cm = max(0.0, float(nv["value"]))
            old = prev.get(name) or {}
            elev, lat, lon = old.get("elev"), old.get("lat"), old.get("lon")
            if not elev:
                info = ses.get(f"{CFR}/open_layers/ajax_stations.php", params={"id": sid, "types": "nivo"},
                                    timeout=30).json()["features"][0]
                desc = info.get("description", "")
                m = re.search(r"Quota staz\. slm \[m\]</b>\s*([\d.]+)", desc)
                elev, lat, lon = round(float(m.group(1))) if m else 0, float(info["lat"]), float(info["lon"])
            series = [x for x in (old.get("series") or []) if x[0] != t_iso][-30:] + [[t_iso, round(cm, 1)]]
            series.sort()
            first = series[0]
            hours = (t - datetime.fromisoformat(first[0].replace("Z", "+00:00"))).total_seconds() / 3600
            out.append({"name": name, "elev": elev, "lat": lat, "lon": lon, "cm": round(cm), "time": t_iso,
                        "delta": round(cm - first[1]) if hours >= 6 else 0, "delta_h": round(hours) if hours >= 6 else 0,
                        "series": series, "source": CFR_SOURCE})
        except Exception as ex:  # noqa: BLE001
            print(f"neve misurata Toscana: {name} non disponibile ({ex})")
    return out


def main() -> None:
    try:
        prev = {s["name"]: s for s in json.loads(OUT.read_text()).get("stations", [])}
    except Exception:  # noqa: BLE001
        prev = {}
    tos = cfr_stations(prev)
    try:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
    except Exception as ex:  # noqa: BLE001
        print(f"neve misurata: Arpae non disponibile ({ex})")
        r = None
    st: dict[str, dict] = {}
    for line in (r.text.splitlines() if r is not None else []):
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
    if r is None:  # Arpae giù: tengo le sue stazioni dell'ultimo giro
        stations = [s for s in prev.values() if (s.get("source") or SOURCE)["name"] == SOURCE["name"]]
    for s_ in stations:
        s_.setdefault("source", SOURCE)
    stations += tos
    OUT.write_text(json.dumps({"source": SOURCE, "stations": stations}, ensure_ascii=False, indent=1))
    print(f"neve misurata: {len(stations)} stazioni ({len(tos)} toscane)")


if __name__ == "__main__":
    main()
