"""Tendenza a 15 giorni dai 51 scenari dell'ensemble ECMWF sul crinale.

Per ogni giorno e ogni scenario: temperatura media a 850 hPa (~1.500 m), pioggia del giorno, direzione del
flusso a 700 hPa. Ogni scenario finisce in uno di cinque "tipi di tempo"; contiamo quanti scenari per tipo.
"""
from __future__ import annotations

import math
import statistics as st
from collections import Counter, defaultdict

from compute import flow_of
from i18n import T, cap, day_short, nice_date

TYPES = [  # chiave, etichetta, emoji, colore
    ("neve", "Neve fino alle stazioni", "❄️", "#2563eb"),
    ("neve-alto", "Neve in quota, pioggia sotto", "🌨️", "#60a5fa"),
    ("pioggia", "Pioggia", "🌧️", "#94a3b8"),
    ("freddo", "Freddo e asciutto", "🥶", "#a5b4fc"),
    ("mite", "Asciutto e mite", "☀️", "#fbbf24"),
]


def classify(t: float, p: float) -> str:
    wet = p >= 2.0
    if wet:
        return "neve" if t <= -2 else ("neve-alto" if t <= 1 else "pioggia")
    return "freddo" if t <= -2 else "mite"


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def trend(raw: dict, today: str) -> dict:
    h = raw.get("hourly", {})
    times = h.get("time", [])
    members = sorted({k.split("_member")[1] for k in h if "_member" in k})
    keys = [""] + [f"_member{m}" for m in members]  # "" = controllo
    by_day = defaultdict(list)
    for i, ts in enumerate(times):
        if ts[:10] >= today:
            by_day[ts[:10]].append(i)
    days = []
    for d, idx in sorted(by_day.items()):
        if len(idx) < 12:
            continue
        ts_, types, flows = [], Counter(), Counter()
        for k in keys:
            T8 = h.get(f"temperature_850hPa{k}") or []
            P = h.get(f"precipitation{k}") or []
            D = h.get(f"wind_direction_700hPa{k}") or []
            tv = [T8[i] for i in idx if i < len(T8) and T8[i] is not None]
            if not tv:
                continue
            t = st.mean(tv)
            p = sum((P[i] or 0) for i in idx if i < len(P))
            dv = [D[i] for i in idx if i < len(D) and D[i] is not None]
            if dv:
                sx, cx = sum(math.sin(math.radians(x)) for x in dv), sum(math.cos(math.radians(x)) for x in dv)
                flows[flow_of(math.degrees(math.atan2(sx, cx)) % 360)[0]] += 1
            ts_.append(t)
            types[classify(t, p)] += 1
        n = sum(types.values())
        if not n:
            continue
        days.append({"date": d, "n": n, "t50": st.median(ts_), "t10": pct(ts_, .1), "t90": pct(ts_, .9),
                     "mix": {k: types.get(k, 0) / n for k, *_ in TYPES},
                     "flow": flows.most_common(1)[0][0] if flows else "n.d."})
    return {"days": days}


def chart(days: list[dict]) -> str:
    if len(days) < 3:
        return ""
    W, H, P = 900, 230, 30
    lo = min(min(d["t10"] for d in days), -6) - 1
    hi = max(max(d["t90"] for d in days), 4) + 1
    x = lambda i: P + i * (W - 2 * P) / (len(days) - 1)
    y = lambda v: 12 + (hi - v) * (H - 100) / (hi - lo)
    band = " ".join(f"{x(i):.1f},{y(d['t90']):.1f}" for i, d in enumerate(days)) + " " + \
        " ".join(f"{x(i):.1f},{y(d['t10']):.1f}" for i, d in reversed(list(enumerate(days))))
    med = " ".join(f"{x(i):.1f},{y(d['t50']):.1f}" for i, d in enumerate(days))
    sy = y(-3)
    o = [f'<svg viewBox="0 0 {W} {H}" class="syn-chart" role="img" aria-label="{T("Tendenza della temperatura a 1.500 m")}">',
         f'<rect x="{P}" y="{sy:.1f}" width="{W - 2 * P}" height="{H - 88 - sy:.1f}" fill="#dbeafe" opacity=".7"/>',
         f'<line x1="{P}" x2="{W - P}" y1="{sy:.1f}" y2="{sy:.1f}" stroke="#2563eb" stroke-width="1.5"/>',
         f'<text x="{P + 4}" y="{sy + 14:.1f}" class="lbl snow">❄ {T("soglia neve −3 °C")}</text>',
         f'<line x1="{P}" x2="{W - P}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#94a3b8" stroke-dasharray="3 4"/>',
         f'<polygon points="{band}" fill="#0f2236" opacity=".12"/>',
         f'<polyline points="{med}" fill="none" stroke="#0f2236" stroke-width="2.5" stroke-linejoin="round"/>']
    # barre del tipo di tempo, sotto il grafico
    bw = (W - 2 * P) / (len(days) - 1) * .62
    for i, d in enumerate(days):
        y0 = H - 48
        for k, _, _, col in TYPES:
            hgt = d["mix"][k] * 30
            if hgt > 0:
                o.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y0 - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="{col}"/>')
                y0 -= hgt
        if i % 2 == 0 or len(days) <= 8:
            o.append(f'<text x="{x(i):.1f}" y="{H - 6}" text-anchor="middle" class="day">'
                     f'{cap(day_short(d["date"]))} {d["date"][8:].lstrip("0")}</text>')
    o.append("</svg>")
    return "".join(o)


def view(raw: dict | None, today: str) -> dict:
    if not raw:
        return {}
    days = trend(raw, today)["days"]
    if len(days) < 6:
        return {}
    phases = []
    for a, b, lab in ((0, 5, "Prossimi 5 giorni"), (5, 10, "Dal 6° al 10° giorno"), (10, 15, "Dall'11° al 15° giorno")):
        seg = days[a:b]
        if not seg:
            continue
        mix = {k: st.mean(d["mix"][k] for d in seg) for k, *_ in TYPES}
        top = max(mix, key=mix.get)
        meta = {k: (lab_, emo, col) for k, lab_, emo, col in TYPES}
        spread = st.mean(d["t90"] - d["t10"] for d in seg)
        conf = T("alta") if spread < 4 else (T("media") if spread < 7 else T("bassa"))
        snow = mix["neve"] + mix["neve-alto"]
        best = max(seg, key=lambda d: d["mix"]["neve"] + d["mix"]["neve-alto"])
        flows = Counter(d["flow"] for d in seg)
        phases.append({"label": T(lab), "from": nice_date(seg[0]["date"], True), "to": nice_date(seg[-1]["date"], True),
                       "emoji": meta[top][1], "type": T(meta[top][0]), "color": meta[top][2],
                       "share": round(mix[top] * 100), "snow": round(snow * 100),
                       "best": nice_date(best["date"]) if snow >= .1 else "",
                       "t50": f"{st.mean(d['t50'] for d in seg):+.0f}".replace("+0", "0").replace("-0", "0"),
                       "flow": T(flows.most_common(1)[0][0]), "conf": conf,
                       "mix": [(T(meta[k][0]), meta[k][2], round(mix[k] * 100)) for k, *_ in TYPES if mix[k] >= .03]})
    # frase di apertura
    tot = lambda d: d["mix"]["neve"] + d["mix"]["neve-alto"]
    best = max(days, key=tot)
    if tot(best) >= .3 and best["mix"]["neve"] >= best["mix"]["neve-alto"]:
        head = T("❄️ Il segnale più forte di neve fino alle stazioni: intorno a {d} ({p}% degli scenari)",
                 d=nice_date(best["date"]), p=round(tot(best) * 100))
    elif tot(best) >= .3:
        head = T("🌨️ Qualche chance di neve, soprattutto in quota, intorno a {d}", d=nice_date(best["date"]))
    else:
        head = T("☀️ Due settimane senza segnali seri di neve: i 51 scenari restano quasi tutti miti o asciutti")
    return {"head": head, "phases": phases, "chart": chart(days),
            "legend": [(T(lab), emo, col) for _, lab, emo, col in TYPES], "until": nice_date(days[-1]["date"])}
