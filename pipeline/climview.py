"""Vista dello storico delle stagioni invernali 1 dic – 31 mar (data/seasons.json) per pagine e località."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NORMAL = (1991, 2020)


def load() -> dict:
    try:
        return json.loads((ROOT / "data" / "seasons.json").read_text())
    except Exception:  # noqa: BLE001
        return {}


def _avg(rows, k):
    v = [r[k] for r in rows if r.get(k) is not None]
    return round(sum(v) / len(v), 1) if v else None


def chart(rows: list[dict], mean: float | None) -> str:
    """Barre della neve caduta per anno (SVG inline, nessuna libreria)."""
    if not rows:
        return ""
    rows = sorted(rows, key=lambda r: r["year"])
    w, h, pad = 720, 190, 26
    top = max(max(r["snow"] for r in rows), 1)
    bw = (w - pad) / len(rows)
    out = [f'<svg viewBox="0 0 {w} {h + 22}" class="clim-chart" role="img" aria-label="neve per stagione">']
    for i, r in enumerate(rows):
        bh = (h - 10) * r["snow"] / top
        x = pad + i * bw
        cls = "b part" if r.get("partial") else ("b xmas" if r.get("xmas") else "b")
        out.append(f'<rect class="{cls}" x="{x + 1:.1f}" y="{h - bh:.1f}" width="{bw - 2:.1f}" height="{bh:.1f}" rx="2">'
                   f'<title>{r["label"]}: {r["snow"]:.0f} cm</title></rect>')
        if r["year"] % 5 == 0 or i == len(rows) - 1:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{h + 16}" text-anchor="middle">{r["label"]}</text>')
    if mean:
        y = h - (h - 10) * mean / top
        out.append(f'<line x1="{pad}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}" class="mean"/>')
        out.append(f'<text x="{pad - 4}" y="{y + 4:.1f}" text-anchor="end">{mean:.0f}</text>')
    out.append(f'<text x="{pad - 4}" y="14" text-anchor="end">{top:.0f}</text></svg>')
    return "".join(out)


def view(slug: str, data: dict | None = None) -> dict | None:
    data = load() if data is None else data
    rec = data.get(slug)
    if not rec or len(rec.get("years", {})) < 5:
        return None
    rows = [{"year": int(y), "label": f"{y}/{(int(y) + 1) % 100:02d}", **v} for y, v in rec["years"].items()]
    full = [r for r in rows if not r.get("partial")]
    norm = [r for r in full if NORMAL[0] <= r["year"] <= NORMAL[1]] or full
    last10 = sorted(full, key=lambda r: r["year"])[-10:]
    keys = ("snow", "snow_days", "ice", "frost", "tmin", "tmean")
    mean = {k: _avg(norm, k) for k in keys}
    mean["months"] = {m: round(sum(r["months"][m] for r in norm) / len(norm), 1) for m in ("12", "01", "02", "03")}
    recent = {k: _avg(last10, k) for k in keys}
    rec_ = {
        "snow": max(full, key=lambda r: r["snow"]),
        "least": min(full, key=lambda r: r["snow"]),
        "cold": min(full, key=lambda r: r["tmin"]),
        "ice": max(full, key=lambda r: r["ice"]),
    }
    xmas = sum(1 for r in full if r.get("xmas"))
    return {
        "point": rec["point"], "elev": rec["elev"],
        "rows": sorted(rows, key=lambda r: -r["year"]),
        "mean": mean, "recent": recent, "records": rec_,
        "xmas": xmas, "n": len(full), "first": min(r["year"] for r in full),
        "last": max(r["year"] for r in full),
        "chart": chart(rows, mean["snow"]),
        "trend": None if not (mean["snow"] and recent["snow"]) else round(100 * (recent["snow"] / mean["snow"] - 1)),
    }
