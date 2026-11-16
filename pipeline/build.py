"""Costruisce il sito statico e l'API JSON a partire dai dati in data/raw/."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from compute import blend_point, ensemble_probs, name_configuration, synoptic_days
from text import location_text, nice_date, overview_text

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "site"


def load(name: str) -> dict:
    p = RAW / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else {}


def fmt_int(v, sign: bool = False) -> str:
    """Intero arrotondato, senza "-0"."""
    if v is None:
        return "–"
    n = round(v) or 0
    return f"{n:+d}" if sign else f"{n:d}"


def svg_snow_chart(points: list[dict], days: int = 10) -> str:
    """Barre di neve stimata per giorno, una barra per quota. SVG inline, niente JavaScript."""
    W, H, pad_l, pad_b, pad_t = 640, 200, 34, 34, 12
    cols = ["#9cc4e4", "#4f8fc0", "#1d4f7a"]
    dates = [r["date"] for r in points[0]["days"][:days]]
    vmax = max([5] + [r["snow_max"] for p in points for r in p["days"][:days]])
    vmax = (int(vmax / 5) + 1) * 5
    gw = (W - pad_l - 6) / max(1, len(dates))
    bw = min(16, (gw - 6) / len(points))
    y = lambda v: H - pad_b - (H - pad_b - pad_t) * v / vmax
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Neve stimata per giorno">']
    for k in range(0, vmax + 1, max(5, vmax // 4 // 5 * 5 or 5)):
        parts.append(f'<line x1="{pad_l}" x2="{W-4}" y1="{y(k):.1f}" y2="{y(k):.1f}" class="grid"/>'
                     f'<text x="{pad_l-6}" y="{y(k)+4:.1f}" class="ax" text-anchor="end">{k}</text>')
    for i, d in enumerate(dates):
        x0 = pad_l + i * gw + (gw - bw * len(points)) / 2
        for j, p in enumerate(points):
            r = next((r for r in p["days"] if r["date"] == d), None)
            if not r:
                continue
            x = x0 + j * bw
            # forbice tra modelli
            parts.append(f'<line x1="{x+bw/2:.1f}" x2="{x+bw/2:.1f}" y1="{y(r["snow_min"]):.1f}" '
                         f'y2="{y(r["snow_max"]):.1f}" class="range"/>')
            h = H - pad_b - y(r["snow"])
            parts.append(f'<rect x="{x+1:.1f}" y="{y(r["snow"]):.1f}" width="{bw-2:.1f}" height="{max(h,0):.1f}" '
                         f'fill="{cols[j % 3]}" rx="2"><title>{p["name"]} {nice_date(d, True)}: '
                         f'{r["snow"]:.0f} cm (forbice {r["snow_min"]:.0f}-{r["snow_max"]:.0f})</title></rect>')
        parts.append(f'<text x="{pad_l + i*gw + gw/2:.1f}" y="{H-14}" class="ax" text-anchor="middle">'
                     f'{nice_date(d, True)}</text>')
    parts.append('</svg>')
    return "".join(parts)


def main() -> None:
    cfg = json.loads((ROOT / "config" / "locations.json").read_text())
    site = json.loads((ROOT / "config" / "site.json").read_text())
    sponsors = json.loads((ROOT / "config" / "sponsors.json").read_text())
    webcams = json.loads((ROOT / "config" / "webcams.json").read_text())
    glob, lam, ens, syn = load("global"), load("lam"), load("ensemble"), load("synoptic")

    now = datetime.now(ZoneInfo("Europe/Rome"))
    today = now.date().isoformat()

    pts = {}
    for pid, meta in cfg["points"].items():
        if pid not in glob:
            continue
        days = blend_point(glob[pid], lam.get(pid), today)
        probs = ensemble_probs(ens[pid], today) if pid in ens else {}
        pts[pid] = {"id": pid, **meta, "days": days, "probs": probs}

    syn_rows = synoptic_days(syn, today) if syn else []
    for r in syn_rows:
        r["name"] = name_configuration(r)

    locs = []
    for loc in cfg["locations"]:
        if not all(p in pts for p in loc["points"]):
            continue
        L = dict(loc)
        L["text"] = location_text(loc, pts, syn_rows)
        L["pts"] = [pts[p] for p in loc["points"]]
        L["road"] = [pts[p] for p in loc.get("road_points", []) if p in pts]
        L["chart"] = svg_snow_chart(L["pts"])
        L["sponsors"] = sponsors.get(loc["slug"], []) or []
        L["webcams"] = webcams.get(loc["slug"], []) or []
        locs.append(L)

    ctx = {"site": site, "locs": locs, "syn": syn_rows, "overview": overview_text(locs) if locs else "",
           "updated": now.strftime("%d/%m/%Y %H:%M"), "updated_iso": now.isoformat(timespec="minutes"),
           "updated_rfc": now.strftime("%a, %d %b %Y %H:%M:%S %z"), "today": today, "sample": bool(int(__import__("os").environ.get("SAMPLE", "0"))), "nice_date": nice_date, "global_sponsors": sponsors.get("_global", [])}

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "api" / "v1").mkdir(parents=True)
    shutil.copytree(ROOT / "static", OUT / "static")

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "xml"]))
    env.globals.update(nice_date=nice_date)
    env.filters["n0"] = fmt_int

    explicit_index = bool(int(__import__("os").environ.get("EXPLICIT_INDEX", "0")))

    def render(tpl: str, path: str, **extra):
        dst = OUT / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        root = "../" * path.count("/") or "./"

        def u(p: str = "") -> str:
            if p.startswith("#"):
                return root + ("index.html" if explicit_index else "") + p
            if explicit_index and (p == "" or p.endswith("/")):
                p += "index.html"
            return root + p

        dst.write_text(env.get_template(tpl).render(**ctx, **extra, u=u))

    render("index.html", "index.html")
    for L in locs:
        render("location.html", f"{L['slug']}/index.html", loc=L)
    for page in ("metodo", "sponsor", "newsletter", "privacy"):
        render(f"{page}.html", f"{page}/index.html")
    render("feed.xml", "feed.xml")
    render("sitemap.xml", "sitemap.xml")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site['base_url']}/sitemap.xml\n")
    (OUT / "CNAME").write_text(site["base_url"].split("//")[1] + "\n")

    # API per la futura app
    api = {"generated": ctx["updated_iso"], "licence": "Dati elaborati da modelli open data; vedi /metodo/",
           "locations": [{"slug": L["slug"], "name": L["name"], "summary": L["text"],
                          "points": [{k: p[k] for k in ("id", "name", "lat", "lon", "elev", "days", "probs")}
                                     for p in L["pts"]]} for L in locs],
           "synoptic": syn_rows}
    (OUT / "api" / "v1" / "forecast.json").write_text(json.dumps(api, ensure_ascii=False))
    for L in api["locations"]:
        (OUT / "api" / "v1" / f"{L['slug']}.json").write_text(json.dumps(L, ensure_ascii=False))

    # stato per newsletter/allerte
    state = {"generated": ctx["updated_iso"],
             "alerts": [{"slug": L["slug"], "name": L["name"], "title": L["text"]["title"],
                         "snow3_top": L["text"]["snow3_top"]} for L in locs if L["text"]["level"] == "alert"],
             "overview": ctx["overview"]}
    (ROOT / "data" / "latest.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))
    print(f"sito generato: {len(locs)} località, {len(pts)} punti")


if __name__ == "__main__":
    main()
