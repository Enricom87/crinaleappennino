"""Pericolo valanghe dal bollettino ufficiale Meteomont (Arma dei Carabinieri), scala europea EAWS 1-5,
per i due sottosettori che coprono le nostre località. Oggi e i 2 giorni successivi."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "avalanche.json"
API = "https://servizimeteomont.csifa.carabinieri.it/api/meteomontweb/previsioni/getprevisionivalangheCL/data"
WANT = {("08", "2"), ("09", "1")}


def grade(x: dict) -> int | None:
    g = [int(c) for c in (x.get("colorePericolo1"), x.get("colorePericolo2")) if c and c.strip().isdigit()]
    return max(g) if g else None


def main() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    try:
        r = requests.get(API, params={"data": now}, timeout=60, headers={"User-Agent": "crinaleappennino.it"})
        r.raise_for_status()
        v = r.json()
    except Exception as ex:  # noqa: BLE001
        print(f"valanghe: Meteomont non disponibile ({ex}), tengo l'ultimo file")
        return
    out = {}
    for i in range(4):
        for x in (v.get(f"giorno{i}") or {}).get("previsioneValanga") or []:
            key = (x.get("codSett"), x.get("codSottoSett"))
            if key not in WANT:
                continue
            s = out.setdefault(f"{key[0]}/{key[1]}", {"name": x.get("descSottoSett"), "days": []})
            s["days"].append({"offset": i, "ref": x.get("dataRif"), "grade": grade(x), "hs": x.get("hNeve"),
                              "hn": x.get("hNeveFresca")})
    OUT.write_text(json.dumps({"fetched": now + "Z", "sectors": out}, ensure_ascii=False, indent=1))
    print(f"valanghe: {len(out)} sottosettori")


if __name__ == "__main__":
    main()
