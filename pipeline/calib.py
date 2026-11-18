"""Taratura automatica per località, imparata dagli errori passati.

1. Quantità di neve: per ogni giorno con neve prevista o misurata confrontiamo la previsione del mattino
   precedente con la neve fresca misurata dalla stazione di riferimento (data/history.json). Gli episodi
   restano in archivio (data/calib.json) anche dopo i 30 giorni dello storico. Con almeno 4 episodi il
   rapporto misurato/previsto diventa un fattore di correzione, prudente: si avvicina al valore pieno solo
   con molti episodi ed è limitato tra 0,6 e 1,4.
2. Quota neve: le segnalazioni dal territorio («nevica» o «piove» a una certa quota) dicono se la nostra
   quota neve di quel giorno era troppo alta o troppo bassa. Con almeno 4 segnalazioni utili ne ricaviamo
   uno spostamento medio, limitato a ±300 m."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "calib.json"
MIN_EV, SHRINK = 4, 6


def _j(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return default


def update(today: str) -> dict:
    from history import measured_new_snow
    h = _j(ROOT / "data" / "history.json", {"forecast": {}, "obs": {}})
    reports = _j(ROOT / "data" / "reports.json", [])
    c = _j(FILE, {"snow": {}, "level": {}})
    t0 = date.fromisoformat(today)
    for slug, fc in h.get("forecast", {}).items():
        ev = c["snow"].setdefault(slug, {})
        for i in range(1, 8):
            d = (t0 - timedelta(days=i)).isoformat()
            made = (t0 - timedelta(days=i + 1)).isoformat()
            f = (fc.get(made) or {}).get("days", {}).get(d)
            if f is None or d in ev:
                continue
            m = measured_new_snow(h["obs"].get(fc[made]["station"], {}), d)
            if m is None or (f < 2 and m < 2):
                continue
            ev[d] = {"fc": round(f, 1), "obs": m}
        # snow-level check from reports
        lv_ev = c["level"].setdefault(slug, {})
        for r in reports:
            if r.get("loc") != slug or r.get("kind") not in ("nevica", "pioggia") or r["id"] in lv_ev:
                continue
            d = r["ts"][:10]
            made = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
            lv = ((fc.get(made) or fc.get(d) or {}).get("snowline") or {}).get(d)
            if lv is None:
                continue
            e = r["elev"]
            if r["kind"] == "nevica" and lv > e + 100:
                lv_ev[r["id"]] = {"date": d, "err": e - lv}         # nevicava sotto la nostra quota
            elif r["kind"] == "pioggia" and lv < e - 100:
                lv_ev[r["id"]] = {"date": d, "err": e + 100 - lv}   # pioveva sopra la nostra quota
            else:
                lv_ev[r["id"]] = {"date": d, "err": 0}
    FILE.write_text(json.dumps(c, separators=(",", ":")))
    return c


def factors(c: dict | None = None) -> dict:
    c = c if c is not None else _j(FILE, {"snow": {}, "level": {}})
    out = {}
    for slug in set(c.get("snow", {})) | set(c.get("level", {})):
        ev = sorted(c.get("snow", {}).get(slug, {}).items())[-20:]
        f = 1.0
        if len(ev) >= MIN_EV and sum(v["fc"] for _, v in ev) >= 10:
            raw = sum(v["obs"] for _, v in ev) / sum(v["fc"] for _, v in ev)
            f = 1 + (raw - 1) * len(ev) / (len(ev) + SHRINK)
            f = round(min(1.4, max(0.6, f)), 2)
        lv = sorted(c.get("level", {}).get(slug, {}).values(), key=lambda v: v["date"])[-20:]
        off = 0
        if len(lv) >= MIN_EV:
            off = sum(v["err"] for v in lv) / len(lv) * len(lv) / (len(lv) + SHRINK)
            off = int(round(min(300, max(-300, off)) / 50) * 50)
        out[slug] = {"snow": f, "n_snow": len(ev), "level": off, "n_level": len(lv)}
    return out


def apply(base_locs: list[dict], pts: dict, fac: dict) -> None:
    """Scala la neve prevista nei punti della località (ogni punto una volta sola)."""
    done = set()
    for loc in base_locs:
        f = (fac.get(loc["slug"]) or {}).get("snow", 1.0)
        for pid in loc["points"]:
            if pid in done or pid not in pts:
                continue
            done.add(pid)
            if f == 1.0:
                continue
            for d in pts[pid]["days"]:
                for k in ("snow", "snow_min", "snow_max"):
                    if d.get(k):
                        d[k] = round(d[k] * f, 1)
            for hr in pts[pid].get("hours", []):
                if hr.get("snow"):
                    hr["snow"] = round(hr["snow"] * f, 1)
