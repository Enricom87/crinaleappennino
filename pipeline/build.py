"""Costruisce il sito statico e l'API JSON a partire dai dati in data/raw/."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from compute import blend_point, ensemble_probs, name_configuration, synoptic_days
from cards import cards
from summer import mountain_days, overview_mtn, summer_text
from i18n import T
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
    fb = T("forbice")
    y = lambda v: H - pad_b - (H - pad_b - pad_t) * v / vmax
    aria = T("Neve stimata per giorno")
    parts = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="{aria}">']
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
                         f'{r["snow"]:.0f} cm ({fb} {r["snow_min"]:.0f}-{r["snow_max"]:.0f})</title></rect>')
        parts.append(f'<text x="{pad_l + i*gw + gw/2:.1f}" y="{H-14}" class="ax" text-anchor="middle">'
                     f'{nice_date(d, True)}</text>')
    parts.append('</svg>')
    return "".join(parts)


def main() -> None:
    cfg = json.loads((ROOT / "config" / "locations.json").read_text())
    site = json.loads((ROOT / "config" / "site.json").read_text())
    from shop import merged_sponsors, offers
    sponsors = merged_sponsors()
    webcams = json.loads((ROOT / "config" / "webcams.json").read_text())
    local_sources = json.loads((ROOT / "config" / "local_sources.json").read_text())["sources"]
    glob, lam, ens, syn = load("global"), load("lam"), load("ensemble"), load("synoptic")

    now = datetime.now(ZoneInfo("Europe/Rome"))
    today = now.date().isoformat()
    IS_SUMMER = __import__("os").environ.get("SEASON", "") == "summer" or (
        __import__("os").environ.get("SEASON", "") != "winter" and now.month in range(5, 11))

    pts = {}
    for pid, meta in cfg["points"].items():
        if pid not in glob:
            continue
        days = blend_point(glob[pid], lam.get(pid), today, meta["elev"])
        probs = ensemble_probs(ens[pid], today, meta["elev"]) if pid in ens else {}
        pts[pid] = {"id": pid, **meta, "days": days, "probs": probs}

    syn_rows = synoptic_days(syn, today) if syn else []
    for r in syn_rows:
        r["name"] = name_configuration(r)

    import copy
    import i18n
    from i18n import HTML_LANG, LANGS, NAMES, T, set_lang
    from conditions import LABELS, profile_svg, route_conditions
    from routes import load_routes, to_gpx

    # dati indipendenti dalla lingua
    base_locs = [loc for loc in cfg["locations"] if all(p in pts for p in loc["points"])]
    mtn = {}
    for loc in base_locs:
        for pid in loc["points"]:
            if pid not in mtn:
                mtn[pid] = mountain_days(glob[pid], lam.get(pid), today)
    routes_cfg = json.loads((ROOT / "config" / "routes.json").read_text())
    base_routes = load_routes(routes_cfg)

    pcfg = json.loads((ROOT / "config" / "photos.json").read_text())
    pcred = {**json.loads((ROOT / "data" / "photos" / "credits.json").read_text())} \
        if (ROOT / "data" / "photos" / "credits.json").exists() else {}
    pcred.update(pcfg.get("own", {}))
    season = "estate" if IS_SUMMER else "inverno"

    def photo_for(slug: str):
        key = pcfg["locations"].get(slug, {}).get(season)
        has = key and ((ROOT / "data" / "photos" / f"{key}.jpg").exists() or (ROOT / "static" / "photos" / f"{key}.jpg").exists())
        return {"key": key, "credit": pcred.get(key, {}), "pos": pcfg["locations"].get(slug, {}).get("pos") or pcfg.get("positions", {}).get(key, "center 60%")} if has else None

    def build_lang():
        """Località e percorsi con i testi nella lingua corrente."""
        locs = []
        for loc in base_locs:
            L = dict(loc)
            L["intro"], L["area"] = T(loc.get("intro", "")), T(loc["area"])
            L["text"] = location_text(loc, pts, syn_rows)
            L["pts"] = [pts[p] for p in loc["points"]]
            L["road"] = [pts[p] for p in loc.get("road_points", []) if p in pts]
            L["chart"] = svg_snow_chart(L["pts"])
            top = max(L["pts"], key=lambda p: p["elev"])
            L["mtn_top"] = top
            L["mtn"] = mtn[top["id"]]
            L["mtn_text"] = summer_text(L["name"], top, L["mtn"])
            low = min(L["pts"], key=lambda p: p["elev"])
            L["low_pt"] = low
            L["cards_top"] = cards(top["days"], L["mtn"], today)
            L["cards_base"] = cards(low["days"], mtn[low["id"]], today) if low["id"] != top["id"] else []
            L["sponsors"] = sponsors.get(loc["slug"], []) or []
            L["webcams"] = [{**w, "label": T(w["label"])} for w in (webcams.get(loc["slug"], []) or [])]
            L["local"] = [{**src, "about": T(src["about"]),
                           "entries": [{**l, "label": T(l["label"])} for l in src["links"][loc["slug"]]]}
                          for src in local_sources if loc["slug"] in src["links"]]
            L["photo"] = photo_for(loc["slug"])
            locs.append(L)
        loc_by_slug = {L["slug"]: L for L in locs}
        routes = []
        for r0 in base_routes:
            L = loc_by_slug.get(r0["location"])
            if not L:
                continue
            r = dict(r0)
            r["name"], r["summary"] = T(r0["name"]), T(r0.get("summary", ""))
            r["loc_name"] = L["name"]
            r["cond"] = route_conditions(r, L["pts"] + L["road"], glob)
            r["profile"] = profile_svg(r)
            r["labels"] = [T(LABELS.get(a, a)) for a in r["activities"]]
            r["geojson_str"] = json.dumps(r["geojson"]["geometry"])
            m0 = (L["mtn"] or [None])[0]
            if m0 and m0["storm"] >= 2 and set(r["activities"]) & {"escursionismo", "trail-running", "mtb-gravel"}:
                when = T(": meglio rientrare entro le {h}", h=m0["back_by"]) if m0["back_by"] else ""
                r["cond"]["notes"].insert(0, T("Oggi temporali {lvl} nel pomeriggio in quota{when}. "
                                               "Lontano da creste e vette esposte al primo tuono.",
                                               lvl=T(m0["storm_label"]), when=when))
            routes.append(r)
        for L in locs:
            L["routes"] = [r for r in routes if r["location"] == L["slug"]]
        return locs, routes

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "api" / "v1").mkdir(parents=True)
    shutil.copytree(ROOT / "static", OUT / "static")
    # foto: originali 1600 px per le testate, miniature 640 px per le schede della home
    (OUT / "static" / "photos").mkdir(exist_ok=True)
    for f in (ROOT / "data" / "photos").glob("*.jpg"):
        shutil.copy(f, OUT / "static" / "photos" / f.name)
        try:
            from PIL import Image
            im = Image.open(f)
            im.thumbnail((640, 640))
            im.convert("RGB").save(OUT / "static" / "photos" / f"{f.stem}-640.jpg", quality=78)
        except Exception:
            shutil.copy(f, OUT / "static" / "photos" / f"{f.stem}-640.jpg")

    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=select_autoescape(["html", "xml"]))
    env.globals.update(nice_date=nice_date, t=T)
    env.filters["n0"] = fmt_int
    explicit_index = bool(int(__import__("os").environ.get("EXPLICIT_INDEX", "0")))
    SHARED = ("static/", "api/", "manifest.webmanifest", "sw.js", "feed.xml")
    prefix = lambda l: "" if l == "it" else f"{l}/"
    all_pages = []  # percorsi di pagina (senza lingua), per la sitemap

    it_ctx = None
    for lang in LANGS:
        set_lang(lang)
        locs, routes = build_lang()
        offers_l = [{**o, "name": T(o["name"]), "desc": T(o["desc"])} for o in offers()]
        ctx = {"site": {**site, "tagline": T(site["tagline"])}, "locs": locs, "home_photo": photo_for("_home"),
               "local_sources": [{**s, "about": T(s["about"]), "links": {k: [{**l, "label": T(l["label"])} for l in v]
                                                                       for k, v in s["links"].items()}}
                                 for s in local_sources],
               "routes": routes, "activity_labels": {k: T(v) for k, v in LABELS.items()}, "syn": syn_rows,
               "summer": IS_SUMMER,
               "overview": ((overview_mtn(locs) if IS_SUMMER else overview_text(locs)) if locs else ""),
               "updated": now.strftime("%d/%m/%Y %H:%M"), "updated_iso": now.isoformat(timespec="minutes"),
               "updated_rfc": now.strftime("%a, %d %b %Y %H:%M:%S %z"), "today": today,
               "sample": bool(int(__import__("os").environ.get("SAMPLE", "0"))),
               "global_sponsors": sponsors.get("_global", []), "offers": offers_l,
               "lang": lang, "html_lang": HTML_LANG[lang], "lang_names": NAMES, "langs": LANGS}
        if lang == "it":
            it_ctx = ctx

        def render(tpl: str, page: str, **extra):
            """page: percorso della pagina senza lingua, es. 'abetone/' o '' per la home."""
            path = prefix(lang) + page + "index.html"
            dst = OUT / path
            dst.parent.mkdir(parents=True, exist_ok=True)
            root = "../" * path.count("/")

            def link(p: str, l: str) -> str:
                if p.startswith("#"):
                    return root + prefix(l) + ("index.html" if explicit_index else "") + p
                if explicit_index and (p == "" or p.endswith("/")):
                    p += "index.html"
                return root + (p if p.startswith(SHARED) else prefix(l) + p) or "./"

            alt = [{"lang": l, "name": NAMES[l], "hreflang": HTML_LANG[l], "href": link(page, l),
                    "abs": f"{site['base_url']}/{prefix(l)}{page}"} for l in LANGS]
            name = f"{lang}/{tpl}" if lang != "it" and (ROOT / "templates" / lang / tpl).exists() else tpl
            dst.write_text(env.get_template(name).render(**ctx, **extra, u=lambda p="": link(p, lang),
                                                        alternates=alt, page=page))
            if lang == "it":
                all_pages.append(page)

        render("index.html", "")
        for L in locs:
            render("location.html", f"{L['slug']}/", loc=L)
        for pg in ("metodo", "sponsor", "newsletter", "privacy", "app", "offline"):
            render(f"{pg}.html", f"{pg}/")
        render("percorsi.html", "percorsi/")
        for r in routes:
            render("percorso.html", f"percorsi/{r['slug']}/", route=r)
            (OUT / prefix(lang) / "percorsi" / r["slug"] / f"{r['slug']}.gpx").write_text(to_gpx(r))

    set_lang("it")
    ctx = it_ctx
    locs, routes = ctx["locs"], ctx["routes"]
    ctx_x = {**ctx, "u": lambda p="": p}
    (OUT / "feed.xml").write_text(env.get_template("feed.xml").render(**ctx_x))
    (OUT / "sitemap.xml").write_text(env.get_template("sitemap.xml").render(
        **ctx_x, pages=[p for p in all_pages if p != "offline/"], prefixes=[prefix(l) for l in LANGS]))
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site['base_url']}/sitemap.xml\n")
    # app installabile (PWA): manifest e service worker alla radice del sito
    (OUT / "manifest.webmanifest").write_text(json.dumps({
        "name": f"{site['name']} · neve e meteo in quota", "short_name": site["name"],
        "description": site["tagline"], "lang": "it", "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": "#f6f9fb", "theme_color": "#0f2236",
        "icons": [{"src": "static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "static/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}],
        "shortcuts": [{"name": "Percorsi", "url": "percorsi/"}, {"name": "Allerta neve", "url": "newsletter/"}],
    }, ensure_ascii=False, indent=1))
    (OUT / "sw.js").write_text(env.get_template("sw.js").render(**ctx_x))
    (OUT / "CNAME").write_text(site["base_url"].split("//")[1] + "\n")

    # API per la futura app
    api = {"generated": ctx["updated_iso"], "licence": "Dati elaborati da modelli open data; vedi /metodo/",
           "locations": [{"slug": L["slug"], "name": L["name"], "summary": L["text"],
                          "mountain": {"point": L["mtn_top"]["id"], "days": L["mtn"], "text": L["mtn_text"]},
                          "points": [{k: p[k] for k in ("id", "name", "lat", "lon", "elev", "days", "probs")}
                                     for p in L["pts"]]} for L in locs],
           "synoptic": syn_rows}
    (OUT / "api" / "v1" / "forecast.json").write_text(json.dumps(api, ensure_ascii=False))
    (OUT / "api" / "v1" / "routes.json").write_text(json.dumps(
        {"generated": ctx["updated_iso"], "routes": [
            {k: r[k] for k in ("slug", "name", "location", "activities", "summary", "stats", "cond", "credit")}
            | {"cai": r.get("cai"), "difficulty": r.get("difficulty"), "geometry": r["geojson"]["geometry"]}
            for r in routes]}, ensure_ascii=False))
    for L in api["locations"]:
        (OUT / "api" / "v1" / f"{L['slug']}.json").write_text(json.dumps(L, ensure_ascii=False))

    # stato per newsletter/allerte
    state = {"generated": ctx["updated_iso"],
             "alerts": [{"slug": L["slug"], "name": L["name"], "title": L["text"]["title"],
                         "snow3_top": L["text"]["snow3_top"]} for L in locs if L["text"]["level"] == "alert"],
             "overview": ctx["overview"]}
    (ROOT / "data" / "latest.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))
    (ROOT / "data" / "i18n_missing.json").unlink(missing_ok=True)
    if i18n.MISSING:
        (ROOT / "data" / "i18n_missing.json").write_text(json.dumps(sorted(i18n.MISSING), ensure_ascii=False, indent=0))
        print(f"traduzioni mancanti: {len(i18n.MISSING)}")
    print(f"sito generato: {len(locs)} località, {len(pts)} punti, {len(LANGS)} lingue")


if __name__ == "__main__":
    main()
