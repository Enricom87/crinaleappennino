"""Condizioni previste lungo un percorso, ricavate dai punti meteo della sua località."""
from __future__ import annotations

from datetime import datetime, timedelta

from i18n import T, nice_date

LABELS = {"escursionismo": "Escursionismo", "ciaspole": "Ciaspole", "scialpinismo": "Scialpinismo",
          "trail-running": "Trail running", "mtb-gravel": "MTB e gravel"}


def nearest(points: list[dict], z: float) -> dict:
    return min(points, key=lambda p: abs(p["elev"] - z))


def at_elev(points: list[dict], z: float, date: str, key: str):
    """Valore interpolato alla quota z tra i due punti che la racchiudono (altrimenti il più vicino)."""
    rows = []
    for p in points:
        r = next((x for x in p["days"] if x["date"] == date), None)
        if r is not None and r.get(key) is not None:
            rows.append((p["elev"], r[key]))
    if not rows:
        return None
    rows.sort()
    below = [r for r in rows if r[0] <= z]
    above = [r for r in rows if r[0] >= z]
    if below and above and above[0][0] != below[-1][0]:
        (z0, v0), (z1, v1) = below[-1], above[0]
        return v0 + (v1 - v0) * (z - z0) / (z1 - z0)
    return min(rows, key=lambda r: abs(r[0] - z))[1]


def past_precip(raw_point: dict, hours: int = 48) -> float | None:
    """Pioggia/neve caduta nelle ultime ore secondo ECMWF (serve past_days nel download)."""
    if not raw_point:
        return None
    h = raw_point.get("hourly", {})
    times, P = h.get("time", []), h.get("precipitation_ecmwf_ifs025") or []
    now = datetime.now()
    start = now - timedelta(hours=hours)
    tot, seen = 0.0, False
    for t, p in zip(times, P):
        dt = datetime.fromisoformat(t)
        if start <= dt <= now and p is not None:
            tot += p
            seen = True
    return round(tot, 1) if seen else None


def route_conditions(route: dict, loc_points: list[dict], raw_glob: dict) -> dict:
    s = route["stats"]
    top = nearest(loc_points, s["z_max"] or 1500)
    low = nearest(loc_points, s["z_min"] or 1200)
    days = []
    zt, zl = s["z_max"] or 1500, s["z_min"] or 1200
    for r_top in top["days"][:4]:
        d = r_top["date"]
        r_low = next((x for x in low["days"] if x["date"] == d), r_top)
        days.append({"date": d, "snow_top": round(at_elev(loc_points, zt, d, "snow") or 0, 1),
                     "snow_low": round(at_elev(loc_points, zl, d, "snow") or 0, 1),
                     "tmin_top": at_elev(loc_points, zt, d, "tmin"), "tmax_low": r_low["tmax"],
                     "gust_top": r_top["gust"], "precip": r_low["precip"], "fl": r_top["fl_min"]})
    past = past_precip(raw_glob.get(low["id"]))
    notes = []
    acts = route["activities"]
    zq = int(round(zt, -2))
    snow3 = sum(d["snow_top"] for d in days[:3])
    windy = [d for d in days[:3] if d["gust_top"] and d["gust_top"] >= 50]
    icy = [d for d in days[:3] if d["tmin_top"] is not None and d["tmin_top"] <= 0]

    if any(a in acts for a in ("ciaspole", "scialpinismo")):
        if snow3 >= 10:
            notes.append(T("Neve fresca prevista in quota nei prossimi 3 giorni: circa {n} cm intorno ai {zq} m.", n=f"{snow3:.0f}", zq=zq))
        elif snow3 >= 1:
            notes.append(T("Poca neve fresca prevista in quota (circa {n} cm in 3 giorni).", n=f"{snow3:.0f}"))
        else:
            notes.append(T("Nessuna nevicata prevista nei prossimi 3 giorni."))
        notes.append(T("Il sito non misura la neve al suolo: controlla le webcam della località e, per lo scialpinismo, "
                     "il bollettino valanghe Meteomont prima di partire."))
    if any(a in acts for a in ("escursionismo", "trail-running")):
        if icy and ((past or 0) >= 2 or any(d["precip"] >= 1 for d in days[:3])):
            notes.append(T("Possibile ghiaccio sui tratti alti (intorno ai {zq} m): minime sotto zero dopo precipitazioni "
                         "({days}).", zq=zq, days=', '.join(nice_date(d['date'], True) for d in icy[:3])))
        if snow3 >= 3 and "ciaspole" not in acts:
            notes.append(T("Neve prevista in quota ({n} cm in 3 giorni): sul tratto alto possono servire ciaspole o ramponcini.", n=f"{snow3:.0f}"))
    if "mtb-gravel" in acts:
        if past is not None:
            if past >= 15:
                notes.append(T("Fondo probabilmente fangoso: {n} mm di pioggia nelle ultime 48 ore.", n=f"{past:.0f}"))
            elif past >= 5:
                notes.append(T("Possibili tratti fangosi: {n} mm di pioggia nelle ultime 48 ore.", n=f"{past:.0f}"))
            else:
                notes.append(T("Fondo verosimilmente asciutto: poca o nessuna pioggia nelle ultime 48 ore."))
        if snow3 >= 1:
            notes.append(T("Neve prevista sui tratti alti: verifica la percorribilità."))
    if windy:
        d = max(windy, key=lambda x: x["gust_top"])
        notes.append(T("Vento forte in quota: raffiche fino a {g} km/h {d}.", g=d['gust_top'], d=nice_date(d['date'])))
    if not notes:
        notes.append(T("Nessuna criticità meteo evidente nei prossimi giorni."))
    return {"top_point": top["name"], "top_elev": top["elev"], "z_used": zq, "low_point": low["name"], "days": days,
            "past48": past, "notes": notes}


def profile_svg(route: dict) -> str:
    """Profilo altimetrico del percorso principale, SVG statico."""
    from routes import haversine
    lines = route["geojson"]["geometry"]["coordinates"]
    ln = [p for p in lines[0] if len(p) > 2]  # percorso principale, già concatenato da routes.chain
    if len(ln) < 2:
        return ""
    d, xs = 0.0, [0.0]
    for a, b in zip(ln, ln[1:]):
        d += haversine(a, b)
        xs.append(d)
    zs = [p[2] for p in ln]
    W, H, pl, pb, pt = 640, 160, 40, 24, 10
    zmin, zmax = min(zs), max(zs)
    zmin, zmax = (zmin // 100) * 100, (zmax // 100 + 1) * 100
    X = lambda x: pl + (W - pl - 6) * x / max(xs[-1], 1)
    Y = lambda z: H - pb - (H - pb - pt) * (z - zmin) / max(zmax - zmin, 1)
    path = " ".join(f"{X(x):.1f},{Y(z):.1f}" for x, z in zip(xs, zs))
    area = f"{X(0):.1f},{H - pb} {path} {X(xs[-1]):.1f},{H - pb}"
    grid = "".join(f'<line x1="{pl}" x2="{W - 4}" y1="{Y(z):.1f}" y2="{Y(z):.1f}" class="grid"/>'
                   f'<text x="{pl - 4}" y="{Y(z) + 4:.1f}" class="ax" text-anchor="end">{int(z)}</text>'
                   for z in range(int(zmin), int(zmax) + 1, 200 if zmax - zmin > 600 else 100))
    km = xs[-1] / 1000
    ticks = "".join(f'<text x="{X(k * 1000):.1f}" y="{H - 6}" class="ax" text-anchor="middle">{k} km</text>'
                    for k in range(0, int(km) + 1, max(1, int(km // 6) or 1)))
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{T("Profilo altimetrico")}">{grid}'
            f'<polygon points="{area}" fill="#9cc4e4" opacity=".55"/><polyline points="{path}" fill="none" '
            f'stroke="#1d4f7a" stroke-width="2"/>{ticks}</svg>')
