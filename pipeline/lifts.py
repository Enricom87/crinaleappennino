"""Stato di impianti e piste dai siti ufficiali dei comprensori (Multipass Abetone, Consorzio Cimone).

Legge le pagine pubbliche una volta per aggiornamento del sito e salva data/lifts.json. Se una pagina non
risponde o cambia forma, tiene i dati precedenti con la loro data: il sito mostrerà da quando sono fermi.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "lifts.json"
UA = {"User-Agent": "crinaleappennino.it (previsioni neve; info@crinaleappennino.it)"}


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def get(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def multipass(url: str) -> list[dict]:
    """Pagina con un blocco div.aperto e uno div.chiuso; ogni impianto è un <p><strong>Nome</strong> …"""
    soup = get(url)
    out = []
    for status in ("aperto", "chiuso"):
        for box in soup.select(f"div.{status}"):
            for p in box.find_all("p"):
                st = p.find("strong")
                name = clean(st.get_text()) if st else ""
                if name:
                    out.append({"name": re.sub(r"^\d+\.\s*", "", name), "open": status == "aperto", "area": ""})
    return out


def cimone_pane(soup: BeautifulSoup, pane: str) -> list[dict]:
    """Tabella dentro #impianti_risalita o #piste: righe tr.table-title (zona) e tr.standard-row (voce)."""
    box = soup.select_one(f"#{pane}")
    if not box:
        return []
    out, area = [], ""
    for tr in box.select("tr"):
        cls = tr.get("class") or []
        if "table-title" in cls:
            area = clean(tr.get_text()).upper()
        elif "standard-row" in cls:
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            name = clean(tds[0].get_text()).split(" - Orari")[0]
            name = re.sub(r"^\d+\.\s*", "", name)
            out.append({"name": name, "open": "APERT" in clean(tds[-1].get_text()).upper(), "area": area})
    return out


def main() -> None:
    cfg = json.loads((ROOT / "config" / "lifts.json").read_text())
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    now = datetime.now(ZoneInfo("Europe/Rome")).isoformat(timespec="minutes")
    data = {}
    for key, src in cfg["sources"].items():
        try:
            if src["kind"] == "multipass":
                lifts = multipass(src["lifts"])
                slopes = multipass(src["slopes"]) if src.get("slopes") else []
                updated = ""
            else:
                soup = get(src["lifts"])
                lifts, slopes = cimone_pane(soup, "impianti_risalita"), cimone_pane(soup, "piste")
                m = re.search(r"Aggiornato il\s*([0-9/]+)\s*ore\s*([0-9.:]+)", soup.get_text(" "))
                updated = f"{m.group(1)} {m.group(2).replace('.', ':')}" if m else ""
            if not lifts:
                raise ValueError("nessun impianto trovato: la pagina è cambiata?")
            data[key] = {"name": src["name"], "url": src["lifts"], "fetched": now, "updated": updated,
                         "lifts": lifts, "slopes": slopes}
            print(f"{key}: {sum(l['open'] for l in lifts)}/{len(lifts)} impianti aperti")
        except Exception as e:  # noqa: BLE001
            print(f"{key}: non letto ({e}), tengo i dati precedenti")
            if key in old:
                data[key] = old[key]
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
