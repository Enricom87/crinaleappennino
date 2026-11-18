"""Archivia le segnalazioni dal territorio (neve vista da chi è in montagna): restano online 3 giorni,
ma qui le teniamo per tarare i modelli (quota neve reale, centimetri reali)."""
from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reports.json"
URL = "https://crinale-bot.enrico-marchionni.workers.dev/reports.json"


def main() -> None:
    try:
        new = requests.get(URL, timeout=30).json().get("reports", [])
    except Exception as ex:  # noqa: BLE001
        print(f"segnalazioni: non disponibili ({ex})")
        return
    try:
        old = json.loads(OUT.read_text())
    except Exception:  # noqa: BLE001
        old = []
    seen = {r["id"] for r in old}
    old += [r for r in new if r["id"] not in seen]
    old = sorted(old, key=lambda r: r["ts"])[-5000:]
    OUT.write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")))
    print(f"segnalazioni: {len(new)} recenti, {len(old)} in archivio")


if __name__ == "__main__":
    main()
