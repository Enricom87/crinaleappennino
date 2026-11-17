"""Tendenza fino a 30 giorni da tutti gli ensemble disponibili sopra il crinale (fino a ~300 scenari).

Per ogni modello, giorno e scenario: temperatura media (850 hPa, o al suolo a 1.500 m per i modelli che non
danno la quota), pioggia del giorno, direzione del flusso a 700 hPa se c'è. Ogni scenario finisce in uno di
cinque "tipi di tempo". Nel riassunto ogni modello pesa uguale, qualunque sia il numero dei suoi scenari.
"""
from __future__ import annotations

import json
import math
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from compute import flow_of
from i18n import T, cap, day_short, nice_date

TYPES = [  # chiave, etichetta, emoji, colore
    ("neve", "Neve fino alle stazioni", "❄️", "#2563eb"),
    ("neve-alto", "Neve in quota, pioggia sotto", "🌨️", "#60a5fa"),
    ("pioggia", "Pioggia", "🌧️", "#94a3b8"),
    ("freddo", "Freddo e asciutto", "🥶", "#a5b4fc"),
    ("mite", "Asciutto e mite", "☀️", "#fbbf24"),
]
MODELS = [  # chiave, nome, provenienza, colore della linea
    ("ecmwf", "ECMWF IFS", "Europa", "#0f2236"),
    ("aifs", "ECMWF AIFS", "Europa · IA", "#475569"),
    ("gfs", "GFS", "USA", "#dc2626"),
    ("gem", "GEM", "Canada", "#ea580c"),
    ("weathernext", "WeatherNext 2", "Google · IA", "#7c3aed"),
    ("icon", "ICON", "Germania", "#16a34a"),
    ("ukmo", "UK Met Office", "Regno Unito", "#0891b2"),
    ("ch2", "ICON-CH2", "Svizzera", "#be185d"),
]
VARS = ("temperature_850hPa", "temperature_2m", "precipitation", "wind_direction_700hPa")


def classify(t: float, p: float) -> str:
    if p >= 2.0:
        return "neve" if t <= -2 else ("neve-alto" if t <= 1 else "pioggia")
    return "freddo" if t <= -2 else "mite"


def pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    f, c = math.floor(k), math.ceil(k)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def normalize(raw: dict) -> tuple[list[str], dict[str, dict[str, list]]]:
    """Riordina le colonne per scenario: {"00": {var: valori}, "01": …} ("00" = corsa di controllo)."""
    h = raw.get("hourly", {})
    out: dict[str, dict[str, list]] = defaultdict(dict)
    for k, v in h.items():
        var = next((x for x in VARS if k.startswith(x)), None)
        if not var:
            continue
        m = re.search(r"_member(\d+)", k)
        out[m.group(1) if m else "00"][var] = v
    return h.get("time", []), out


def trend(raw: dict, today: str) -> list[dict]:
    times, members = normalize(raw)
    by_day = defaultdict(list)
    for i, ts in enumerate(times):
        if ts[:10] >= today:
            by_day[ts[:10]].append(i)
    days = []
    for d, idx in sorted(by_day.items()):
        if len(idx) < 12:
            continue
        ts_, types, flows = [], Counter(), Counter()
        for cols in members.values():
            T8 = cols.get("temperature_850hPa") or cols.get("temperature_2m") or []
            P = cols.get("precipitation") or []
            D = cols.get("wind_direction_700hPa") or []
            tv = [T8[i] for i in idx if i < len(T8) and T8[i] is not None]
            pv = [P[i] for i in idx if i < len(P) and P[i] is not None]
            if len(tv) < 4 or not pv:
                continue
            t, p = st.mean(tv), sum(pv)
            dv = [D[i] for i in idx if i < len(D) and D[i] is not None]
            if dv:
                sx, cx = sum(math.sin(math.radians(x)) for x in dv), sum(math.cos(math.radians(x)) for x in dv)
                flows[flow_of(math.degrees(math.atan2(sx, cx)) % 360)[0]] += 1
            ts_.append(t)
            types[classify(t, p)] += 1
        n = sum(types.values())
        if n < 5:
            continue
        days.append({"date": d, "n": n, "t50": st.median(ts_), "t10": pct(ts_, .1), "t90": pct(ts_, .9),
                     "mix": {k: types.get(k, 0) / n for k, *_ in TYPES},
                     "flow": flows.most_common(1)[0][0] if flows else None})
    return days


def combine(per_model: dict[str, list[dict]]) -> list[dict]:
    """Un giorno "medio": ogni modello pesa uguale."""
    dates = sorted({d["date"] for days in per_model.values() for d in days})
    out = []
    for date in dates:
        rows = [d for days in per_model.values() for d in days if d["date"] == date]
        if not rows:
            continue
        flows = Counter(r["flow"] for r in rows if r["flow"])
        out.append({"date": date, "models": len(rows), "n": sum(r["n"] for r in rows),
                    "t50": st.median(r["t50"] for r in rows), "t10": min(r["t10"] for r in rows),
                    "t90": max(r["t90"] for r in rows),
                    "mix": {k: st.mean(r["mix"][k] for r in rows) for k, *_ in TYPES},
                    "flow": flows.most_common(1)[0][0] if flows else "n.d."})
    return out


def chart(days: list[dict], per_model: dict[str, list[dict]]) -> str:
    if len(days) < 3:
        return ""
    W, H, P = 900, 250, 30
    lo = min(min(d["t10"] for d in days), -6) - 1
    hi = max(max(d["t90"] for d in days), 4) + 1
    x = lambda i: P + i * (W - 2 * P) / (len(days) - 1)
    y = lambda v: 12 + (hi - v) * (H - 100) / (hi - lo)
    pos = {d["date"]: i for i, d in enumerate(days)}
    band = " ".join(f"{x(i):.1f},{y(d['t90']):.1f}" for i, d in enumerate(days)) + " " + \
        " ".join(f"{x(i):.1f},{y(d['t10']):.1f}" for i, d in reversed(list(enumerate(days))))
    sy = y(-3)
    o = [f'<svg viewBox="0 0 {W} {H}" class="syn-chart" role="img" aria-label="{T("Tendenza della temperatura a 1.500 m")}">',
         f'<rect x="{P}" y="{sy:.1f}" width="{W - 2 * P}" height="{H - 88 - sy:.1f}" fill="#dbeafe" opacity=".7"/>',
         f'<line x1="{P}" x2="{W - P}" y1="{sy:.1f}" y2="{sy:.1f}" stroke="#2563eb" stroke-width="1.5"/>',
         f'<text x="{P + 4}" y="{sy + 14:.1f}" class="lbl snow">❄ {T("soglia neve −3 °C")}</text>',
         f'<line x1="{P}" x2="{W - P}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="#94a3b8" stroke-dasharray="3 4"/>',
         f'<polygon points="{band}" fill="#0f2236" opacity=".09"/>']
    if len(days) > 15:  # oltre il 15° giorno restano solo GFS e GEM
        xs = x(14.5) if len(days) > 15 else W
        o.append(f'<rect x="{xs:.1f}" y="6" width="{W - P - xs:.1f}" height="{H - 94}" fill="#fff" opacity=".45"/>')
        o.append(f'<text x="{xs + 6:.1f}" y="20" class="lbl">{T("solo GFS e GEM")}</text>')
    for key, _, _, col in MODELS:
        md = [d for d in per_model.get(key, []) if d["date"] in pos]
        if len(md) > 1:
            pts = " ".join(f"{x(pos[d['date']]):.1f},{y(d['t50']):.1f}" for d in md)
            o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{2.6 if key == "ecmwf" else 1.6}" '
                     f'stroke-linejoin="round" opacity="{1 if key == "ecmwf" else .85}"/>')
    bw = (W - 2 * P) / (len(days) - 1) * .62
    step = 2 if len(days) <= 16 else 4
    for i, d in enumerate(days):
        y0 = H - 48
        for k, _, _, col in TYPES:
            hgt = d["mix"][k] * 30
            if hgt > 0:
                o.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y0 - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="{col}"/>')
                y0 -= hgt
        if i % step == 0:
            o.append(f'<text x="{x(i):.1f}" y="{H - 6}" text-anchor="middle" class="day">'
                     f'{cap(day_short(d["date"]))} {d["date"][8:].lstrip("0")}</text>')
    o.append("</svg>")
    return "".join(o)


def view_dir(path: Path, today: str) -> dict:
    raws = {}
    for key, *_ in MODELS:
        f = path / f"{key}.json"
        if f.exists():
            try:
                raws[key] = json.loads(f.read_text())
            except ValueError:
                pass
    return view(raws, today)


def view(raws: dict[str, dict], today: str) -> dict:
    per_model = {k: trend(r, today) for k, r in raws.items()}
    per_model = {k: v for k, v in per_model.items() if v}
    days = combine(per_model)[:30]
    if len(days) < 6:
        return {}
    meta = {k: (lab, emo, col) for k, lab, emo, col in TYPES}
    phases = []
    for a, b, lab in ((0, 5, "Prossimi 5 giorni"), (5, 10, "Dal 6° al 10° giorno"),
                      (10, 15, "Dall'11° al 15° giorno"), (15, 30, "Dal 16° al 30° giorno")):
        seg = days[a:b]
        if len(seg) < 3:
            continue
        dates = {d["date"] for d in seg}
        mix = {k: st.mean(d["mix"][k] for d in seg) for k, *_ in TYPES}
        top = max(mix, key=mix.get)
        spread = st.mean(d["t90"] - d["t10"] for d in seg)
        conf = T("alta") if spread < 5 else (T("media") if spread < 9 else T("bassa"))
        if a >= 15:
            conf = T("bassa")
        best = max(seg, key=lambda d: d["mix"]["neve"] + d["mix"]["neve-alto"])
        snow = mix["neve"] + mix["neve-alto"]
        rows = []
        for key, name, origin, col in MODELS:
            md = [d for d in per_model.get(key, []) if d["date"] in dates]
            if len(md) < max(2, len(seg) // 2):
                continue
            rows.append({"name": name, "origin": T(origin), "color": col, "n": round(st.mean(d["n"] for d in md)),
                         "snow": round(st.mean(d["mix"]["neve"] + d["mix"]["neve-alto"] for d in md) * 100),
                         "cold": round(st.mean(d["mix"]["neve"] + d["mix"]["freddo"] for d in md) * 100),
                         "t": f"{st.mean(d['t50'] for d in md):+.0f}"})
        flows = Counter(d["flow"] for d in seg if d["flow"] != "n.d.")
        agree = sum(1 for r in rows if r["snow"] >= 30)
        phases.append({"label": T(lab), "from": nice_date(seg[0]["date"], True), "to": nice_date(seg[-1]["date"], True),
                       "emoji": meta[top][1], "type": T(meta[top][0]), "color": meta[top][2],
                       "share": round(mix[top] * 100), "snow": round(snow * 100),
                       "cold": round((mix["neve"] + mix["freddo"]) * 100),
                       "best": nice_date(best["date"]) if snow >= .1 else "",
                       "t50": f"{st.mean(d['t50'] for d in seg):+.0f}".replace("+0", "0").replace("-0", "0"),
                       "flow": T(flows.most_common(1)[0][0]) if flows else "",
                       "conf": conf, "rows": rows, "agree": agree, "nmodels": len(rows),
                       "scen": round(st.mean(d["n"] for d in seg)),
                       "mix": [(T(meta[k][0]), meta[k][2], round(mix[k] * 100)) for k, *_ in TYPES if mix[k] >= .03]})
    tot = lambda d: d["mix"]["neve"] + d["mix"]["neve-alto"]
    first15 = days[:15]
    best = max(first15, key=tot)
    if tot(best) >= .3 and best["mix"]["neve"] >= best["mix"]["neve-alto"]:
        head = T("❄️ Il segnale più forte di neve fino alle stazioni: intorno a {d} ({p}% degli scenari)",
                 d=nice_date(best["date"]), p=round(tot(best) * 100))
    elif tot(best) >= .3:
        head = T("🌨️ Qualche chance di neve, soprattutto in quota, intorno a {d}", d=nice_date(best["date"]))
    else:
        head = T("☀️ Due settimane senza segnali seri di neve: quasi tutti gli scenari restano miti o asciutti")
    used = [(name, T(origin), col, round(st.mean(d["n"] for d in per_model[k])))
            for k, name, origin, col in MODELS if k in per_model]
    return {"head": head, "phases": phases, "chart": chart(days, per_model), "models": used,
            "nscen": sum(u[3] for u in used), "nmodels": len(used),
            "legend": [(T(lab), emo, col) for _, lab, emo, col in TYPES], "until": nice_date(days[-1]["date"])}
