"""Quota neve calcolata dal profilo verticale previsto (925, 850, 700 hPa: temperatura, umidità, quota).

Per ogni ora e modello calcoliamo la temperatura di bulbo umido a ogni livello: è la temperatura che l'aria
raggiunge quando la precipitazione evapora e la raffredda, ed è quella che decide se un fiocco arriva a terra
come neve. La quota neve è dove il bulbo umido scende a +1 °C (sotto quella quota i fiocchi fondono quasi
tutti). Rispetto a «zero termico − 300 m» tiene conto dell'aria secca, che con le precipitazioni si raffredda
e abbassa la neve, e dell'aria satura, che la tiene alta.

Giorno per giorno: media pesata sulle ore con precipitazione (se non piove, minima del giorno).
Modelli: ICON-2I (primi 3 giorni, peso doppio), ECMWF IFS, ICON globale."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEVELS = (925, 850, 700)
MODELS = {"italia_meteo_arpae_icon_2i": 2.0, "meteofrance_arome_france": 2.0, "ecmwf_ifs025": 1.0, "icon_global": 1.0}
TW_SNOW = 1.0  # °C di bulbo umido
VARS = ",".join(f"{v}_{p}hPa" for p in LEVELS for v in ("temperature", "relative_humidity", "geopotential_height")) \
    + ",precipitation"


def wet_bulb(t: float, rh: float) -> float:
    """Formula di Stull (2011), valida tra −20 e +50 °C e umidità 5–99 %."""
    rh = min(max(rh, 5.0), 99.0)
    return (t * math.atan(0.151977 * math.sqrt(rh + 8.313659)) + math.atan(t + rh) - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh) - 4.686035)


def level_from(prof: list[tuple[float, float]]) -> float | None:
    """prof = [(quota m, bulbo umido °C)] dal basso; quota dove il bulbo umido vale TW_SNOW."""
    prof = sorted(p for p in prof if p[0] is not None and p[1] is not None)
    if len(prof) < 2:
        return None
    if prof[0][1] <= TW_SNOW:  # già sotto soglia al livello più basso: estrapolo verso il basso (≈ 5 °C/km)
        return max(200.0, prof[0][0] - (TW_SNOW - prof[0][1]) / 0.005)
    for (z1, w1), (z2, w2) in zip(prof, prof[1:]):
        if w1 > TW_SNOW >= w2:
            return z1 + (z2 - z1) * (w1 - TW_SNOW) / (w1 - w2)
    return 3500.0  # caldo fino a 3000 m: niente neve sull'Appennino


def daily(raw_point: dict) -> dict[str, dict]:
    """{data: {"lv": quota neve m, "wet": piove/nevica?}} per un punto."""
    h = raw_point.get("hourly", {})
    times = h.get("time", [])
    acc: dict[str, list] = defaultdict(list)  # data -> [(quota, peso)]
    dry: dict[str, list] = defaultdict(list)
    for m, w in MODELS.items():
        for i, ts in enumerate(times):
            prof = []
            for p in LEVELS:
                try:
                    t = h[f"temperature_{p}hPa_{m}"][i]
                    rh = h[f"relative_humidity_{p}hPa_{m}"][i]
                    z = h[f"geopotential_height_{p}hPa_{m}"][i]
                except (KeyError, IndexError):
                    t = None
                if t is None or rh is None or z is None:
                    continue
                prof.append((z, wet_bulb(t, rh)))
            lv = level_from(prof)
            if lv is None:
                continue
            pr = (h.get(f"precipitation_{m}") or [None] * len(times))[i] or 0
            if pr >= 0.2:
                acc[ts[:10]].append((lv, w * pr))
            dry[ts[:10]].append(lv)
    out = {}
    wet_h: dict[str, list] = defaultdict(list)  # (ora, quota) media dei modelli per ora, solo ore con precipitazione
    by_h: dict[str, list] = defaultdict(list)
    for m, w in MODELS.items():
        for i, ts in enumerate(times):
            pr = (h.get(f"precipitation_{m}") or [None] * len(times))[i] or 0
            prof = []
            for p in LEVELS:
                try:
                    t, rh, z = (h[f"temperature_{p}hPa_{m}"][i], h[f"relative_humidity_{p}hPa_{m}"][i],
                                h[f"geopotential_height_{p}hPa_{m}"][i])
                except (KeyError, IndexError):
                    continue
                if None not in (t, rh, z):
                    prof.append((z, wet_bulb(t, rh)))
            lv = level_from(prof)
            if lv is not None and pr >= 0.2:
                by_h[ts].append(lv)
    for ts in sorted(by_h):
        wet_h[ts[:10]].append(sum(by_h[ts]) / len(by_h[ts]))
    for d in sorted(set(acc) | set(dry)):
        if acc.get(d) and sum(x[1] for x in acc[d]) >= 0.5:
            tot = sum(x[1] for x in acc[d])
            seq = wet_h.get(d) or [sum(x[0] * x[1] for x in acc[d]) / tot]
            out[d] = {"lv": round(sum(x[0] * x[1] for x in acc[d]) / tot), "wet": True,
                      "lv_min": round(min(seq)), "lv_first": round(seq[0]), "lv_last": round(seq[-1])}
        elif dry.get(d):
            out[d] = {"lv": round(min(dry[d])), "wet": False}
    return out


def load() -> dict[str, dict]:
    try:
        raw = json.loads((ROOT / "data" / "raw" / "profile.json").read_text())
    except Exception:  # noqa: BLE001
        return {}
    return {pid: daily(r) for pid, r in raw.items()}


def cap(pts: dict, levels: dict, offsets: dict | None = None, margin: int = 200) -> int:
    """Toglie la neve prevista nei punti che stanno ben sotto la quota neve del giorno (es. Le Polle quando
    nevica solo sul Cimone). Ritorna quanti giorni-punto sono stati corretti."""
    n = 0
    for pid, p in pts.items():
        lv_by = levels.get(pid) or {}
        offset = (offsets or {}).get(pid, 0)
        for d in p["days"]:
            v = lv_by.get(d["date"])
            if not v or not v["wet"]:
                continue
            # prudente: si toglie la neve solo se il punto resta sotto la quota neve in TUTTE le ore con
            # precipitazione (con un fronte freddo la quota può crollare in serata)
            lv = v.get("lv_min", v["lv"]) + offset
            if p["elev"] < lv - margin and (d.get("snow") or 0) > 0:
                d.setdefault("snow_model", d["snow"])
                for k in ("snow", "snow_min", "snow_max"):
                    if k in d:
                        d[k] = 0.0
                d["level_capped"] = round(lv)
                n += 1
        for hr in p.get("hours", []):
            v = lv_by.get(hr["time"][:10])
            if v and v["wet"] and p["elev"] < v.get("lv_min", v["lv"]) + offset - margin and hr.get("snow"):
                hr["snow"] = 0.0
    return n
