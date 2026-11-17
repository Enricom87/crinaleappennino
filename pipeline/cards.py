"""Previsione "da telefono": una scheda per giorno con icona, temperature e una frase semplice.

Unisce i dati del bollettino neve (cm per giorno) con quelli del bollettino in quota
(nuvolosità, pioggia, temporali, raffiche) dello stesso punto.
"""
from __future__ import annotations

from datetime import date

import i18n
from i18n import T, cap, day_name, day_short


def day_label(d: str, today: str) -> str:
    delta = (date.fromisoformat(d) - date.fromisoformat(today)).days
    if delta == 0:
        return T("Oggi")
    if delta == 1:
        return T("Domani")
    x = date.fromisoformat(d)
    return f"{day_name(d)} {x.day}" if i18n.LANG != "zh" else f"{day_short(d)} {x.day}日"


def icon_and_phrase(snow: float, rain: float, storm: int, cloud: float | None, gust: float | None,
                    tmax: float) -> tuple[str, str]:
    """Icona (id del simbolo SVG) e frase breve. Prima ciò che conta di più per chi sale."""
    if snow >= 10:
        return "snow-heavy", T("Nevicata! Circa {n} cm", n=f"{snow:.0f}")
    if snow >= 1:
        return "snow", T("Neve, {n} cm", n=f"{snow:.0f}")
    if storm >= 2:
        return "storm", T("Temporali nel pomeriggio")
    if rain >= 3:
        return "rain", T("Pioggia")
    if rain >= 0.5:
        return "showers", T("Qualche goccia")
    if gust is not None and gust >= 60:
        return "wind", T("Vento forte in cresta")
    if cloud is None:
        return "partly", T("Variabile")
    if cloud >= 75:
        return "cloud", T("Cielo coperto")
    if cloud >= 35:
        return "partly", T("Sole e nuvole")
    return ("sun", T("Sole pieno")) if tmax > 0 else ("sun-cold", T("Sole e aria frizzante"))


def cards(snow_days: list[dict], mtn_days: list[dict], today: str, n: int = 5) -> list[dict]:
    by_date = {r["date"]: r for r in snow_days}
    out = []
    for m in mtn_days[:n]:
        s = by_date.get(m["date"], {})
        snow = s.get("snow", 0) or 0
        icon, phrase = icon_and_phrase(snow, m["rain"], m["storm"], m["cloud"], m["gust"], m["tmax"])
        out.append({
            "date": m["date"], "label": day_label(m["date"], today), "icon": icon, "phrase": phrase,
            "short": cap(day_short(m["date"])) if day_label(m["date"], today) not in (T("Oggi"), T("Domani"))
                     else day_label(m["date"], today),
            "tmax": m["tmax"], "tmin": m["tmin"], "snow": round(snow), "gust": m["gust"],
            "back_by": m["back_by"], "windy": (m["gust"] or 0) >= 50, "sure": certainty(m["idx"]),
        })
    return out


def hour_icon(h: dict) -> str:
    """Icona per una singola ora, con luna di notte."""
    hr = int(h["time"][11:13])
    night = hr < 7 or hr >= 18
    if h["snow"] >= 1.5:
        return "snow-heavy"
    if h["snow"] >= 0.2:
        return "snow"
    if h["cape"] >= 500 and h["rain"] >= 0.5:
        return "storm"
    if h["rain"] >= 1:
        return "rain"
    if h["rain"] >= 0.2:
        return "rain" if night else "showers"
    if h["gust"] >= 60:
        return "wind"
    if h["cloud"] >= 75:
        return "cloud"
    if h["cloud"] >= 35:
        return "moon-cloud" if night else "partly"
    return "moon" if night else ("sun" if h["t"] > 0 else "sun-cold")


def hourly_strip(hours: list[dict]) -> list[dict]:
    """Celle per la striscia oraria: ora, icona, temperatura, precipitazione, raffica, cambio di giorno."""
    from i18n import cap, day_name
    out, prev = [], None
    for h in hours:
        d = h["time"][:10]
        out.append({**h, "hour": h["time"][11:13], "icon": hour_icon(h),
                    "newday": cap(day_name(d)) if prev and d != prev else None})
        prev = d
    return out


def certainty(idx: int) -> dict:
    """Quanto fidarsi, in base a quanto è lontano il giorno."""
    if idx <= 1:
        return {"key": "sure", "label": T("Affidabile"), "icon": "🔒"}
    if idx <= 4:
        return {"key": "likely", "label": T("Probabile"), "icon": "📈"}
    return {"key": "trend", "label": T("Tendenza"), "icon": "🔭"}


def prob_word(p: float) -> str:
    """Probabilità in parole (p in %)."""
    if p >= 90:
        return T("quasi sicura")
    if p >= 60:
        return T("probabile")
    if p >= 30:
        return T("possibile")
    if p >= 10:
        return T("poco probabile")
    return T("improbabile")
