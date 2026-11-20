"""Costruisce il sito statico e l'API JSON a partire dai dati in data/raw/."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

from compute import blend_point, ensemble_probs, hourly_point, name_configuration, synoptic_days, thermal_class, visibility_days
from cards import cards, hourly_strip
from summer import mountain_days, overview_mtn, summer_text
from i18n import T
from synview import syn_view
from teleconn import view as tele_view
from phasecard import decorate
from verdict import weekend
from extras import activities, events, snow_ground, places, avalanche
from bestpick import best_pick
from i18n import day_short
from articles import due as art_due_fn, compose as art_compose, save as art_save, load_all as art_load
from history import record as hist_record, view as hist_view
import verify
import runs as runs_mod
import engine_overlay
from seo import location_seo
from climview import load as clim_load, view as clim_view
from cards import prob_word


def trend_view():
    """Tendenza a 15 giorni; se i dati mancano o qualcosa va storto la sezione semplicemente non appare."""
    try:
        import trend
        return trend.view_dir(ROOT / "data" / "raw" / "ens_trend", datetime.now(ZoneInfo("Europe/Rome")).date().isoformat())
    except Exception as e:  # noqa: BLE001
        print("tendenza non calcolata:", e)
        return {}
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
        hours = hourly_point(glob[pid], lam.get(pid), now.strftime("%Y-%m-%dT%H:00"), meta["elev"])
        vis = visibility_days(hourly_point(glob[pid], lam.get(pid), today + "T00:00", meta["elev"], hours=24 * 5))
        for d in days:
            if d["date"] in vis:
                d["vis"] = vis[d["date"]]
        pts[pid] = {"id": pid, **meta, "days": days, "probs": probs, "hours": hours}

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
    import pro
    pro_notes = pro.apply(base_locs, pts)  # freno dei meteorologi LaMMA sulla quota neve
    # taratura imparata dagli errori passati e quota neve calcolata dal profilo verticale
    import calib
    import snowlevel
    CAL = calib.factors(calib.update(today))
    calib.apply(base_locs, pts, CAL)
    LEVELS = snowlevel.load()
    pid_off = {}
    for loc in base_locs:
        for pid in loc["points"]:
            pid_off.setdefault(pid, (CAL.get(loc["slug"]) or {}).get("level", 0))
    print(f"quota neve dal profilo: {len(LEVELS)} punti, {snowlevel.cap(pts, LEVELS, pid_off)} giorni-punto senza neve sotto quota")
    # primi 5 giorni dal motore fisico-statistico (appennino_engine.py): neve, pioggia, quota neve, raffiche
    import engine_overlay
    ENGINE_LOC = engine_overlay.apply(base_locs, pts, CAL, today)
    # grafico «configurazione»: giorni 1-5 dal motore (ICON-2I, AROME, ICON-CH2, ECMWF, GFS pesati per regime),
    # dal 6° la mediana pesata dei modelli a scenari (famiglie bilanciate); ECMWF grezzo solo se manca il resto
    TV = trend_view()
    _eng_t = engine_overlay.t850_days(today)
    _multi = (TV or {}).get("tmed", {})
    for r in syn_rows:
        base_r = r.get("ec") or r.get("gfs")
        if not base_r:
            continue
        t_new, src = (_eng_t.get(r["date"]), "engine") if r["date"] in _eng_t else (_multi.get(r["date"]), "multi")
        if t_new is None:
            continue
        r["mix"] = {**base_r, "t850": t_new, "thermal": thermal_class(t_new), "src": src}
    for pid, p in pts.items():  # quota neve del giorno su ogni punto, per dire «neve dai X m in su»
        for d in p["days"]:
            v = (LEVELS.get(pid) or {}).get(d["date"])
            if (d.get("engine") or {}).get("qn") is not None:
                d["lv"] = d["engine"]["qn"] + pid_off.get(pid, 0)
            elif v and v.get("wet"):
                d["lv"] = v.get("lv_min", v["lv"]) + pid_off.get(pid, 0)
            elif d.get("fl_min") is not None and (d.get("precip") or 0) >= 1:
                d["lv"] = d["fl_min"] - 300
    # una sola quota neve al giorno per tutto il crinale (mediana dei punti con precipitazione, media
    # pesata e non il minimo notturno): «dai X m» deve essere lo stesso numero all'Abetone e al Cimone
    _reg = {}
    for pid, p in pts.items():
        for d in p["days"]:
            v = (LEVELS.get(pid) or {}).get(d["date"])
            if (d.get("engine") or {}).get("qn") is not None:
                _reg.setdefault(d["date"], []).append(d["engine"]["qn"] + pid_off.get(pid, 0))
            elif v and v.get("wet"):
                _reg.setdefault(d["date"], []).append(v["lv"] + pid_off.get(pid, 0))
            elif d.get("lv") is not None:
                _reg.setdefault(d["date"], []).append(d["lv"])
    _reg = {k: sorted(x)[len(x) // 2] for k, x in _reg.items() if len(x) >= 3}
    tops = {max(loc["points"], key=lambda q: pts[q]["elev"] if q in pts else 0) for loc in base_locs}
    for k in list(_reg):  # se una vetta prende neve vera quel giorno, «dai X m» non può stare sopra quella vetta
        snowy = [pts[q]["elev"] for q in tops if q in pts
                 for d in pts[q]["days"] if d["date"] == k and (d.get("snow") or 0) >= 2]
        if snowy:
            _reg[k] = min(_reg[k], min(snowy) - 100)
    REG_LV = dict(_reg)
    for p in pts.values():
        for d in p["days"]:
            if d["date"] in _reg:
                d["lv"] = _reg[d["date"]]
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

    lifts_cfg = json.loads((ROOT / "config" / "lifts.json").read_text()) if (ROOT / "config" / "lifts.json").exists() else {}
    lifts_data = json.loads((ROOT / "data" / "lifts.json").read_text()) if (ROOT / "data" / "lifts.json").exists() else {}

    def lifts_for(slug: str):
        """Stato impianti e piste della località, dai siti ufficiali (vedi pipeline/lifts.py)."""
        c = lifts_cfg.get("locations", {}).get(slug)
        if not c:
            return None
        if "link" in c:
            return {"link": c["link"], "name": c["name"]}
        d = lifts_data.get(c["source"])
        if not d:
            return {"link": lifts_cfg["sources"][c["source"]]["lifts"], "name": lifts_cfg["sources"][c["source"]]["name"]}
        areas = set(c.get("areas", []))
        pick = lambda xs: [x for x in xs if not areas or x["area"] in areas]
        L, S = pick(d["lifts"]), pick(d.get("slopes", []))
        age_h = (now - datetime.fromisoformat(d["fetched"])).total_seconds() / 3600
        upd = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", d.get("updated") or "")
        if upd:
            ud = datetime(int(upd[3]), int(upd[2]), int(upd[1]), tzinfo=now.tzinfo)
            if (now - ud).days > 3:  # il gestore non aggiorna da giorni (stagione chiusa): niente numeri, solo il link
                src = lifts_cfg["sources"][c["source"]]
                return {"link": src["lifts"], "name": src["name"], "off": True}
        return {"name": d["name"], "url": d["url"], "updated": d.get("updated") or "", "fetched": d["fetched"],
                "stale": age_h > 36, "open": sum(x["open"] for x in L), "total": len(L),
                "slopes_open": sum(x["open"] for x in S), "slopes_total": len(S),
                "lifts": sorted(L, key=lambda x: (not x["open"], x["area"], x["name"])), "multi_area": len(areas) > 1}

    def home_events(locs):
        seen, out = set(), []
        for L in locs:
            for e in L["events"]["list"]:
                if e["id"] not in seen:
                    seen.add(e["id"]); out.append({**e, "near": L["name"].split(" · ")[0], "near_url": L["slug"]})
        out.sort(key=lambda e: (max(e["from"], today), e["km"]))
        src = next((L["events"]["source"] for L in locs if L["events"]["source"]), None)
        return {"list": out[:6], "source": src}

    ROADS = json.loads((ROOT / "config" / "roads.json").read_text())

    def build_lang():
        """Località e percorsi con i testi nella lingua corrente."""
        locs = []
        for loc in base_locs:
            L = dict(loc)
            L["intro"], L["area"] = T(loc.get("intro", "")), T(loc["area"])
            L["text"] = location_text(loc, pts, syn_rows)
            L["pts"] = [pts[p] for p in loc["points"]]
            L["engine"] = [{**e, "name": day_short(e["date"])} for e in ENGINE_LOC.get(loc["slug"], [])]
            # numeri della card in home: tutti dal motore (una sola fonte), quota neve = quella dei titoli
            _e = L["engine"]
            _first = next((e for e in _e if (e["top"] or 0) >= 1), None)
            _z = REG_LV.get(_first["date"]) if _first else None
            L["stats"] = {"top": round(sum(e["top"] or 0 for e in _e)) if _e else None,
                          "qn": (min(int(round(_z / 100.0) * 100), int(max(p["elev"] for p in L["pts"]) // 100 * 100)) if _z else None),
                          "gust": max((e["gust"] or 0) for e in _e) if _e else None,
                          "q": engine_overlay.QUALITY.get(loc["slug"])}
            _top = max(L["pts"], key=lambda p: p["elev"])
            _vis = {d["date"]: d.get("vis") for d in _top["days"]}
            for e in L["engine"]:
                e["vis"] = _vis.get(e["date"])
            _vnext = [v for d, v in sorted(_vis.items()) if d >= today and v][:2]
            L["stats"]["vis"] = ("nebbia" if "nebbia" in _vnext else ("variabile" if "variabile" in _vnext else
                                 ("ottima" if _vnext else None)))
            L["roadsnow"] = [{"date": d, "name": day_short(d)} for d in engine_overlay.ROADS.get(loc["slug"], [])]
            if L["stats"]["q"]:
                L["stats"]["q"] = {**L["stats"]["q"], "label": T(L["stats"]["q"]["label"])}
            L["road"] = [pts[p] for p in loc.get("road_points", []) if p in pts]
            L["chart"] = svg_snow_chart(L["pts"])
            top = max(L["pts"], key=lambda p: p["elev"])
            L["mtn_top"] = top
            L["mtn"] = mtn[top["id"]]
            L["mtn_text"] = summer_text(L["name"], top, L["mtn"])
            low = min(L["pts"], key=lambda p: p["elev"])
            L["low_pt"] = low
            L["cards_top"] = cards(top["days"], L["mtn"], today)
            L["hours_top"] = hourly_strip(top.get("hours", []))
            L["hours_base"] = hourly_strip(low.get("hours", [])) if low["id"] != top["id"] else []
            L["cards_base"] = cards(low["days"], mtn[low["id"]], today) if low["id"] != top["id"] else []
            # schede della home: la neve si mostra dove si scia (punto basso); se nevica solo più su si dice
            # «dai X m», uguale per tutte le località, invece dei cm in vetta (vette di altezze diverse)
            home = []
            top_by = {c["date"]: c for c in L["cards_top"]}
            lv_by = {d["date"]: d.get("lv") for d in top["days"]}
            for c in (L["cards_base"] or L["cards_top"]):
                c = dict(c)
                t = top_by.get(c["date"]) or {}
                if c["snow"] < 1 and (t.get("snow") or 0) >= 1:
                    lv = lv_by.get(c["date"]) or (low["elev"] + top["elev"]) / 2
                    z = int(round(min(max(lv, 500), top["elev"] - 100) / 100) * 100)
                    c.update(icon="snow", zq=z, phrase=T("Neve in quota, dai {z} m in su", z=z))
                home.append(c)
            L["cards_home"] = home
            L["sponsors"] = sponsors.get(loc["slug"], []) or []
            L["webcams"] = [{**w, "label": T(w["label"])} for w in (webcams.get(loc["slug"], []) or [])]
            L["local"] = [{**src, "about": T(src["about"]),
                           "entries": [{**l, "label": T(l["label"])} for l in src["links"][loc["slug"]]]}
                          for src in local_sources if loc["slug"] in src["links"]]
            L["photo"] = photo_for(loc["slug"])
            L["liftinfo"] = lifts_for(loc["slug"])
            L["weekend"] = weekend(L, today, IS_SUMMER)
            li = L["liftinfo"] or {}
            L["ground"] = None if IS_SUMMER else snow_ground(loc, pts)
            has_snow = not IS_SUMMER and ((li.get("open") or 0) > 0 or (L["text"].get("snow3_top") or 0) >= 3
                                          or (L["ground"] or {}).get("cm", 0) >= 10)
            L["extras"] = activities(loc, pts, IS_SUMMER, L["weekend"], has_snow)
            L["events"] = events(loc, pts, today)
            L["places"] = places(loc, pts)
            L["aval"] = None if IS_SUMMER else avalanche(loc)
            L["roadrule"] = None if IS_SUMMER else ROADS.get(loc["slug"], [])
            zd = (pro.load().get("zones") or {}).get(pro.ZONE_FOR.get(loc["slug"], ""))
            L["snowline"] = None if IS_SUMMER else pro.snowline(loc, pts, today, zd, levels=LEVELS,
                                                                     offset=(CAL.get(loc["slug"]) or {}).get("level", 0))
            # una sola quota neve per giorno su tutta la pagina: quella dei titoli (REG_LV) dove c'è
            for x in (L["snowline"] or []):
                if x["date"] in REG_LV and not x["dry"]:
                    x["lv"], x["late"] = int(round(REG_LV[x["date"]] / 100) * 100), None
            for e in L["engine"]:
                if e["date"] in REG_LV and e.get("qn") is not None:
                    e["qn"] = REG_LV[e["date"]]
            L["seo"] = location_seo(L, site, IS_SUMMER)
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
    import hashlib
    css_v = hashlib.md5((ROOT / "static" / "style.css").read_bytes()).hexdigest()[:8]
    env.globals.update(nice_date=nice_date, t=T, css_v=css_v, prob_word=prob_word)
    env.filters["n0"] = fmt_int
    explicit_index = bool(int(__import__("os").environ.get("EXPLICIT_INDEX", "0")))
    SHARED = ("static/", "api/", "manifest.webmanifest", "sw.js", "feed.xml")
    prefix = lambda l: "" if l == "it" else f"{l}/"
    all_pages = []  # percorsi di pagina (senza lingua), per la sitemap

    it_ctx = None
    CLIM = clim_load()
    art_due = art_due_fn(today)
    bot_feed = {}  # dati per il bot Telegram (avvisi personali), in tutte le lingue
    for lang in LANGS:
        set_lang(lang)
        locs, routes = build_lang()
        if lang == LANGS[0]:
            hist_record(locs, today)
            if not IS_SUMMER:
                verify.record(locs, today)
        for L in locs:
            L["history"] = None if IS_SUMMER else hist_view(L, today)
            L["calib"] = None if IS_SUMMER else (CAL.get(L["slug"]) or {"snow": 1.0, "n_snow": 0, "level": 0, "n_level": 0})
            L["clim"] = clim_view(L["slug"], CLIM)
        for L in locs:
            wk = L.get("weekend")
            f = bot_feed.setdefault(L["slug"], {"slug": L["slug"], "level": L["text"]["level"],
                                                "snow3_top": L["text"]["snow3_top"],
                                                "ground": (L.get("ground") or {}).get("cm"),
                                                "wk_color": wk["color"] if wk else None,
                                                "wk_sure": wk["sure"]["key"] if wk else None, "i18n": {}})
            f["i18n"][lang] = {"name": L["name"], "title": L["text"]["title"],
                               "wk_title": wk["title"] if wk else "", "wk_advice": wk["advice"] if wk else "",
                               "wk_days": [f"{d['name']}: {d['why']}" for d in wk["days"]] if wk else [],
                               "url": "https://crinaleappennino.it/" + ("" if lang == "it" else lang + "/") + L["slug"] + "/"}
        offers_l = [{**o, "name": T(o["name"]), "desc": T(o["desc"])} for o in offers()]
        ctx = {"site": {**site, "tagline": T(site["tagline"])}, "locs": locs, "home_photo": photo_for("_home"),
               "local_sources": [{**s, "about": T(s["about"]), "links": {k: [{**l, "label": T(l["label"])} for l in v]
                                                                       for k, v in s["links"].items()}}
                                 for s in local_sources],
               "routes": routes, "activity_labels": {k: T(v) for k, v in LABELS.items()}, "syn": syn_rows, "synv": syn_view(syn_rows, REG_LV, min(L["low_pt"]["elev"] for L in locs if L["low_pt"]["elev"] <= 1600)), "trendv": decorate(trend_view(), locs, ENGINE_LOC, REG_LV), "telev": tele_view(today),
               "summer": IS_SUMMER, "home_events": home_events(locs), "bestpick": best_pick(locs, IS_SUMMER),
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

        if art_due:
            a = art_compose(ctx["trendv"], ctx["synv"], ctx["bestpick"], today, locs, ctx.get("telev"))
            if a:
                art_save(lang, a)
        articles = art_load(lang)
        ctx["articles"] = articles
        pg = verify.scores(today)
        names = {L["slug"]: L["name"] for L in locs}
        for e in pg["events"]:
            e["name"] = names.get(e["slug"], e["slug"])
            e["day"] = day_short(e["date"])
        ctx["pagella"] = pg
        # prossime ore per la pagina radar: base e vetta di ogni località, dal calcolo di questo giro
        nowc = []
        for L in locs:
            lo, tp = L["low_pt"], L["mtn_top"]
            def nxt(pt, h):
                hs = [x for x in (pt.get("hours") or []) if x["time"] >= now.strftime("%Y-%m-%dT%H:00")][:h]
                return {"snow": round(sum(x["snow"] for x in hs), 1), "rain": round(sum(x["rain"] for x in hs), 1),
                        "t": hs[0]["t"] if hs else None}
            nowc.append({"slug": L["slug"], "name": L["name"].split(" · ")[0], "lat": lo["lat"], "lon": lo["lon"],
                         "low": {"name": lo["name"], "elev": lo["elev"], "h3": nxt(lo, 3), "h6": nxt(lo, 6)},
                         "top": {"name": tp["name"], "elev": tp["elev"], "h3": nxt(tp, 3), "h6": nxt(tp, 6)}})
        ctx["nowcast"] = nowc
        ctx["runs"] = runs_mod.view(now)
        render("index.html", "")
        render("tendenze.html", "tendenze/")
        for a in articles:
            render("articolo.html", f"tendenze/{a['date']}/", art=a)
        for L in locs:
            render("location.html", f"{L['slug']}/", loc=L)
        for pg in ("metodo", "sponsor", "newsletter", "privacy", "app", "offline", "segnala", "segnala-neve", "inverni", "come-funziona", "pagella", "radar", "widget"):
            render(f"{pg}.html", f"{pg}/")
        if lang == "it":  # widget incorporabili (in italiano): un file per località, aggiornato a ogni giro
            (OUT / "widget").mkdir(parents=True, exist_ok=True)
            for L in locs:
                (OUT / "widget" / f"{L['slug']}.html").write_text(
                    env.get_template("widget_loc.html").render(**ctx, L=L))
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
        **ctx_x, pages=[p for p in all_pages if p != "offline/"], prefixes=[prefix(l) for l in LANGS],
        lastmod=now.isoformat(timespec="seconds")))
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
                          "points": [{k: p[k] for k in ("id", "name", "lat", "lon", "elev", "days", "probs", "hours") if k in p}
                                     for p in L["pts"]]} for L in locs],
           "synoptic": syn_rows}
    (OUT / "api" / "v1" / "forecast.json").write_text(json.dumps(api, ensure_ascii=False))
    _eng = ROOT / "data" / "raw" / "engine.json"
    if _eng.exists():  # uscita del motore fisico, formato colonnare schema 2.0
        (OUT / "api" / "v2").mkdir(parents=True, exist_ok=True)
        shutil.copy(_eng, OUT / "api" / "v2" / "crinale.json")
    (OUT / "api" / "v1" / "routes.json").write_text(json.dumps(
        {"generated": ctx["updated_iso"], "routes": [
            {k: r[k] for k in ("slug", "name", "location", "activities", "summary", "stats", "cond", "credit")}
            | {"cai": r.get("cai"), "difficulty": r.get("difficulty"), "geometry": r["geojson"]["geometry"]}
            for r in routes]}, ensure_ascii=False))
    for L in api["locations"]:
        (OUT / "api" / "v1" / f"{L['slug']}.json").write_text(json.dumps(L, ensure_ascii=False))

    (OUT / "api" / "v1" / "bot.json").write_text(json.dumps(
        {"generated": ctx["updated_iso"], "summer": IS_SUMMER, "locs": list(bot_feed.values())}, ensure_ascii=False))

    # stato per newsletter/allerte
    state = {"generated": ctx["updated_iso"],
             "alerts": [{"slug": L["slug"], "name": L["name"], "title": L["text"]["title"],
                         "snow3_top": L["text"]["snow3_top"]} for L in locs if L["text"]["level"] == "alert"],
             "overview": ctx["overview"], "summer": IS_SUMMER,
             "locs": [{"slug": L["slug"], "name": L["name"], "title": L["text"]["title"], "level": L["text"]["level"],
                       "snow3_top": L["text"]["snow3_top"],
                       "verdict": (L["mtn"] or [{}])[0].get("verdict_label"),
                       "back_by": (L["mtn"] or [{}])[0].get("back_by"),
                       "weekend": L.get("weekend"), "region": L.get("region")} for L in locs],
             "bestpick": ctx.get("bestpick"),
             # neve prevista nelle prossime 48 ore su qualsiasi punto: decide gli aggiornamenti leggeri ogni 3 ore
             "snow48": round(max([d.get("snow") or 0 for p in pts.values() for d in p["days"] if d["idx"] <= 1] or [0]), 1),
             "phases": [{"label": p["label"], "from": p["from"], "to": p["to"], "card": p.get("card"),
                         "snow": p["snow"], "snow_low": p.get("snow_low", 0), "cold": p.get("cold_tail") or 0}
                        for p in ((ctx.get("trendv") or {}).get("phases") or [])],
             "article": (lambda a: {"title": a["title"], "brief": a.get("brief", []), "date": a["date"]}
                         if a else None)((ctx.get("articles") or [None])[0])}
    (ROOT / "data" / "latest.json").write_text(json.dumps(state, ensure_ascii=False, indent=1))
    (ROOT / "data" / "i18n_missing.json").unlink(missing_ok=True)
    if i18n.MISSING:
        (ROOT / "data" / "i18n_missing.json").write_text(json.dumps(sorted(i18n.MISSING), ensure_ascii=False, indent=0))
        print(f"traduzioni mancanti: {len(i18n.MISSING)}")
    print(f"sito generato: {len(locs)} località, {len(pts)} punti, {len(LANGS)} lingue")


if __name__ == "__main__":
    main()
