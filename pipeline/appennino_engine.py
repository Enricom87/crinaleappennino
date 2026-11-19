"""
appennino_engine.py
===================

Motore di calcolo fisico-statistico per crinaleappennino.it.

Pipeline per ogni località e per ogni ora:

1. **Parsing** della risposta Open-Meteo multi-modello (chiavi orarie con
   suffisso ``_<modello>``) in serie allineate per modello.
2. **Diagnostica per modello**: profilo verticale di bulbo umido (2 m +
   livelli di pressione sopra il terreno), Tw a quota base/cima, zero di
   bulbo umido, raffiche in cresta.
3. **Regime-Based Blending**: pesi dinamici in funzione della direzione del
   vento a 850 hPa (ECMWF) e del lead time, con ridistribuzione proporzionale
   dei pesi dei modelli mancanti.
4. **Quota neve reale**: zero Tw + correzione omotermia + bonus valle chiusa.
5. **Accumulo nevoso**: SLR variabile da Tw + erosione eolica in cresta.
6. **Output JSON-ready**: serie oraria + totali giornalieri per base e cima.

Dipendenze: solo libreria standard (Python >= 3.10).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

# =============================================================================
# 1. CONFIGURAZIONE LOCALITÀ
# =============================================================================

LOCALITA_CONFIG: dict[str, dict[str, Any]] = {
    "abetone": {
        "nome": "Abetone",
        "versante": "toscano",
        "quota_base": 1388,
        "quota_cima": 1892,  # Monte Gomito
        "is_valle_chiusa": True,  # Val di Luce / Boscolungo trattengono cuscinetto freddo
        "is_cresta_esposta": True,  # Monte Gomito molto esposto al vento
    },
    "cimone": {
        "nome": "Cimone",
        "versante": "emiliano",
        "quota_base": 1550,  # Passo del Lupo
        "quota_cima": 2165,  # Vetta Cimone
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,
    },
    "le_polle": {
        "nome": "Le Polle",
        "versante": "emiliano",
        "quota_base": 1300,
        "quota_cima": 2165,
        "is_valle_chiusa": True,  # Conca riparata in basso
        "is_cresta_esposta": False,
    },
    "cimoncino": {
        "nome": "Cimoncino",
        "versante": "emiliano",
        "quota_base": 1423,  # stazione Cimoncino / Rif. Zambelli
        "quota_cima": 2165,
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,
    },
    "doganaccia": {
        "nome": "Doganaccia",
        "versante": "toscano",
        "quota_base": 1540,
        "quota_cima": 1780,  # Croce Arcana
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,  # Croce Arcana estremamente ventosa
    },
    "corno_alle_scale": {
        "nome": "Corno alle Scale",
        "versante": "emiliano",
        "quota_base": 1418,  # Cavone
        "quota_cima": 1945,  # Punta Sofia
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,
    },
    "lago_scaffaiolo": {
        "nome": "Lago Scaffaiolo",
        "versante": "crinale",
        "quota_base": 1775,
        "quota_cima": 1790,
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,  # Crinale puro, zero riparo
    },
    "lago_santo": {
        "nome": "Lago Santo",
        "versante": "emiliano",
        "quota_base": 1501,
        "quota_cima": 1991,  # Monte Giovo
        "is_valle_chiusa": True,  # Conca glaciale con forte inversione/cuscinetto
        "is_cresta_esposta": True,
    },
    "garfagnana": {
        "nome": "Garfagnana (Passo Radici / Casone)",
        "versante": "toscano",
        "quota_base": 1300,  # Casone di Profecchia
        "quota_cima": 2054,  # Monte Prado
        "is_valle_chiusa": True,
        "is_cresta_esposta": False,
    },
    "cerreto_laghi": {
        "nome": "Cerreto Laghi",
        "versante": "crinale",
        "quota_base": 1344,
        "quota_cima": 1894,  # Monte La Nuda
        "is_valle_chiusa": True,  # Conca del lago
        "is_cresta_esposta": True,
    },
    "febbio": {
        "nome": "Febbio",
        "versante": "emiliano",
        "quota_base": 1120,  # Rescadore
        "quota_cima": 2121,  # Monte Cusna
        "is_valle_chiusa": False,
        "is_cresta_esposta": True,
    },
}

# =============================================================================
# 2. COSTANTI FISICHE E PARAMETRI DI TARATURA
# =============================================================================

GRADIENTE_SATURO_C_PER_M: float = 0.0055  # 0.55 °C / 100 m
QUOTA_RIFERIMENTO_M: float = 1500.0  # fallback per 850 hPa
LIVELLI_HPA: tuple[int, ...] = (900, 850, 800, 700)
QUOTA_STANDARD_LIVELLI: dict[int, float] = {900: 1000.0, 850: 1500.0, 800: 1950.0, 700: 3010.0}

# Omotermia: (soglia mm/h, metri da sottrarre) — ordinate dalla più alta
SOGLIE_OMOTERMIA: tuple[tuple[float, int], ...] = ((10.0, 300), (6.0, 200), (3.0, 100))

# Valle chiusa / cuscinetto freddo
BONUS_VALLE_CHIUSA_M: int = 100
ORE_BONUS_VALLE_CHIUSA: int = 6
SOGLIA_PRECIP_EVENTO_MMH: float = 0.2  # sotto questa soglia l'ora è "secca"
PAUSA_FINE_EVENTO_H: int = 3  # ore secche consecutive che chiudono un evento

# Erosione eolica in cresta: (soglia raffica km/h, fattore) — ordinate dalla più alta.
# Convenzione ai bordi: soglia inferiore inclusa (35 → 0.80, 60 → 0.55, 85 → 0.30).
SOGLIE_VENTO: tuple[tuple[float, float], ...] = ((85.0, 0.30), (60.0, 0.55), (35.0, 0.80))

# Raffica "in libera atmosfera" stimata come vento medio al livello × fattore.
# Serve perché la raffica a 10 m sul terreno liscio del modello sottostima
# fortemente il vento sulle creste reali. Mettere a 0 per disattivarla.
FATTORE_RAFFICA_LIBERA: float = 1.35

# Coerenza quota neve / SLR: Tw_eff = Tw − (correzione_quota_m × 0.0055).
# Le stesse correzioni (omotermia + valle chiusa) che abbassano la quota neve
# raffreddano la Tw usata per l'SLR, così i cm non contraddicono la quota neve.
APPLICA_CORREZIONE_TW: bool = True

# Lead time oltre il quale si passa ai pesi di medio termine
LEAD_TIME_BREVE_H: float = 48.0

# =============================================================================
# 3. MODELLI E PESI DI BLENDING
# =============================================================================

#: Chiave interna -> identificativi Open-Meteo accettati (match per suffisso).
ALIAS_MODELLI: dict[str, tuple[str, ...]] = {
    "icon_2i": ("italia_meteo_arpae_icon_2i", "icon_2i"),
    # AROME HD (1,3 km) non arriva sull'Appennino tosco-emiliano (Open-Meteo restituisce solo null):
    # si usa AROME France (2,5 km), che copre tutte le località. La chiave interna resta la stessa.
    "arome_france_hd": ("meteofrance_arome_france_hd", "meteofrance_arome_france", "arome_france_hd"),
    "icon_ch2": ("meteoswiss_icon_ch2", "icon_ch2"),
    "ecmwf_ifs": ("ecmwf_ifs025", "ecmwf_ifs04", "ecmwf_ifs"),
    "gfs_seamless": ("gfs_seamless", "ncep_gfs_seamless"),
    "icon_eu": ("dwd_icon_eu", "icon_eu"),
}

#: Identificativi da passare al parametro ``models`` di Open-Meteo.
MODELLI_OPEN_METEO: tuple[str, ...] = (
    "italia_meteo_arpae_icon_2i",
    "meteofrance_arome_france",
    "meteoswiss_icon_ch2",
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_eu",
)

PESI_REGIME: dict[str, dict[str, float]] = {
    # Libeccio/Ostro 180°-250°: stau toscano
    "libeccio": {"icon_2i": 0.45, "arome_france_hd": 0.35, "ecmwf_ifs": 0.15, "gfs_seamless": 0.05},
    # Grecale/Bora 20°-80°: stau emiliano
    "grecale": {"icon_2i": 0.40, "icon_ch2": 0.30, "ecmwf_ifs": 0.20, "gfs_seamless": 0.10},
    # Tutte le altre direzioni (o direzione non disponibile)
    "altro": {"icon_2i": 0.35, "arome_france_hd": 0.25, "ecmwf_ifs": 0.25, "gfs_seamless": 0.15},
    # Lead time > 48 h
    "lungo_termine": {"ecmwf_ifs": 0.55, "icon_2i": 0.30, "gfs_seamless": 0.15},
}

#: Sostituti usati solo nel regime di lungo termine ("icon_2i o icon_eu").
SOSTITUTI_LUNGO_TERMINE: dict[str, tuple[str, ...]] = {"icon_2i": ("icon_eu",)}

# =============================================================================
# 4. VARIABILI DA RICHIEDERE A OPEN-METEO
# =============================================================================


def variabili_orarie() -> list[str]:
    """Restituisce l'elenco delle variabili ``hourly`` necessarie al motore."""
    vars_: list[str] = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_gusts_10m"]
    for lev in LIVELLI_HPA:
        vars_ += [
            f"temperature_{lev}hPa",
            f"relative_humidity_{lev}hPa",
            f"geopotential_height_{lev}hPa",
            f"wind_speed_{lev}hPa",
        ]
    vars_.append("wind_direction_850hPa")
    return vars_


def costruisci_parametri_richiesta(
    latitudine: float,
    longitudine: float,
    modelli: Sequence[str] = MODELLI_OPEN_METEO,
    giorni: int = 5,
    timezone_name: str = "Europe/Rome",
) -> dict[str, str]:
    """Parametri query per ``https://api.open-meteo.com/v1/forecast``.

    Nota: non si passa ``elevation``; il motore usa l'``elevation`` restituita
    come quota del punto a 2 m e ricostruisce il profilo con i livelli di
    pressione. I modelli che non hanno una variabile restituiscono ``null``:
    il blending ridistribuisce automaticamente i pesi.
    """
    return {
        "latitude": f"{latitudine:.4f}",
        "longitude": f"{longitudine:.4f}",
        "hourly": ",".join(variabili_orarie()),
        "models": ",".join(modelli),
        "forecast_days": str(giorni),
        "timezone": timezone_name,
        "wind_speed_unit": "kmh",
    }


# =============================================================================
# 5. PARSING DELLA RISPOSTA OPEN-METEO
# =============================================================================


@dataclass
class DatiModelli:
    """Serie orarie allineate per modello.

    Attributes:
        tempi: asse temporale comune (ora locale naive, come restituita da Open-Meteo).
        serie: ``serie[modello][variabile][i]`` -> valore o ``None``.
        elevazione: quota (m) del punto griglia/DEM a cui si riferiscono le variabili a 2 m.
        utc_offset_s: offset UTC del fuso richiesto.
    """

    tempi: list[datetime]
    serie: dict[str, dict[str, list[Optional[float]]]] = field(default_factory=dict)
    elevazione: Optional[float] = None
    utc_offset_s: int = 0

    def valore(self, modello: str, variabile: str, i: int) -> Optional[float]:
        """Valore di ``variabile`` per ``modello`` all'indice ``i`` (``None`` se assente)."""
        v = self.serie.get(modello, {}).get(variabile)
        if v is None or i >= len(v):
            return None
        x = v[i]
        if x is None:
            return None
        try:
            xf = float(x)
        except (TypeError, ValueError):
            return None
        return xf if math.isfinite(xf) else None

    @property
    def modelli(self) -> list[str]:
        return sorted(self.serie)


def _tabella_suffissi() -> list[tuple[str, str]]:
    """(suffisso, chiave interna) ordinati per lunghezza decrescente (match greedy)."""
    coppie = [(alias, chiave) for chiave, alias_list in ALIAS_MODELLI.items() for alias in alias_list]
    return sorted(coppie, key=lambda c: len(c[0]), reverse=True)


def normalizza_modello(nome: str) -> Optional[str]:
    """Converte un identificativo Open-Meteo nella chiave interna (``None`` se ignoto)."""
    nome = nome.strip().lower()
    for suffisso, chiave in _tabella_suffissi():
        if nome == suffisso or nome.endswith("_" + suffisso):
            return chiave
    return None


def _scomponi_chiave(chiave: str) -> tuple[str, Optional[str]]:
    """``temperature_850hPa_ecmwf_ifs025`` -> (``temperature_850hPa``, ``ecmwf_ifs``)."""
    for suffisso, modello in _tabella_suffissi():
        if chiave.endswith("_" + suffisso):
            return chiave[: -(len(suffisso) + 1)], modello
    return chiave, None


def estrai_dati_modelli(dati_open_meteo: Any) -> DatiModelli:
    """Normalizza la risposta Open-Meteo in :class:`DatiModelli`.

    Formati accettati:

    * una singola risposta multi-modello (``{"hourly": {...}}`` con chiavi
      suffissate ``_<modello>``);
    * una lista di risposte (single o multi-modello);
    * un dizionario ``{nome_modello: risposta_single_model}``.
    """
    risposte: list[tuple[Any, Optional[str]]] = []
    if isinstance(dati_open_meteo, Mapping) and "hourly" in dati_open_meteo:
        risposte.append((dati_open_meteo, None))
    elif isinstance(dati_open_meteo, Mapping):
        for nome, resp in dati_open_meteo.items():
            risposte.append((resp, normalizza_modello(str(nome))))
    elif isinstance(dati_open_meteo, (list, tuple)):
        risposte.extend((r, None) for r in dati_open_meteo)
    else:
        raise TypeError("Formato dati Open-Meteo non riconosciuto")

    grezzo: dict[str, dict[str, dict[datetime, Any]]] = {}
    tutti_tempi: set[datetime] = set()
    elevazione: Optional[float] = None
    offset = 0

    for resp, modello_hint in risposte:
        if not isinstance(resp, Mapping) or "hourly" not in resp:
            logger.warning("Risposta senza blocco 'hourly' ignorata")
            continue
        if elevazione is None and resp.get("elevation") is not None:
            elevazione = float(resp["elevation"])
        offset = int(resp.get("utc_offset_seconds", offset) or 0)
        hourly = resp["hourly"]
        tempi = [datetime.fromisoformat(t) for t in hourly.get("time", [])]
        tutti_tempi.update(tempi)
        for chiave, valori in hourly.items():
            if chiave == "time":
                continue
            variabile, modello = _scomponi_chiave(chiave)
            modello = modello or modello_hint
            if modello is None:
                logger.debug("Chiave senza modello riconoscibile: %s", chiave)
                continue
            dest = grezzo.setdefault(modello, {}).setdefault(variabile, {})
            for t, v in zip(tempi, valori):
                dest[t] = v

    asse = sorted(tutti_tempi)
    serie = {
        m: {var: [vals.get(t) for t in asse] for var, vals in vars_.items()}
        for m, vars_ in grezzo.items()
    }
    return DatiModelli(tempi=asse, serie=serie, elevazione=elevazione, utc_offset_s=offset)


# =============================================================================
# 6. FISICA DI BASE
# =============================================================================


def bulbo_umido_stull(t_c: float, rh_pct: float) -> float:
    """Temperatura di bulbo umido (°C) con la formula empirica di Stull (2011).

    Validità dichiarata: RH 5-99 %, T -20/+50 °C (errore tipico < 0.3 °C).
    Oltre il 99 % si interpola linearmente verso Tw = T (saturazione), evitando
    il piccolo bias della formula in condizioni sature. Il risultato non supera mai T.
    """
    def _stull(t: float, rh: float) -> float:
        return (
            t * math.atan(0.151977 * math.sqrt(rh + 8.313659))
            + math.atan(t + rh)
            - math.atan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * math.atan(0.023101 * rh)
            - 4.686035
        )

    rh = min(max(rh_pct, 5.0), 100.0)
    if rh > 99.0:
        tw99 = _stull(t_c, 99.0)
        tw = tw99 + (t_c - tw99) * (rh - 99.0)
    else:
        tw = _stull(t_c, rh)
    return min(tw, t_c)


def quota_zero_bulbo_umido(tw_rif: float, z_rif: float = QUOTA_RIFERIMENTO_M) -> float:
    """Quota (m) dello zero di Tw estrapolando con gradiente saturo 0.55 °C/100 m."""
    return z_rif + tw_rif / GRADIENTE_SATURO_C_PER_M


def tw_effettiva(tw: Optional[float], correzione_quota_m: float) -> Optional[float]:
    """Tw corretta per omotermia/cuscinetto: ``Tw − correzione_m × 0.0055``.

    Restituisce ``tw`` invariata se :data:`APPLICA_CORREZIONE_TW` è ``False``.
    """
    if tw is None or not APPLICA_CORREZIONE_TW:
        return tw
    return tw - correzione_quota_m * GRADIENTE_SATURO_C_PER_M


def correzione_omotermia(precip_mmh: float) -> int:
    """Metri da sottrarre alla quota neve per raffreddamento da fusione/evaporazione."""
    for soglia, metri in SOGLIE_OMOTERMIA:
        if precip_mmh >= soglia:
            return metri
    return 0


def slr_da_tw(tw: Optional[float]) -> float:
    """Snow-to-Liquid Ratio in funzione della temperatura di bulbo umido."""
    if tw is None or tw > 0.5:
        return 0.0
    if tw > -1.0:
        return 6.5
    if tw > -3.0:
        return 9.5
    if tw > -6.0:
        return 12.5
    return 15.0


def fattore_vento(raffica_kmh: Optional[float]) -> float:
    """Fattore di riduzione dell'accumulo per erosione/trasporto eolico in cresta."""
    if raffica_kmh is None:
        return 1.0
    for soglia, fattore in SOGLIE_VENTO:
        if raffica_kmh >= soglia:
            return fattore
    return 1.0


def accumulo_neve_cm(
    precip_mm: float,
    tw: Optional[float],
    raffica_kmh: Optional[float] = None,
    applica_vento: bool = False,
) -> tuple[float, float, float]:
    """Accumulo orario di neve fresca.

    ``cm = mm * SLR / 10`` (SLR 10:1 → 1 mm d'acqua = 1 cm di neve).

    Returns:
        (accumulo_cm, slr, fattore_vento_applicato)
    """
    slr = slr_da_tw(tw)
    fv = fattore_vento(raffica_kmh) if applica_vento else 1.0
    cm = max(precip_mm, 0.0) * slr / 10.0 * fv
    return cm, slr, fv


# =============================================================================
# 7. INTERPOLAZIONE VERTICALE E DIAGNOSTICA PER MODELLO
# =============================================================================


def interpola_verticale(
    punti: Sequence[tuple[float, float]],
    z: float,
    gradiente_extrap: Optional[float] = GRADIENTE_SATURO_C_PER_M,
) -> Optional[float]:
    """Interpolazione lineare in quota su ``punti`` = [(z, valore), ...].

    Fuori dall'intervallo: estrapola con ``gradiente_extrap`` (°C/m, valore che
    diminuisce con la quota) o, se ``None``, usa il valore più vicino.
    """
    if not punti:
        return None
    pts = sorted(punti)
    if z <= pts[0][0]:
        z0, v0 = pts[0]
        return v0 + (gradiente_extrap * (z0 - z) if gradiente_extrap else 0.0)
    if z >= pts[-1][0]:
        z1, v1 = pts[-1]
        return v1 - (gradiente_extrap * (z - z1) if gradiente_extrap else 0.0)
    for (za, va), (zb, vb) in zip(pts, pts[1:]):
        if za <= z <= zb:
            if zb == za:
                return va
            return va + (vb - va) * (z - za) / (zb - za)
    return None  # pragma: no cover


@dataclass
class DiagnosticaOraria:
    """Grandezze derivate di un singolo modello in una singola ora."""

    dir_850: Optional[float] = None
    tw_850: Optional[float] = None
    z_tw: Optional[float] = None
    tw_base: Optional[float] = None
    tw_cima: Optional[float] = None
    precip: Optional[float] = None
    raffica_base: Optional[float] = None
    raffica_cima: Optional[float] = None


def diagnostica_modello(
    dati: DatiModelli, modello: str, i: int, quota_base: float, quota_cima: float
) -> DiagnosticaOraria:
    """Calcola le grandezze derivate per un modello all'ora ``i``.

    Il profilo di Tw usa il punto a 2 m (alla quota ``dati.elevazione``) più i
    livelli di pressione **sopra** il terreno del modello; i livelli sotto
    terra (valori estrapolati dal modello) vengono scartati.
    """
    v = lambda var: dati.valore(modello, var, i)  # noqa: E731
    d = DiagnosticaOraria()
    elev = dati.elevazione

    profilo_tw: list[tuple[float, float]] = []
    profilo_vento: list[tuple[float, float]] = []

    t2, rh2 = v("temperature_2m"), v("relative_humidity_2m")
    if t2 is not None and rh2 is not None and elev is not None:
        profilo_tw.append((elev, bulbo_umido_stull(t2, rh2)))

    for lev in LIVELLI_HPA:
        z = v(f"geopotential_height_{lev}hPa") or QUOTA_STANDARD_LIVELLI[lev]
        if elev is not None and z < elev:
            continue
        t, rh = v(f"temperature_{lev}hPa"), v(f"relative_humidity_{lev}hPa")
        if t is not None and rh is not None:
            tw = bulbo_umido_stull(t, rh)
            profilo_tw.append((z, tw))
            if lev == 850:
                d.tw_850 = tw
                d.z_tw = quota_zero_bulbo_umido(tw, z)
        ws = v(f"wind_speed_{lev}hPa")
        if ws is not None:
            profilo_vento.append((z, ws))

    # Zero Tw: se manca 850 hPa, usa il profilo interpolato a 1500 m
    if d.z_tw is None and profilo_tw:
        tw_rif = interpola_verticale(profilo_tw, QUOTA_RIFERIMENTO_M)
        if tw_rif is not None:
            d.z_tw = quota_zero_bulbo_umido(tw_rif, QUOTA_RIFERIMENTO_M)

    d.tw_base = interpola_verticale(profilo_tw, quota_base)
    d.tw_cima = interpola_verticale(profilo_tw, quota_cima)
    d.dir_850 = v("wind_direction_850hPa")
    d.precip = v("precipitation")

    g10 = v("wind_gusts_10m")
    d.raffica_base = g10
    candidati = [g10] if g10 is not None else []
    if profilo_vento and FATTORE_RAFFICA_LIBERA > 0:
        ws_cima = interpola_verticale(profilo_vento, quota_cima, gradiente_extrap=None)
        if ws_cima is not None:
            candidati.append(ws_cima * FATTORE_RAFFICA_LIBERA)
    d.raffica_cima = max(candidati) if candidati else None
    return d


# =============================================================================
# 8. REGIME-BASED BLENDING
# =============================================================================


def settore_vento(direzione: Optional[float]) -> str:
    """Classifica la direzione a 850 hPa: ``libeccio``, ``grecale`` o ``altro``."""
    if direzione is None:
        return "altro"
    d = direzione % 360.0
    if 180.0 <= d <= 250.0:
        return "libeccio"
    if 20.0 <= d <= 80.0:
        return "grecale"
    return "altro"


def classifica_regime(direzione_850: Optional[float], lead_time_h: float) -> str:
    """Regime di blending in funzione di direzione 850 hPa e lead time."""
    if lead_time_h > LEAD_TIME_BREVE_H:
        return "lungo_termine"
    return settore_vento(direzione_850)


def media_pesata(
    valori: Mapping[str, Optional[float]],
    pesi: Mapping[str, float],
    sostituti: Optional[Mapping[str, Iterable[str]]] = None,
) -> tuple[Optional[float], dict[str, float]]:
    """Media pesata con ridistribuzione proporzionale dei pesi mancanti.

    1. Il peso di un modello assente passa al primo sostituto disponibile (se previsto).
    2. I pesi rimasti vengono rinormalizzati a 1 sui soli modelli disponibili.
    3. Se nessun modello del regime è disponibile, media semplice dei disponibili.

    Returns:
        (valore_mediato, pesi_effettivi)
    """
    disponibili = {m: x for m, x in valori.items() if x is not None and math.isfinite(x)}
    if not disponibili:
        return None, {}

    eff: dict[str, float] = {}
    for m, w in pesi.items():
        if w <= 0:
            continue
        if m in disponibili:
            eff[m] = eff.get(m, 0.0) + w
        elif sostituti:
            for s in sostituti.get(m, ()):
                if s in disponibili:
                    eff[s] = eff.get(s, 0.0) + w
                    break

    totale = sum(eff.values())
    if totale <= 0:
        n = len(disponibili)
        eff = {m: 1.0 / n for m in disponibili}
    else:
        eff = {m: w / totale for m, w in eff.items()}
    return sum(disponibili[m] * w for m, w in eff.items()), eff


def media_circolare(direzioni: Mapping[str, Optional[float]], pesi: Mapping[str, float]) -> Optional[float]:
    """Media vettoriale pesata di direzioni (gradi), con pesi ridistribuiti."""
    validi = {m: d for m, d in direzioni.items() if d is not None}
    if not validi:
        return None
    w = {m: pesi.get(m, 0.0) for m in validi}
    if sum(w.values()) <= 0:
        w = {m: 1.0 for m in validi}
    s = sum(math.sin(math.radians(d)) * w[m] for m, d in validi.items())
    c = sum(math.cos(math.radians(d)) * w[m] for m, d in validi.items())
    return math.degrees(math.atan2(s, c)) % 360.0


def direzione_850_riferimento(diag: Mapping[str, DiagnosticaOraria]) -> tuple[Optional[float], str]:
    """Direzione 850 hPa da ECMWF; fallback: media circolare degli altri modelli."""
    ecmwf = diag.get("ecmwf_ifs")
    if ecmwf and ecmwf.dir_850 is not None:
        return ecmwf.dir_850, "ecmwf_ifs"
    d = media_circolare({m: x.dir_850 for m, x in diag.items()}, PESI_REGIME["altro"])
    return d, "media_modelli" if d is not None else "n/d"


# =============================================================================
# 9. EVENTI PRECIPITATIVI E QUOTA NEVE
# =============================================================================


def ore_da_inizio_evento(precip: Sequence[Optional[float]]) -> list[Optional[int]]:
    """Per ogni ora, ore trascorse dall'inizio dell'evento in corso (``None`` se secco).

    Un evento inizia alla prima ora >= ``SOGLIA_PRECIP_EVENTO_MMH`` e termina dopo
    ``PAUSA_FINE_EVENTO_H`` ore secche consecutive.
    """
    out: list[Optional[int]] = []
    inizio: Optional[int] = None
    secche = 0
    for i, p in enumerate(precip):
        bagnata = p is not None and p >= SOGLIA_PRECIP_EVENTO_MMH
        if bagnata:
            if inizio is None:
                inizio = i
            secche = 0
            out.append(i - inizio)
        else:
            if inizio is not None:
                secche += 1
                if secche >= PAUSA_FINE_EVENTO_H:
                    inizio, secche = None, 0
            out.append(None)
    return out


def calcola_quota_neve(
    z_tw: Optional[float],
    precip_mmh: float,
    is_valle_chiusa: bool,
    ore_da_inizio: Optional[int],
) -> tuple[Optional[float], dict[str, int]]:
    """Quota neve reale = zero Tw − omotermia − bonus valle chiusa (minimo 0 m).

    Returns:
        (quota_neve_m, dettaglio_correzioni)
    """
    if z_tw is None:
        return None, {"omotermia_m": 0, "valle_chiusa_m": 0}
    omo = correzione_omotermia(precip_mmh)
    valle = (
        BONUS_VALLE_CHIUSA_M
        if is_valle_chiusa and ore_da_inizio is not None and ore_da_inizio < ORE_BONUS_VALLE_CHIUSA
        else 0
    )
    return max(z_tw - omo - valle, 0.0), {"omotermia_m": omo, "valle_chiusa_m": valle}


# =============================================================================
# 10. ELABORAZIONE LOCALITÀ
# =============================================================================


def _r(x: Optional[float], nd: int = 1) -> Optional[float | int]:
    """Arrotonda per il JSON (intero se ``nd == 0``); ``None`` resta ``None``."""
    if x is None:
        return None
    return int(round(float(x))) if nd == 0 else round(float(x), nd)


def _riferimento_default(dati: DatiModelli) -> datetime:
    """Istante attuale espresso nell'ora locale naive della risposta, troncato all'ora."""
    now = datetime.now(timezone.utc) + timedelta(seconds=dati.utc_offset_s)
    return now.replace(tzinfo=None, minute=0, second=0, microsecond=0)


def elabora_localita(
    codice_localita: str,
    dati_open_meteo: Any,
    riferimento: Optional[datetime] = None,
) -> dict[str, Any]:
    """Elabora una località e restituisce un dizionario serializzabile in JSON.

    Args:
        codice_localita: chiave di :data:`LOCALITA_CONFIG` (es. ``"abetone"``).
        dati_open_meteo: risposta Open-Meteo (vedi :func:`estrai_dati_modelli`).
        riferimento: istante (ora locale naive) da cui misurare il lead time;
            default = ora corrente. Le ore passate hanno lead time 0.

    Returns:
        Dizionario con metadati, ``orario`` (serie oraria), ``giornaliero`` e ``totali``.

    Raises:
        KeyError: se la località non esiste.
        ValueError: se i dati non contengono serie temporali.
    """
    if codice_localita not in LOCALITA_CONFIG:
        raise KeyError(f"Località sconosciuta: {codice_localita!r}")
    cfg = LOCALITA_CONFIG[codice_localita]
    q_base, q_cima = float(cfg["quota_base"]), float(cfg["quota_cima"])

    dati = dati_open_meteo if isinstance(dati_open_meteo, DatiModelli) else estrai_dati_modelli(dati_open_meteo)
    if not dati.tempi:
        raise ValueError("Nessuna serie temporale nei dati Open-Meteo")
    rif = riferimento or _riferimento_default(dati)

    # --- Passo 1: diagnostica per modello + blending ---------------------------
    blend_rows: list[dict[str, Any]] = []
    for i, t in enumerate(dati.tempi):
        lead = max(0.0, (t - rif).total_seconds() / 3600.0)
        diag = {m: diagnostica_modello(dati, m, i, q_base, q_cima) for m in dati.modelli}
        dir850, fonte_dir = direzione_850_riferimento(diag)
        regime = classifica_regime(dir850, lead)
        pesi = PESI_REGIME[regime]
        sost = SOSTITUTI_LUNGO_TERMINE if regime == "lungo_termine" else None

        def bl(attr: str) -> tuple[Optional[float], dict[str, float]]:
            return media_pesata({m: getattr(x, attr) for m, x in diag.items()}, pesi, sost)

        precip, pesi_precip = bl("precip")
        z_tw, pesi_termici = bl("z_tw")
        tw_base, _ = bl("tw_base")
        tw_cima, _ = bl("tw_cima")
        raff_base, _ = bl("raffica_base")
        raff_cima, _ = bl("raffica_cima")

        blend_rows.append(
            {
                "t": t, "lead": lead, "dir850": dir850, "fonte_dir": fonte_dir,
                "settore": settore_vento(dir850), "regime": regime,
                "precip": max(precip or 0.0, 0.0), "precip_disp": precip is not None,
                "z_tw": z_tw, "tw_base": tw_base, "tw_cima": tw_cima,
                "raff_base": raff_base, "raff_cima": raff_cima,
                "pesi_precip": pesi_precip, "pesi_termici": pesi_termici,
            }
        )

    # --- Passo 2: eventi, quota neve, accumuli --------------------------------
    eventi = ore_da_inizio_evento([r["precip"] for r in blend_rows])
    orario: list[dict[str, Any]] = []
    for r, ore_ev in zip(blend_rows, eventi):
        quota_neve, corr = calcola_quota_neve(r["z_tw"], r["precip"], cfg["is_valle_chiusa"], ore_ev)
        corr_tot = corr["omotermia_m"] + corr["valle_chiusa_m"]
        tw_eff_b = tw_effettiva(r["tw_base"], corr_tot)
        tw_eff_c = tw_effettiva(r["tw_cima"], corr_tot)
        cm_b, slr_b, _ = accumulo_neve_cm(r["precip"], tw_eff_b)
        cm_c, slr_c, fv_c = accumulo_neve_cm(
            r["precip"], tw_eff_c, r["raff_cima"], applica_vento=bool(cfg["is_cresta_esposta"])
        )
        orario.append(
            {
                "time": r["t"].isoformat(timespec="minutes"),
                "lead_h": int(round(r["lead"])),
                "regime": r["regime"],
                "settore_850": r["settore"],
                "dir_850": _r(r["dir850"], 0),
                "fonte_dir_850": r["fonte_dir"],
                "precip_mm": _r(r["precip"], 2) if r["precip_disp"] else None,
                "ore_da_inizio_evento": ore_ev,
                "zero_tw_m": _r(r["z_tw"], 0),
                "quota_neve_m": _r(quota_neve, 0),
                "correzioni": corr,
                "base": {
                    "quota_m": int(q_base),
                    "tw_c": _r(r["tw_base"], 1),
                    "tw_eff_c": _r(tw_eff_b, 1),
                    "slr": slr_b,
                    "raffica_kmh": _r(r["raff_base"], 0),
                    "neve_cm": _r(cm_b, 2),
                },
                "cima": {
                    "quota_m": int(q_cima),
                    "tw_c": _r(r["tw_cima"], 1),
                    "tw_eff_c": _r(tw_eff_c, 1),
                    "slr": slr_c,
                    "raffica_kmh": _r(r["raff_cima"], 0),
                    "fattore_vento": fv_c,
                    "neve_cm": _r(cm_c, 2),
                },
                "pesi": {m: round(w, 3) for m, w in sorted(r["pesi_precip"].items())},
                "pesi_termici": {m: round(w, 3) for m, w in sorted(r["pesi_termici"].items())},
            }
        )

    giornaliero = aggrega_giornaliero(orario)
    return {
        "schema_version": SCHEMA_VERSION,
        "generato_il": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "riferimento": rif.isoformat(timespec="minutes"),
        "localita": {"codice": codice_localita, **cfg},
        "modelli_disponibili": dati.modelli,
        "elevazione_modello_m": _r(dati.elevazione, 0),
        "orario": orario,
        "giornaliero": giornaliero,
        "totali": _totali(giornaliero),
    }


def aggrega_giornaliero(orario: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Totali e estremi giornalieri (giorno locale) per quota base e cima."""
    giorni: dict[str, list[Mapping[str, Any]]] = {}
    for h in orario:
        giorni.setdefault(h["time"][:10], []).append(h)

    out: list[dict[str, Any]] = []
    for data, ore in giorni.items():
        bagnate = [h for h in ore if (h["precip_mm"] or 0) >= SOGLIA_PRECIP_EVENTO_MMH]
        qn = [h["quota_neve_m"] for h in bagnate if h["quota_neve_m"] is not None]

        def _vals(sezione: str, chiave: str) -> list[float]:
            return [h[sezione][chiave] for h in ore if h[sezione][chiave] is not None]

        def _blocco(sezione: str) -> dict[str, Any]:
            tw = _vals(sezione, "tw_c")
            raff = _vals(sezione, "raffica_kmh")
            return {
                "neve_cm": round(sum(_vals(sezione, "neve_cm")), 1),
                "ore_neve": sum(1 for h in ore if (h[sezione]["neve_cm"] or 0) > 0),
                "tw_min_c": min(tw) if tw else None,
                "tw_max_c": max(tw) if tw else None,
                "raffica_max_kmh": max(raff) if raff else None,
            }

        out.append(
            {
                "data": data,
                "ore": len(ore),
                "precip_mm": round(sum(h["precip_mm"] or 0 for h in ore), 1),
                "ore_precip": len(bagnate),
                "quota_neve_min_m": min(qn) if qn else None,
                "quota_neve_media_m": round(sum(qn) / len(qn)) if qn else None,
                "base": _blocco("base"),
                "cima": _blocco("cima"),
            }
        )
    return out


def _totali(giornaliero: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "precip_mm": round(sum(g["precip_mm"] for g in giornaliero), 1),
        "neve_base_cm": round(sum(g["base"]["neve_cm"] for g in giornaliero), 1),
        "neve_cima_cm": round(sum(g["cima"]["neve_cm"] for g in giornaliero), 1),
    }


def elabora_tutte(dati_per_localita: Mapping[str, Any], riferimento: Optional[datetime] = None) -> dict[str, Any]:
    """Elabora più località; un errore su una non blocca le altre."""
    out: dict[str, Any] = {}
    for codice, dati in dati_per_localita.items():
        try:
            out[codice] = elabora_localita(codice, dati, riferimento)
        except Exception as exc:  # noqa: BLE001 — isolamento per località
            logger.exception("Errore elaborando %s", codice)
            out[codice] = {"errore": str(exc)}
    return out


# =============================================================================
# 11. TEST SIMULATO: PEGGIORAMENTO DA LIBECCIO ALL'ABETONE
# =============================================================================


def _genera_scenario_libeccio(inizio: datetime, ore: int = 96) -> dict[str, Any]:
    """Risposta Open-Meteo multi-modello sintetica.

    Scenario: richiamo caldo-umido da SW (215°) con stau toscano, picco ~9 mm/h
    a +26 h, passaggio del fronte a +30 h con rotazione a NW e crollo termico,
    breve fase da NE (+40/+47 h), poi debole evento a +60/+70 h.
    Coperture: AROME HD 42 h (solo superficie), ICON-CH2 33 h, ICON-2I 72 h,
    ECMWF / GFS / ICON-EU 96 h.
    """
    modelli = {
        # suffisso open-meteo: (ore coperte, offset T, fattore precip, livelli pressione?)
        "italia_meteo_arpae_icon_2i": (72, 0.0, 1.15, True),
        "meteofrance_arome_france_hd": (42, -0.3, 1.25, False),
        "meteoswiss_icon_ch2": (33, 0.2, 1.05, True),
        "ecmwf_ifs025": (96, 0.4, 0.85, True),
        "gfs_seamless": (96, 0.8, 0.70, True),
        "icon_eu": (96, 0.3, 0.90, True),
    }
    tempi = [inizio + timedelta(hours=h) for h in range(ore)]
    hourly: dict[str, list[Any]] = {"time": [t.isoformat(timespec="minutes") for t in tempi]}

    def t850(h: int) -> float:
        if h < 30:
            return 1.5 - 2.5 * h / 30  # +1.5 → -1.0 (fusione/evaporazione nel pre-frontale)
        if h < 48:
            return -1.0 - 5.0 * (h - 30) / 18  # crollo post-frontale fino a -6
        return -5.0

    def rh850(h: int) -> float:
        return 97.0 if h < 34 else (80.0 if h < 48 else (92.0 if 60 <= h < 70 else 65.0))

    def direzione(h: int) -> float:
        if h < 30:
            return 215.0
        if 40 <= h < 48:
            return 45.0
        return 315.0

    def precip(h: int) -> float:
        p = 0.0
        if 12 <= h <= 36:
            p = 9.0 * math.exp(-((h - 26) / 5.0) ** 2)
        if 40 <= h < 48:
            p = 1.5
        if 60 <= h < 70:
            p = 1.2
        return p

    def vento800(h: int) -> float:
        return 35.0 + 40.0 * math.exp(-((h - 29) / 6.0) ** 2)

    for suff, (copertura, dt, fp, livelli) in modelli.items():
        def col(fn) -> list[Optional[float]]:
            return [round(fn(h), 2) if h < copertura else None for h in range(ore)]

        hourly[f"temperature_2m_{suff}"] = col(lambda h: t850(h) + dt + 1.4)
        hourly[f"relative_humidity_2m_{suff}"] = col(lambda h: min(rh850(h) + 2, 100))
        hourly[f"precipitation_{suff}"] = col(lambda h: precip(h) * fp)
        hourly[f"wind_gusts_10m_{suff}"] = col(lambda h: 0.7 * vento800(h))
        if livelli:
            hourly[f"wind_direction_850hPa_{suff}"] = col(lambda h: direzione(h) + dt * 5)
            for lev, (dz, dtl, dws) in {
                900: (1000, 2.9, 0.7), 850: (1480, 0.0, 0.85), 800: (1960, -2.8, 1.0), 700: (3010, -8.5, 1.3)
            }.items():
                hourly[f"temperature_{lev}hPa_{suff}"] = col(lambda h, x=dtl: t850(h) + dt + x)
                hourly[f"relative_humidity_{lev}hPa_{suff}"] = col(rh850)
                hourly[f"geopotential_height_{lev}hPa_{suff}"] = col(lambda h, z=dz: z)
                hourly[f"wind_speed_{lev}hPa_{suff}"] = col(lambda h, k=dws: vento800(h) * k)

    return {"latitude": 44.14, "longitude": 10.66, "elevation": 1250.0,
            "utc_offset_seconds": 3600, "timezone": "Europe/Rome", "hourly": hourly}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # --- Test unitari della fisica ---------------------------------------------
    assert abs(bulbo_umido_stull(20.0, 50.0) - 13.7) < 0.1, "Stull: valore di riferimento"
    assert abs(bulbo_umido_stull(0.0, 100.0)) < 1e-9, "Saturazione: Tw = T"
    assert bulbo_umido_stull(2.0, 60.0) < 2.0
    assert quota_zero_bulbo_umido(1.1, 1500) == 1700.0
    assert [correzione_omotermia(p) for p in (2.9, 3.0, 6.0, 10.0)] == [0, 100, 200, 300]
    assert [slr_da_tw(t) for t in (0.6, 0.5, -1.0, -3.0, -6.0, -8.0)] == [0, 6.5, 9.5, 12.5, 15.0, 15.0]
    assert [fattore_vento(g) for g in (30, 35, 60, 85, 120)] == [1.0, 0.80, 0.55, 0.30, 0.30]
    v, w = media_pesata({"icon_2i": 1.0, "ecmwf_ifs": 3.0, "arome_france_hd": None}, PESI_REGIME["libeccio"])
    assert abs(sum(w.values()) - 1) < 1e-9 and "arome_france_hd" not in w
    assert abs(v - (1.0 * 0.45 + 3.0 * 0.15) / 0.60) < 1e-9, "Ridistribuzione proporzionale"
    assert normalizza_modello("ecmwf_ifs025") == "ecmwf_ifs"
    assert _scomponi_chiave("temperature_850hPa_italia_meteo_arpae_icon_2i") == ("temperature_850hPa", "icon_2i")

    # --- Scenario Libeccio Abetone ---------------------------------------------
    t0 = datetime(2026, 11, 20, 0, 0)
    risposta = _genera_scenario_libeccio(t0)
    risultato = elabora_localita("abetone", risposta, riferimento=t0)
    orario = risultato["orario"]

    for h in orario:
        assert abs(sum(h["pesi"].values()) - 1) < 1e-6, f"Pesi non normalizzati alle {h['time']}"
    assert all(h["regime"] == "libeccio" for h in orario[:30]), "Regime libeccio atteso nelle prime 30 h"
    assert orario[44]["regime"] == "grecale"
    assert all(h["regime"] == "lungo_termine" for h in orario[49:])
    assert "arome_france_hd" in orario[20]["pesi"] and "arome_france_hd" not in orario[45]["pesi"]
    assert "icon_eu" in orario[80]["pesi"] and "icon_2i" not in orario[80]["pesi"], "Sostituto ICON-EU"
    picco = max(orario, key=lambda h: h["precip_mm"] or 0)
    assert picco["correzioni"]["omotermia_m"] >= 200
    onset = next(i for i, h in enumerate(orario) if h["ore_da_inizio_evento"] == 0)
    assert all(orario[onset + k]["correzioni"]["valle_chiusa_m"] == 100 for k in range(6)), "Bonus < 6 h"
    assert orario[onset + 6]["correzioni"]["valle_chiusa_m"] == 0
    assert risultato["totali"]["neve_cima_cm"] > 0
    for h in orario:  # coerenza: correzione Tw = correzioni quota × 0.0055
        if h["base"]["tw_c"] is not None:
            attesa = (h["correzioni"]["omotermia_m"] + h["correzioni"]["valle_chiusa_m"]) * GRADIENTE_SATURO_C_PER_M
            assert abs((h["base"]["tw_c"] - h["base"]["tw_eff_c"]) - attesa) < 0.11
    json.dumps(risultato)  # serializzabilità

    # --- Report ----------------------------------------------------------------
    print(f"\n{risultato['localita']['nome']} — base {risultato['localita']['quota_base']} m, "
          f"cima {risultato['localita']['quota_cima']} m — modelli: {', '.join(risultato['modelli_disponibili'])}\n")
    print(f"{'ora':16} {'lead':>4} {'regime':13} {'dir':>4} {'mm/h':>5} {'0Tw':>5} {'QN':>5} "
          f"{'TwB':>5} {'cmB':>5} {'TwC':>5} {'raffC':>5} {'fv':>4} {'cmC':>5}")
    for h in orario:
        if (h["precip_mm"] or 0) < 0.2 and h["lead_h"] % 6:
            continue
        b, c = h["base"], h["cima"]
        print(f"{h['time']:16} {h['lead_h']:>4} {h['regime']:13} {h['dir_850'] or 0:>4.0f} "
              f"{h['precip_mm'] or 0:>5.1f} {h['zero_tw_m'] or 0:>5.0f} {h['quota_neve_m'] or 0:>5.0f} "
              f"{b['tw_c']:>5.1f} {b['neve_cm']:>5.1f} {c['tw_c']:>5.1f} {c['raffica_kmh']:>5.0f} "
              f"{c['fattore_vento']:>4.2f} {c['neve_cm']:>5.1f}")

    print("\nTotali giornalieri:")
    for g in risultato["giornaliero"]:
        print(f"  {g['data']}: {g['precip_mm']:>5.1f} mm | QN min {g['quota_neve_min_m']} m | "
              f"base {g['base']['neve_cm']:>5.1f} cm | cima {g['cima']['neve_cm']:>5.1f} cm "
              f"(raffica max {g['cima']['raffica_max_kmh']} km/h)")
    print(f"\nTotale evento: {risultato['totali']}")
    print("\nTutti i test superati ✔")
