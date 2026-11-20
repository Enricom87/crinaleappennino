"""Vista "da leggere al volo" della configurazione: frase di sintesi, grafico della temperatura a 1.500 m
con la soglia della neve, e una scheda per giorno. Testi nella lingua corrente (i18n)."""
from __future__ import annotations

from i18n import T, cap, day_short, nice_date

PATTERN_EMOJI = {
    "tempo asciutto": "☀️", "libeccio su aria fredda": "🌨️", "libeccio mite": "🌧️",
    "irruzione fredda da nord-est": "🥶", "minimo sul Tirreno con richiamo orientale": "🌀",
    "maestrale post-frontale": "🌬️", "scirocco mite": "🌫️", "configurazione mista": "🔀",
}
VERDICT = {"favorevole": ("Neve fino alle stazioni", "fav"), "marginale": ("Neve solo in alto", "mar"),
           "sfavorevole": ("Troppo mite per nevicare", "sfa")}


STOPS = [(-10, (30, 64, 175)), (-3, (37, 99, 235)), (0, (14, 165, 233)), (3, (245, 158, 11)), (10, (234, 88, 12)),
         (16, (220, 38, 38))]


def tcolor(t: float) -> str:
    """Freddo = blu, intorno allo zero = azzurro, mite = ambra, caldo = rosso."""
    if t <= STOPS[0][0]:
        r, g, b = STOPS[0][1]
    elif t >= STOPS[-1][0]:
        r, g, b = STOPS[-1][1]
    else:
        for (a, ca), (z, cz) in zip(STOPS, STOPS[1:]):
            if a <= t <= z:
                k = (t - a) / (z - a)
                r, g, b = (round(ca[i] + (cz[i] - ca[i]) * k) for i in range(3))
                break
    return f"rgb({r},{g},{b})"


def tfmt(t: float) -> str:
    v = round(t)
    return f"{v:+d}°" if v else "0°"


def chart(days: list[dict]) -> str:
    if len(days) < 2:
        return ""
    W, H, P = 900, 210, 30
    ts = [d["t"] for d in days]
    lo, hi = min(min(ts), -6) - 1, max(max(ts), 4) + 1
    x = lambda i: P + i * (W - 2 * P) / (len(days) - 1)
    y = lambda v: 14 + (hi - v) * (H - 44) / (hi - lo)
    pts = " ".join(f"{x(i):.1f},{y(t):.1f}" for i, t in enumerate(ts))
    area = f"{x(0):.1f},{y(lo):.1f} {pts} {x(len(ts) - 1):.1f},{y(lo):.1f}"
    snow_y, zero_y = y(0), y(2.5)
    lab_snow, lab_zero = T("neve fino alle stazioni sotto 0 °C"), T("neve sulle cime sotto +2,5 °C")
    out = [f'<svg viewBox="0 0 {W} {H}" class="syn-chart" role="img" aria-label="{T("Temperatura a 1.500 m")}">',
           '<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f59e0b" stop-opacity=".28"/>'
           '<stop offset="1" stop-color="#3b82f6" stop-opacity=".05"/></linearGradient></defs>',
           f'<rect x="{P}" y="{snow_y:.1f}" width="{W - 2 * P}" height="{H - 30 - snow_y:.1f}" fill="#dbeafe" opacity=".7"/>',
           f'<line x1="{P}" x2="{W - P}" y1="{zero_y:.1f}" y2="{zero_y:.1f}" stroke="#94a3b8" stroke-dasharray="3 4"/>',
           f'<text x="{P + 4}" y="{zero_y - 4:.1f}" class="lbl">{lab_zero}</text>',
           f'<line x1="{P}" x2="{W - P}" y1="{snow_y:.1f}" y2="{snow_y:.1f}" stroke="#2563eb" stroke-width="1.5"/>',
           f'<text x="{P + 4}" y="{snow_y + 14:.1f}" class="lbl snow">❄ {lab_snow}</text>',
           f'<polygon points="{area}" fill="url(#sg)"/>',
           f'<polyline points="{pts}" fill="none" stroke="#0f2236" stroke-width="2.5" stroke-linejoin="round"/>']
    for i, d in enumerate(days):
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(d["t"]):.1f}" r="5" fill="{tcolor(d["t"])}" stroke="#fff" stroke-width="2"/>')
        out.append(f'<text x="{x(i):.1f}" y="{y(d["t"]) - 9:.1f}" text-anchor="middle" class="val">{tfmt(d["t"])}</text>')
        out.append(f'<text x="{x(i):.1f}" y="{H - 8}" text-anchor="middle" class="day">{d["short"]}</text>')
    out.append("</svg>")
    return "".join(out)


def syn_view(rows: list[dict], reg_lv: dict | None = None, z_station: int = 1300) -> dict:
    days = []
    for r in rows[:10]:
        e = r.get("ec") or r.get("gfs")
        if not e:
            continue
        t = e["t850"]
        v_lab, v_cls = VERDICT.get(e["thermal"], ("", "nd"))
        days.append({"date": r["date"], "short": cap(day_short(r["date"])) + " " + r["date"][8:].lstrip("0"),
                     "t": t, "tlab": tfmt(t), "t_gfs": (r.get("gfs") or {}).get("t850"), "color": tcolor(t),
                     "emoji": PATTERN_EMOJI.get(r["name"], "🌤️"), "pattern": T(r["name"]),
                     "dir": e.get("dir"), "flow": T(e["flow"]), "verdict": T(v_lab), "vcls": v_cls,
                     "wet": e.get("precip", 0) >= 1})
    if not days:
        return {}
    fav = next((d for d in days if d["vcls"] == "fav"), None)
    mar = next((d for d in days if d["vcls"] == "mar"), None)
    coldest = min(days, key=lambda d: d["t"])
    reg_lv = reg_lv or {}
    lv_fav = reg_lv.get(fav["date"]) if fav else None
    if fav and lv_fav is not None and lv_fav > z_station + 150:
        # l'aria a 1.500 m sarebbe abbastanza fredda, ma il calcolo quota per quota dice che la neve resta più su:
        # il titolo deve dire la stessa cosa delle località
        head = T("📉 Si rinfresca da {d}: neve dai {z} m circa in su, le stazioni più basse restano al limite",
                 d=nice_date(fav["date"]), z=int(round(lv_fav / 100.0) * 100))
    elif fav:
        head = T("🥶 Arriva il freddo vero: da {d} aria abbastanza fredda per la neve fino alle stazioni",
                 d=nice_date(fav["date"]))
    elif mar:
        head = T("📉 Si rinfresca da {d}: neve possibile, ma solo sulle cime", d=nice_date(mar["date"]))
    else:
        head = T("🌡️ Aria troppo mite per tutto il periodo: in quota si resta sopra lo zero (minimo {t} °C {d})",
                 t=f"{coldest['t']:+.0f}", d=nice_date(coldest["date"]))
    return {"head": head, "days": days, "chart": chart(days)}
