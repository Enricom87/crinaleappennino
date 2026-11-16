"""Vendita automatica degli spazi sponsor con Stripe Payment Links.

Ogni corsa del workflow:
  1. crea (o ricrea, se cambia prezzo o stagione) un link di pagamento per ogni spazio in vendita;
     ogni link si disattiva da solo quando i posti sono finiti (restrictions.completed_sessions);
  2. legge gli acquisti pagati e li scrive in data/sponsors_sold.json;
  3. toglie chi è stato rimborsato.
Il sito e le email leggono gli sponsor con merged_sponsors(): quelli a mano (config/sponsors.json)
più quelli venduti e ancora validi. Senza STRIPE_API_KEY non fa nulla.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
SHOP = ROOT / "config" / "shop.json"
STATE = ROOT / "data" / "shop_state.json"
SOLD = ROOT / "data" / "sponsors_sold.json"
API = "https://api.stripe.com/v1"


def load(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def season(today: date) -> tuple[str, str]:
    """Stagione corrente e ultimo giorno di visibilità: da aprile si vende già la stagione successiva."""
    y = today.year if today.month >= 4 else today.year - 1
    return f"{y}-{(y + 1) % 100:02d}", f"{y + 1}-03-31"


def slots(cfg: dict, locs: list[dict]) -> list[dict]:
    out = []
    for p in cfg["products"]:
        if p["scope"] == "location":
            for L in locs:
                out.append({"id": f"{p['id']}:{L['slug']}", "product": p, "where": L["slug"],
                            "label": f"{p['name']} · {L['name']}"})
        else:
            out.append({"id": p["id"], "product": p, "where": p["scope"], "label": p["name"]})
    return out


def price_cents(p: dict, cfg: dict, today: date) -> int:
    eur = p["price_eur"]
    if today.isoformat() <= cfg.get("founder_until", ""):
        eur = round(eur * (1 - cfg.get("founder_discount", 0)))
    return int(eur * 100)


class Stripe:
    def __init__(self, key: str):
        self.s = requests.Session()
        self.s.auth = (key, "")

    def post(self, path: str, data: dict) -> dict:
        r = self.s.post(f"{API}/{path}", data=data, timeout=40)
        if r.status_code >= 400:
            raise RuntimeError(f"Stripe {path}: {r.status_code} {r.text[:300]}")
        return r.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        r = self.s.get(f"{API}/{path}", params=params or {}, timeout=40)
        r.raise_for_status()
        return r.json()

    def list_all(self, path: str, params: dict) -> list[dict]:
        out, after = [], None
        while True:
            q = dict(params, limit=100, **({"starting_after": after} if after else {}))
            page = self.get(path, q)
            out += page["data"]
            if not page.get("has_more"):
                return out
            after = page["data"][-1]["id"]


def make_link(st: Stripe, slot: dict, cents: int, limit: int, seas: str, site: dict) -> dict:
    prod = st.post("products", {"name": f"{site['name']} · {slot['label']} · stagione {seas}",
                                "metadata[slot]": slot["id"], "metadata[season]": seas})
    price = st.post("prices", {"product": prod["id"], "currency": "eur", "unit_amount": cents})
    fields = [("nome", "Nome dell'attività", 60), ("sito", "Sito web o pagina di prenotazione", 200),
              ("frase", "Frase di presentazione (max 100 caratteri)", 100)]
    data = {"line_items[0][price]": price["id"], "line_items[0][quantity]": 1,
            "metadata[slot]": slot["id"], "metadata[season]": seas,
            "phone_number_collection[enabled]": "true",
            "invoice_creation[enabled]": "true",
            "restrictions[completed_sessions][limit]": limit,
            "inactive_message": "Posti esauriti per questa stagione. Scrivi a " + site["contact_email"],
            "after_completion[type]": "hosted_confirmation",
            "after_completion[hosted_confirmation][custom_message]":
                "Grazie! Il tuo spazio comparirà su " + site["base_url"].replace("https://", "") +
                " entro poche ore. Per modifiche scrivi a " + site["contact_email"] + "."}
    for i, (k, label, mx) in enumerate(fields):
        data |= {f"custom_fields[{i}][key]": k, f"custom_fields[{i}][type]": "text",
                 f"custom_fields[{i}][label][type]": "custom", f"custom_fields[{i}][label][custom]": label,
                 f"custom_fields[{i}][text][maximum_length]": mx}
    link = st.post("payment_links", data)
    return {"link_id": link["id"], "url": link["url"], "cents": cents, "season": seas, "limit": limit}


def clean_url(u: str) -> str:
    u = (u or "").strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u if re.match(r"^https?://[\w.-]+\.[a-z]{2,}(/\S*)?$", u, re.I) else ""


def sync() -> None:
    key = os.environ.get("STRIPE_API_KEY", "").strip()
    if not key:
        print("shop: nessuna chiave Stripe, salto")
        return
    st = Stripe(key)
    cfg = load(SHOP, {})
    site = load(ROOT / "config" / "site.json", {})
    locs = load(ROOT / "config" / "locations.json", {})["locations"]
    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    seas, until = season(today)
    state = load(STATE, {"links": {}})
    sold = load(SOLD, {"items": []})
    known = {i["session"] for i in sold["items"]}

    for slot in slots(cfg, locs):
        p = slot["product"]
        cur = state["links"].get(slot["id"])
        cents = price_cents(p, cfg, today)
        # acquisti del link attuale (e dei precedenti della stessa stagione)
        for lid in ([cur["link_id"]] if cur else []) + [o for o in (cur or {}).get("old", [])]:
            for s in st.list_all("checkout/sessions", {"payment_link": lid, "status": "complete"}):
                if s["payment_status"] != "paid" or s["id"] in known:
                    continue
                f = {c["key"]: (c.get("text") or {}).get("value", "") for c in s.get("custom_fields", [])}
                sold["items"].append({
                    "session": s["id"], "payment_intent": s.get("payment_intent"), "slot": slot["id"],
                    "where": slot["where"], "product": p["id"], "season": (cur or {}).get("season", seas),
                    "until": until, "name": f.get("nome", "").strip()[:60] or (s.get("customer_details") or {}).get("name", ""),
                    "url": clean_url(f.get("sito", "")), "tagline": f.get("frase", "").strip()[:100],
                    "paid_at": s["created"]})
                known.add(s["id"])
                print(f"shop: nuovo sponsor {slot['id']}: {sold['items'][-1]['name']}")
        taken = sum(1 for i in sold["items"] if i["slot"] == slot["id"] and i["season"] == seas and not i.get("refunded"))
        left = p["max"] - taken
        need_new = cur is None or cur["season"] != seas or cur["cents"] != cents
        if need_new and left > 0:
            if cur:
                st.post(f"payment_links/{cur['link_id']}", {"active": "false"})
            new = make_link(st, slot, cents, left, seas, site)
            new["old"] = ((cur or {}).get("old", []) + [cur["link_id"]])[-4:] if cur and cur["season"] == seas else []
            state["links"][slot["id"]] = new
            print(f"shop: link {slot['id']} a {cents / 100:.0f} € ({left} posti)")
        if slot["id"] in state["links"]:
            state["links"][slot["id"]]["left"] = max(left, 0)

    # rimborsi: chi è stato rimborsato sparisce dal sito
    for i in sold["items"]:
        if i.get("refunded") or not i.get("payment_intent"):
            continue
        pi = st.get(f"payment_intents/{i['payment_intent']}", {"expand[]": "latest_charge"})
        if (pi.get("latest_charge") or {}).get("refunded"):
            i["refunded"] = True
            print(f"shop: rimborsato {i['slot']}")

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))
    SOLD.write_text(json.dumps(sold, indent=1, ensure_ascii=False))


def merged_sponsors(today: date | None = None) -> dict:
    """Sponsor a mano + venduti e ancora validi. Chiavi: slug località, _global, _newsletter."""
    today = today or datetime.now(ZoneInfo("Europe/Rome")).date()
    manual = load(ROOT / "config" / "sponsors.json", {})
    out = {k: list(v) for k, v in manual.items() if not k.startswith("_comment")}
    cfg = load(SHOP, {"products": []})
    places = {p["id"]: p["shows_on"] for p in cfg.get("products", [])}
    locs = [L["slug"] for L in load(ROOT / "config" / "locations.json", {"locations": []})["locations"]]
    for i in load(SOLD, {"items": []})["items"]:
        if i.get("refunded") or i["until"] < today.isoformat() or not i["url"]:
            continue
        card = {"name": i["name"], "tagline": i["tagline"], "url": i["url"], "logo": ""}
        for where in places.get(i["product"], []):
            targets = [i["where"]] if where == "location" else (locs if where == "all_locations" else [where])
            for t in targets:
                out.setdefault(t, []).append(card)
    return out


def offers() -> list[dict]:
    """Per la pagina sponsor: prezzo, posti rimasti e link di pagamento di ogni spazio."""
    cfg = load(SHOP, {"products": []})
    state = load(STATE, {"links": {}})
    locs = load(ROOT / "config" / "locations.json", {"locations": []})["locations"]
    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    out = []
    for p in cfg.get("products", []):
        cents = price_cents(p, cfg, today)
        rows = []
        for slot in slots({"products": [p]}, locs):
            s = state["links"].get(slot["id"], {})
            rows.append({"label": slot["label"].split(" · ", 1)[-1], "url": s.get("url", ""),
                         "left": s.get("left", p["max"])})
        out.append({**p, "price_now": cents // 100, "full": p["price_eur"], "rows": rows,
                    "founder": cents // 100 != p["price_eur"]})
    return out


if __name__ == "__main__":
    sync()
