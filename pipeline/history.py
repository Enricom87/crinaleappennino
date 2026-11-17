"""«Avevamo detto / È andata così»: ogni giorno salviamo quanta neve prevedevamo per i giorni
seguenti alla quota della stazione di riferimento, e la confrontiamo con l'aumento dell'altezza
della neve misurato dalla stazione ufficiale. Il file data/history.json cresce nel tempo (30 giorni)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from extras import STATION_FOR
from i18n import T, cap, day_name

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "history.json"
OBS = ROOT / "data" / "snowobs.json"
KEEP = 30
ROME = ZoneInfo("Europe/Rome")


def _load() -> dict:
    try:
        return json.loads(FILE.read_text())
    except Exception:  # noqa: BLE001
        return {"forecast": {}, "obs": {}}


def record(locs: list[dict], today: str) -> None:
    """Salva la previsione di oggi (una volta al giorno: la prima utile) e le misure delle stazioni."""
    h = _load()
    try:
        stations = {s["name"]: s for s in json.loads(OBS.read_text()).get("stations", [])}
    except Exception:  # noqa: BLE001
        stations = {}
    for L in locs:
        st = stations.get(STATION_FOR.get(L["slug"], ""))
        if not st:
            continue
        ref = min(L["pts"], key=lambda p: abs(p["elev"] - st["elev"]))
        fc = h["forecast"].setdefault(L["slug"], {})
        if today not in fc:  # la previsione «del mattino» non si riscrive nel corso della giornata
            fc[today] = {"elev": ref["elev"], "station": st["name"],
                         "days": {d["date"]: round(d.get("snow", 0) or 0, 1) for d in ref["days"][:4]}}
    for name, st in stations.items():
        ob = h["obs"].setdefault(name, {})
        for t, cm in st.get("series", []):
            ob[t] = cm
    cut = (date.fromisoformat(today) - timedelta(days=KEEP)).isoformat()
    for fc in h["forecast"].values():
        for k in [k for k in fc if k < cut]:
            del fc[k]
    for ob in h["obs"].values():
        for k in [k for k in ob if k[:10] < cut]:
            del ob[k]
    FILE.write_text(json.dumps(h, ensure_ascii=False, separators=(",", ":")))


def measured_new_snow(obs: dict, day: str) -> float | None:
    """Neve caduta nel giorno (ora locale) ≈ aumento massimo dell'altezza rispetto al minimo
    registrato prima, nello stesso giorno o nelle ultime ore del precedente. None se mancano dati."""
    pts = []
    for t, cm in obs.items():
        lt = datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(ROME)
        pts.append((lt, cm))
    pts.sort()
    d0 = datetime.fromisoformat(day).replace(tzinfo=ROME)
    win = [(t, c) for t, c in pts if d0 - timedelta(hours=6) <= t < d0 + timedelta(days=1)]
    if len([1 for t, _ in win if t >= d0]) < 4:
        return None
    best, low = 0.0, win[0][1]
    for _, c in win:
        low = min(low, c)
        best = max(best, c - low)
    return round(best)


def view(L: dict, today: str, n: int = 7) -> dict | None:
    h = _load()
    fc = h["forecast"].get(L["slug"], {})
    if not fc:
        return None
    rows, hits, judged = [], 0, 0
    t0 = date.fromisoformat(today)
    for i in range(n, 0, -1):
        d = (t0 - timedelta(days=i)).isoformat()
        made = (t0 - timedelta(days=i + 1)).isoformat()
        f = (fc.get(made) or {}).get("days", {}).get(d)
        if f is None:
            continue
        st = fc[made]["station"]
        m = measured_new_snow(h["obs"].get(st, {}), d)
        if m is None:
            continue
        ok = (f < 2 and m < 2) or abs(f - m) <= max(3, 0.4 * max(f, m))
        judged += 1
        hits += ok
        rows.append({"date": d, "name": cap(day_name(d)), "fc": round(f), "obs": m, "ok": ok,
                     "snowy": f >= 2 or m >= 2})
    if not rows:
        return None
    station = list(fc.values())[-1]["station"].replace(" Nivo", "")
    snowy = [r for r in rows if r["snowy"]]
    if snowy:  # i giorni asciutti sono facili da indovinare: contano quelli con neve
        head = T("Nei giorni con neve prevista o caduta ci abbiamo preso in {h} casi su {n}.",
                 n=len(snowy), h=sum(r["ok"] for r in snowy))
    else:
        head = T("Niente neve negli ultimi giorni: previsto e misurato concordano.")
    return {"rows": rows, "hits": hits, "judged": judged, "station": station, "head": head}
