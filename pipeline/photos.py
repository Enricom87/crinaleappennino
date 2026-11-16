"""Scarica (una volta sola) le foto delle località da Wikimedia Commons e ne salva i crediti.

Le foto finiscono in data/photos/<chiave>.jpg (larghe 1600 px) e i crediti in data/photos/credits.json.
Licenze libere (CC BY, CC BY-SA, CC0, pubblico dominio): il sito mostra sempre autore e licenza.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "photos"
API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "crinaleappennino.it/1.0 (info@crinaleappennino.it)"}


def clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()[:80]


def main() -> None:
    cfg = json.loads((ROOT / "config" / "photos.json").read_text())
    DIR.mkdir(parents=True, exist_ok=True)
    credits_path = DIR / "credits.json"
    credits = json.loads(credits_path.read_text()) if credits_path.exists() else {}
    for key, title in cfg["files"].items():
        dst = DIR / f"{key}.jpg"
        if dst.exists() and key in credits and credits[key].get("file") == title:
            continue
        try:
            r = requests.get(API, params={"action": "query", "format": "json", "titles": "File:" + title,
                                          "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": 1600},
                             headers=UA, timeout=30)
            r.raise_for_status()
            page = next(iter(r.json()["query"]["pages"].values()))
            info = page["imageinfo"][0]
            meta = info.get("extmetadata", {})
            img = requests.get(info["thumburl"], headers=UA, timeout=60)
            img.raise_for_status()
            dst.write_bytes(img.content)
            credits[key] = {"file": title, "page": info["descriptionurl"],
                            "artist": clean(meta.get("Artist", {}).get("value", "")) or "autore su Wikimedia Commons",
                            "license": clean(meta.get("LicenseShortName", {}).get("value", "")),
                            "license_url": meta.get("LicenseUrl", {}).get("value", "")}
            print(f"foto {key}: {title} ({credits[key]['license']})")
            time.sleep(1)
        except Exception as e:  # una foto mancante non deve fermare il sito
            print(f"foto {key} saltata: {e}")
    credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
