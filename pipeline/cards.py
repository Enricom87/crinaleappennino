"""Previsione "da telefono": una scheda per giorno con icona, temperature e una frase semplice.

Unisce i dati del bollettino neve (cm per giorno) con quelli del bollettino in quota
(nuvolosità, pioggia, temporali, raffiche) dello stesso punto.
"""
from __future__ import annotations

from datetime import date

from text import GIORNI


def day_label(d: str, today: str) -> str:
    delta = (date.fromisoformat(d) - date.fromisoformat(today)).days
    if delta == 0:
        return "Oggi"
    if delta == 1:
        return "Domani"
    x = date.fromisoformat(d)
    return f"{GIORNI[x.weekday()].capitalize()} {x.day}"


def icon_and_phrase(snow: float, rain: float, storm: int, cloud: float | None, gust: float | None,
                    tmax: float) -> tuple[str, str]:
    """Icona (id del simbolo SVG) e frase breve. Prima ciò che conta di più per chi sale."""
    if snow >= 10:
        return "snow-heavy", f"Nevicata! Circa {snow:.0f} cm"
    if snow >= 1:
        return "snow", f"Neve, {snow:.0f} cm"
    if storm >= 2:
        return "storm", "Temporali nel pomeriggio"
    if rain >= 3:
        return "rain", "Pioggia"
    if rain >= 0.5:
        return "showers", "Qualche goccia"
    if gust is not None and gust >= 60:
        return "wind", "Vento forte in cresta"
    if cloud is None:
        return "partly", "Variabile"
    if cloud >= 75:
        return "cloud", "Cielo coperto"
    if cloud >= 35:
        return "partly", "Sole e nuvole"
    return ("sun", "Sole pieno") if tmax > 0 else ("sun-cold", "Sole e aria frizzante")


def cards(snow_days: list[dict], mtn_days: list[dict], today: str, n: int = 5) -> list[dict]:
    by_date = {r["date"]: r for r in snow_days}
    out = []
    for m in mtn_days[:n]:
        s = by_date.get(m["date"], {})
        snow = s.get("snow", 0) or 0
        icon, phrase = icon_and_phrase(snow, m["rain"], m["storm"], m["cloud"], m["gust"], m["tmax"])
        out.append({
            "date": m["date"], "label": day_label(m["date"], today), "icon": icon, "phrase": phrase,
            "short": day_label(m["date"], today)[:3] if day_label(m["date"], today) not in ("Oggi", "Domani")
                     else day_label(m["date"], today),
            "tmax": m["tmax"], "tmin": m["tmin"], "snow": round(snow), "gust": m["gust"],
            "back_by": m["back_by"], "windy": (m["gust"] or 0) >= 50,
        })
    return out
