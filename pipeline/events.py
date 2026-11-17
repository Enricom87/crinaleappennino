"""Eventi in Appennino dagli open data ufficiali di Emilia-Romagna Turismo (licenza CC BY 4.0,
riuso anche commerciale con citazione della fonte). Scarica tutti gli eventi attivi e tiene
quelli vicini alle nostre località. Se la fonte non risponde, resta l'ultimo file buono.

Nota: l'API è in migrazione verso visitemiliaromagna.it; gli URL sono in BASES, il primo che
risponde con JSON vince."""
from __future__ import annotations

import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "events.json"
BASES = ["https://emiliaromagnaturismo.it/opendata/v1", "https://stage.emiliaromagnaturismo.it/v1"]
SOURCE = {"name": "Emilia-Romagna Turismo", "url": "https://emiliaromagnaturismo.it/it/open-data",
          "license": "CC BY 4.0"}
BOX = (43.95, 44.50, 10.10, 11.15)  # lat min, lat max, lon min, lon max: l'Appennino che copriamo


def pull(base: str, lang: str) -> list[dict]:
    out, page = [], 1
    while page <= 20:
        r = requests.get(f"{base}/events", params={"lang": lang, "limit": 100, "page": page}, timeout=60)
        r.raise_for_status()
        j = r.json()
        out += j.get("data") or []
        if page >= (j.get("meta") or {}).get("last_page", 1):
            break
        page += 1
    return out


def slim(e: dict) -> dict | None:
    locs = [l for l in (e.get("locations") or []) if l.get("lat") and l.get("lng")]
    near = [l for l in locs if BOX[0] <= l["lat"] <= BOX[1] and BOX[2] <= l["lng"] <= BOX[3]]
    if not near or e.get("scaduto"):
        return None
    l, d = near[0], e.get("dates") or {}
    if not d.get("from"):
        return None
    return {"id": e["id"], "title": (e.get("title") or "").strip(), "sub": (e.get("subtitle") or "").strip(),
            "from": d["from"], "to": d.get("to") or d["from"], "city": l.get("city") or "",
            "place": l.get("title") or "", "lat": l["lat"], "lon": l["lng"], "url": e.get("permalink") or "",
            "cat": ", ".join(c.get("name", "") for c in (e.get("category") or [])[:2])}


COMMUNITY = "https://crinale-bot.enrico-marchionni.workers.dev/events.json"


def community() -> list[dict]:
    """Eventi segnalati dagli organizzatori e approvati a mano su Telegram."""
    try:
        r = requests.get(COMMUNITY, timeout=30)
        r.raise_for_status()
        out = []
        for e in r.json().get("events", []):
            out.append({"id": "c-" + e["id"], "title": e["title"], "sub": "", "from": e["from"], "to": e["to"],
                        "city": e.get("place") or "", "place": "", "loc": e["loc"], "url": e.get("url") or "",
                        "cat": "", "desc": e.get("desc") or "", "org": e.get("org") or "", "community": True})
        print(f"eventi segnalati: {len(out)}")
        return out
    except Exception as ex:  # noqa: BLE001
        print(f"eventi segnalati: non disponibili ({ex})")
        return []


def main() -> None:
    comm = community()
    for base in BASES:
        try:
            res = {}
            for lang in ("it", "en"):
                res[lang] = [x for x in map(slim, pull(base, lang)) if x] + comm
            OUT.parent.mkdir(parents=True, exist_ok=True)
            OUT.write_text(json.dumps({"source": SOURCE, "events": res}, ensure_ascii=False, indent=1))
            print(f"eventi: {len(res['it'])} in zona (da {base})")
            return
        except Exception as ex:  # noqa: BLE001 — la fonte esterna non deve mai rompere il sito
            print(f"eventi: {base} non disponibile ({ex})")
    if comm:  # la fonte regionale è giù ma le segnalazioni ci sono: aggiorno solo quelle
        try:
            old = json.loads(OUT.read_text())
        except Exception:  # noqa: BLE001
            old = {"source": SOURCE, "events": {"it": [], "en": []}}
        for lang in ("it", "en"):
            old["events"][lang] = [e for e in old["events"].get(lang, []) if not e.get("community")] + comm
        OUT.write_text(json.dumps(old, ensure_ascii=False, indent=1))
    print("eventi: tengo l'ultimo file per la fonte regionale")


if __name__ == "__main__":
    main()
