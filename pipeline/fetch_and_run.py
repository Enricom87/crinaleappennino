#!/usr/bin/env python3
"""
fetch_and_run.py — scarica le previsioni Open-Meteo per le 11 località di
crinaleappennino.it, le elabora con ``appennino_engine`` e scrive
``output_crinale_v2.json`` per il frontend.

Uso:
    python3 fetch_and_run.py                       # tutte le località
    python3 fetch_and_run.py --localita abetone cimone
    python3 fetch_and_run.py --giorni 4 --out public/data/output_crinale_v2.json
    python3 fetch_and_run.py --offline             # pipeline completa su dati sintetici

Dipendenze: solo libreria standard + appennino_engine.py nella stessa cartella.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

import appennino_engine as eng

logger = logging.getLogger("fetch_and_run")

API_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 120  # Open-Meteo gratuito a volte risponde in 40-60 s
MAX_TENTATIVI = 3
PAUSA_TRA_LOCALITA_S = 1.0
USER_AGENT = "crinaleappennino.it/2.0 (+https://crinaleappennino.it)"

# Scarto massimo accettato tra quota DEM restituita da Open-Meteo e quota_base:
# oltre questa soglia le coordinate probabilmente non puntano alla stazione.
TOLLERANZA_QUOTA_M = 120

# Coordinate del punto "quota base" (stazione/partenza impianti) di ogni località.
# Tutte da fonte pubblica (vedi "fonte"). Il controllo automatico sulla quota DEM
# restituita da Open-Meteo segnala comunque scostamenti > TOLLERANZA_QUOTA_M.
COORDINATE: dict[str, dict[str, Any]] = {
    "abetone":          {"lat": 44.1456, "lon": 10.6653, "verificata": True,  "fonte": "Passo dell'Abetone (1388 m; DEM Open-Meteo 1380 m)"},
    "cimone":           {"lat": 44.2148, "lon": 10.7201, "verificata": True,  "fonte": "OSM node 1781307725 (Passo del Lupo, ~1550 m)"},
    "le_polle":         {"lat": 44.2158, "lon": 10.6903, "verificata": True,  "fonte": "Wikidata Q3828408 (Le Polle, 1280 m)"},
    "cimoncino":        {"lat": 44.1983, "lon": 10.7312, "verificata": True,  "fonte": "OSM node 752891918 (stazione Cimoncino; Rif. Zambelli 1423 m)"},
    "doganaccia":       {"lat": 44.1207, "lon": 10.7732, "verificata": True,  "fonte": "italia-italy.org"},
    "corno_alle_scale": {"lat": 44.1331, "lon": 10.8216, "verificata": True,  "fonte": "OSM way 182598726 (Laghetto del Cavone, 1415 m)"},
    "lago_scaffaiolo":  {"lat": 44.1186, "lon": 10.8077, "verificata": True,  "fonte": "Wikipedia/Sygic 44°7'6.9\"N 10°48'27.7\"E"},
    "lago_santo":       {"lat": 44.1365, "lon": 10.5859, "verificata": True,  "fonte": "Wikipedia (Lago Santo modenese)"},
    "garfagnana":       {"lat": 44.2059, "lon": 10.4494, "verificata": True,  "fonte": "TuttoCittà/ISTAT (Casone di Profecchia, ~1305-1320 m)"},
    "cerreto_laghi":    {"lat": 44.2982, "lon": 10.2433, "verificata": True,  "fonte": "GeoNames 9035438 (DEM 1346 m)"},
    "febbio":           {"lat": 44.2997, "lon": 10.4310, "verificata": True,  "fonte": "ARPAE, oss. Zambonini via Rescadore"},
}

assert set(COORDINATE) == set(eng.LOCALITA_CONFIG), "COORDINATE e LOCALITA_CONFIG non allineati"


# =============================================================================
# HTTP con retry
# =============================================================================


class ErroreApi(Exception):
    """Errore definitivo (non ritentabile) restituito da Open-Meteo."""


def _get_json(params: dict[str, str]) -> dict[str, Any]:
    """GET con retry esponenziale su timeout, 429 e 5xx. Rispetta ``Retry-After``."""
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    ultimo_errore: Optional[Exception] = None

    for tentativo in range(1, MAX_TENTATIVI + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", errors="replace")
            if e.code == 400:
                try:
                    motivo = json.loads(corpo).get("reason", corpo)
                except json.JSONDecodeError:
                    motivo = corpo
                raise ErroreApi(f"HTTP 400: {motivo}") from e
            if e.code not in (429, 500, 502, 503, 504):
                raise ErroreApi(f"HTTP {e.code}: {corpo[:200]}") from e
            ultimo_errore = e
            retry_after = e.headers.get("Retry-After") if e.headers else None
            attesa = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** tentativo
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            ultimo_errore = e
            attesa = 2 ** tentativo
        if tentativo < MAX_TENTATIVI:
            attesa = min(attesa, 60) + random.uniform(0, 0.5)
            logger.warning("Tentativo %d/%d fallito (%s): riprovo tra %.1f s",
                           tentativo, MAX_TENTATIVI, ultimo_errore, attesa)
            time.sleep(attesa)

    raise ErroreApi(f"Open-Meteo non raggiungibile dopo {MAX_TENTATIVI} tentativi: {ultimo_errore}")


def scarica_localita(codice: str, giorni: int) -> tuple[Any, list[str]]:
    """Scarica i dati di una località.

    Prima prova la richiesta multi-modello unica. Se Open-Meteo risponde 400
    (es. un identificativo di modello non accettato) ripiega su una richiesta
    per modello, così un modello problematico non blocca gli altri.

    Returns:
        (dati per ``elabora_localita``, elenco avvisi)
    """
    c = COORDINATE[codice]
    avvisi: list[str] = []
    params = eng.costruisci_parametri_richiesta(c["lat"], c["lon"], giorni=giorni)
    try:
        return _get_json(params), avvisi
    except ErroreApi as e:
        if "HTTP 400" not in str(e):
            raise
        avvisi.append(f"richiesta multi-modello rifiutata ({e}); ripiego modello per modello")
        logger.warning("%s: %s", codice, avvisi[-1])

    per_modello: dict[str, Any] = {}
    for modello in eng.MODELLI_OPEN_METEO:
        p = eng.costruisci_parametri_richiesta(c["lat"], c["lon"], modelli=[modello], giorni=giorni)
        try:
            per_modello[modello] = _get_json(p)
        except ErroreApi as e:
            avvisi.append(f"modello {modello} escluso: {e}")
            logger.warning("%s: %s", codice, avvisi[-1])
        time.sleep(0.3)
    if not per_modello:
        raise ErroreApi("nessun modello disponibile")
    return per_modello, avvisi


def _elevazione_risposta(dati: Any) -> Optional[float]:
    if isinstance(dati, dict) and "elevation" in dati:
        return dati.get("elevation")
    if isinstance(dati, dict):
        for r in dati.values():
            if isinstance(r, dict) and r.get("elevation") is not None:
                return r["elevation"]
    return None


# =============================================================================
# Pipeline
# =============================================================================


CAMPI_ORARI_DIAGNOSTICI: tuple[str, ...] = ("pesi", "pesi_termici")
LIMITE_KB = 200


def snellisci(out: dict[str, Any], con_pesi: bool) -> None:
    """Toglie dai record orari i campi diagnostici e quelli ripetuti ogni ora.

    * ``pesi`` / ``pesi_termici``: solo debug (tenuti con ``--con-pesi``);
    * ``base.quota_m`` / ``cima.quota_m``: costanti, già in ``localita``;
    * ``settore_850`` (ricavabile da ``dir_850``) e ``fonte_dir_850`` (quasi sempre "ecmwf_ifs");
    * precipitazione e neve oraria arrotondate a 0,1 (precisione reale dei modelli).
    """
    for h in out["orario"]:
        if not con_pesi:
            for campo in CAMPI_ORARI_DIAGNOSTICI:
                h.pop(campo, None)
        h.pop("settore_850", None)
        h.pop("fonte_dir_850", None)
        if h.get("precip_mm") is not None:
            h["precip_mm"] = round(h["precip_mm"], 1)
        for sez in ("base", "cima"):
            h[sez].pop("quota_m", None)
            if h[sez].get("neve_cm") is not None:
                h[sez]["neve_cm"] = round(h[sez]["neve_cm"], 1)


def _appiattisci(h: dict[str, Any], prefisso: str = "") -> dict[str, Any]:
    piatto: dict[str, Any] = {}
    for k, v in h.items():
        if isinstance(v, dict) and k not in CAMPI_ORARI_DIAGNOSTICI:
            piatto.update(_appiattisci(v, f"{prefisso}{k}_"))
        else:
            piatto[f"{prefisso}{k}"] = v
    return piatto


def a_colonne(orario: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """Righe orarie → colonne: ``{"time": [...], "base_neve_cm": [...], ...}``.

    I sotto-oggetti vengono appiattiti con prefisso (``base.tw_c`` → ``base_tw_c``,
    ``correzioni.omotermia_m`` → ``correzioni_omotermia_m``). Tutte le colonne hanno
    la stessa lunghezza: l'ora i-esima è ``{k: col[i] for k, col in colonne.items()}``.
    """
    righe = [_appiattisci(h) for h in orario]
    chiavi = list(dict.fromkeys(k for r in righe for k in r))
    return {k: [r.get(k) for r in righe] for k in chiavi}


RISPOSTE_GREZZE: dict[str, Any] = {}  # codice -> risposta Open-Meteo, per il calcolo punto per punto del sito


def esegui(codici: list[str], giorni: int, offline: bool, con_pesi: bool = False,
           formato: str = "colonne") -> dict[str, Any]:
    """Scarica ed elabora le località; un errore su una non blocca le altre."""
    risultati: dict[str, Any] = {}
    errori: dict[str, str] = {}
    controlli: dict[str, Any] = {}
    adesso_locale = datetime.now(timezone.utc).astimezone().replace(tzinfo=None)

    for n, codice in enumerate(codici, 1):
        cfg = eng.LOCALITA_CONFIG[codice]
        logger.info("[%d/%d] %s", n, len(codici), cfg["nome"])
        try:
            if offline:
                inizio = adesso_locale.replace(hour=0, minute=0, second=0, microsecond=0)
                dati = eng._genera_scenario_libeccio(inizio, ore=24 * giorni)
                dati["elevation"] = float(cfg["quota_base"])
                avvisi: list[str] = ["dati sintetici (--offline)"]
            else:
                dati, avvisi = scarica_localita(codice, giorni)

            RISPOSTE_GREZZE[codice] = dati
            out = eng.elabora_localita(codice, dati)
            snellisci(out, con_pesi)
            if formato == "colonne":
                out["orario"] = a_colonne(out["orario"])
            out["formato_orario"] = formato

            elev = _elevazione_risposta(dati)
            scarto = None if elev is None else round(elev - cfg["quota_base"])
            if scarto is not None and abs(scarto) > TOLLERANZA_QUOTA_M:
                avvisi.append(f"quota DEM {elev:.0f} m vs quota_base {cfg['quota_base']} m "
                              f"(scarto {scarto:+d} m): verificare le coordinate")
            controlli[codice] = {
                "coordinate": {"lat": COORDINATE[codice]["lat"], "lon": COORDINATE[codice]["lon"]},
                "coordinate_verificate": COORDINATE[codice]["verificata"],
                "quota_dem_m": None if elev is None else round(elev),
                "scarto_quota_m": scarto,
                "avvisi": avvisi,
            }
            out["controlli"] = controlli[codice]
            risultati[codice] = out
        except Exception as e:  # noqa: BLE001 — isolamento per località
            logger.exception("Errore su %s", codice)
            errori[codice] = str(e)
        if not offline and n < len(codici):
            time.sleep(PAUSA_TRA_LOCALITA_S)

    return {
        "schema_version": "2.0" if formato == "colonne" else eng.SCHEMA_VERSION,
        "formato_orario": formato,
        "generato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fonte": "sintetica (offline)" if offline else "Open-Meteo",
        "modelli_richiesti": list(eng.MODELLI_OPEN_METEO),
        "localita": risultati,
        "errori": errori,
    }


def salva_json(payload: dict[str, Any], percorso: str, pretty: bool) -> None:
    """Scrittura atomica: il frontend non legge mai un file a metà."""
    cartella = os.path.dirname(os.path.abspath(percorso))
    os.makedirs(cartella, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=cartella, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False,
                      indent=2 if pretty else None, separators=None if pretty else (",", ":"))
        os.replace(tmp, percorso)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# =============================================================================
# Riepilogo a terminale
# =============================================================================


def _fmt(x: Any, suff: str = "", w: int = 5) -> str:
    return f"{'—':>{w}}" if x is None else f"{x:>{w}}{suff}"


def stampa_riepilogo(payload: dict[str, Any], giorni_mostrati: int = 3) -> None:
    print(f"\n=== crinaleappennino.it — {payload['fonte']} — {payload['generato_il']} ===")
    for codice, out in payload["localita"].items():
        loc = out["localita"]
        ctrl = out.get("controlli", {})
        print(f"\n▲ {loc['nome']}  (base {loc['quota_base']} m · cima {loc['quota_cima']} m)  "
              f"modelli: {', '.join(out['modelli_disponibili'])}")
        print(f"  {'giorno':10} {'mm':>6} {'QN min':>7} {'neve base':>10} {'neve cima':>10} {'raff. cima':>11}")
        for g in out["giornaliero"][:giorni_mostrati]:
            print(f"  {g['data']:10} {g['precip_mm']:>6.1f} {_fmt(g['quota_neve_min_m'], ' m', 5)} "
                  f"{g['base']['neve_cm']:>7.1f} cm {g['cima']['neve_cm']:>7.1f} cm "
                  f"{_fmt(g['cima']['raffica_max_kmh'], ' km/h', 4)}")
        for a in ctrl.get("avvisi", []):
            print(f"  ⚠ {a}")
        if not ctrl.get("coordinate_verificate", True):
            print("  ⚠ coordinate stimate: verificarle")
    for codice, err in payload["errori"].items():
        print(f"\n✖ {codice}: {err}")
    ok, tot = len(payload["localita"]), len(payload["localita"]) + len(payload["errori"])
    print(f"\n{ok}/{tot} località elaborate.\n")


# =============================================================================
# CLI
# =============================================================================


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="output_crinale_v2.json", help="file JSON di output")
    ap.add_argument("--localita", nargs="+", choices=sorted(eng.LOCALITA_CONFIG), help="sottoinsieme di località")
    ap.add_argument("--giorni", type=int, default=5, help="giorni di previsione (default 5)")
    ap.add_argument("--pretty", action="store_true", help="JSON indentato (più leggibile, più pesante)")
    ap.add_argument("--formato", choices=("colonne", "righe"), default="colonne",
                    help="serie oraria a colonne (default, ~160 kB) o a righe (schema 1.0, ~500 kB)")
    ap.add_argument("--con-pesi", action="store_true",
                    help="include i pesi di blending orari (debug; JSON molto più pesante)")
    ap.add_argument("--offline", action="store_true", help="usa dati sintetici, senza chiamare Open-Meteo")
    ap.add_argument("--grezzi", help="salva anche le risposte Open-Meteo grezze (per il sito, punto per punto)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    codici = args.localita or list(eng.LOCALITA_CONFIG)
    payload = esegui(codici, args.giorni, args.offline, args.con_pesi, args.formato)

    if not payload["localita"]:
        logger.error("Nessuna località elaborata: %s non sovrascritto", args.out)
        stampa_riepilogo(payload)
        return 2

    salva_json(payload, args.out, args.pretty)
    if args.grezzi:
        salva_json(RISPOSTE_GREZZE, args.grezzi, False)
    stampa_riepilogo(payload)
    kb = os.path.getsize(args.out) / 1024
    logger.info("Scritto %s (%.0f kB)", args.out, kb)
    if kb > LIMITE_KB:
        logger.warning("JSON di %.0f kB oltre il limite di %d kB (formato=%s, con_pesi=%s)",
                       kb, LIMITE_KB, args.formato, args.con_pesi)
    return 1 if payload["errori"] else 0


if __name__ == "__main__":
    sys.exit(main())
