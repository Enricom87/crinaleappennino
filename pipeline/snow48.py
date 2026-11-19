"""Esce con 0 se nelle prossime 48 ore è prevista neve (almeno 1 cm su un punto): serve all'aggiornamento
leggero ogni 3 ore, che altrimenti non parte per non consumare richieste."""
import json
import sys
from pathlib import Path

try:
    s = json.loads((Path(__file__).resolve().parent.parent / "data" / "latest.json").read_text())
except Exception:  # noqa: BLE001
    sys.exit(1)
v = s.get("snow48") or 0
print(f"neve nelle prossime 48 ore: {v} cm")
sys.exit(0 if v >= 1 else 1)
