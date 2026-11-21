"""Controlli di coerenza sul sito appena generato: stampa gli avvisi nel log e li salva in api/v1/checks.json.
Non blocca la pubblicazione: serve a vedere subito numeri che si contraddicono."""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "site"


def run(out: Path = OUT) -> list[str]:
    api = json.loads((out / "api" / "v1" / "forecast.json").read_text())
    locs = api.get("locations") or api.get("locs") or api
    locs = locs if isinstance(locs, list) else list(locs.values())
    warn: list[str] = []
    for L in locs:
        pts = sorted(L.get("points", []), key=lambda p: p.get("elev", 0))
        dates = sorted({d["date"] for p in pts for d in p.get("days", []) if d.get("idx", 99) < 5})
        for date in dates:
            row = [(p["name"], p["elev"], next((d for d in p["days"] if d["date"] == date), None)) for p in pts]
            row = [(n, z, d) for n, z, d in row if d]
            for (n1, z1, d1), (n2, z2, d2) in zip(row, row[1:]):  # più in alto, mai molta meno neve
                if (d1.get("snow") or 0) - (d2.get("snow") or 0) > max(2.0, 0.25 * (d1.get("snow") or 0)):
                    warn.append(f"{L['slug']} {date}: {n2} ({z2} m) {d2.get('snow')} cm < {n1} ({z1} m) {d1.get('snow')} cm")
            for n, z, d in row:  # neve vera ben sotto la quota neve mostrata
                lv = d.get("lv")
                if lv and (d.get("snow") or 0) >= 2 and z < lv - 250:
                    warn.append(f"{L['slug']} {date}: {n} ({z} m) {d['snow']} cm ma quota neve {lv} m")
    (out / "api" / "v1" / "checks.json").write_text(json.dumps(warn, ensure_ascii=False, indent=1))
    for w in warn:
        print("⚠️ coerenza:", w)
    print(f"controlli di coerenza: {len(warn)} avvisi")
    return warn


if __name__ == "__main__":
    run(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
