"""Da quali corse dei modelli vengono i dati sul sito, e quando arriva il prossimo aggiornamento utile."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAW = Path(__file__).resolve().parent.parent / "data" / "raw" / "runs.json"
ROME = ZoneInfo("Europe/Rome")
BUILD_MIN = 50  # dal momento in cui l'uscita è disponibile al sito online: controllo ogni 10 min + aggiornamento


def view(now: datetime) -> dict | None:
    try:
        r = json.loads(RAW.read_text())
    except Exception:  # noqa: BLE001
        return None
    hh = lambda ts: datetime.fromtimestamp(ts, timezone.utc).astimezone(ROME).strftime("%H")  # noqa: E731
    out = {k: hh(v["init"]) for k, v in r.items()}
    # prossima uscita europea (corsa principale o scenari): stessa distanza tra partenza e uscita dell'ultima volta
    nxt = []
    for k in ("ecmwf", "ens"):
        v = r.get(k)
        if not v:
            continue
        lag = v["avail"] - v["init"]
        t = v["init"] + v["every"] + lag
        while t < now.timestamp():
            t += v["every"]
        nxt.append((t, k))
    if nxt:
        t, k = min(nxt)
        when = datetime.fromtimestamp(t, timezone.utc).astimezone(ROME) + timedelta(minutes=BUILD_MIN)
        out["next"] = when.strftime("%H:%M")
        out["next_what"] = k
    return out
