"""Lingue del sito. L'italiano è la lingua sorgente: ogni testo italiano è anche la chiave della traduzione.

set_lang() imposta la lingua corrente; T() traduce (e formatta) una stringa; nice_date() scrive le date
nella lingua corrente. Le traduzioni stanno in i18n_strings.py: se una manca resta l'italiano.
"""
from __future__ import annotations

from datetime import date

from i18n_strings import STR

LANGS = ["it", "en", "de", "fr", "es", "zh"]
NAMES = {"it": "Italiano", "en": "English", "de": "Deutsch", "fr": "Français", "es": "Español", "zh": "中文"}
HTML_LANG = {"it": "it", "en": "en", "de": "de", "fr": "fr", "es": "es", "zh": "zh-Hans"}

DAYS = {
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "zh": ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"],
}
DAYS_SHORT = {
    "it": ["lun", "mar", "mer", "gio", "ven", "sab", "dom"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "de": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
    "fr": ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"],
    "es": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
    "zh": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
}
MONTHS = {
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
           "ottobre", "novembre", "dicembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
           "novembre", "décembre"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"],
}

LANG = "it"
MISSING: set[str] = set()


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang


def T(s: str, **kw) -> str:
    out = s
    if LANG != "it":
        out = STR.get(s, {}).get(LANG) or s
        if s not in STR and s:
            MISSING.add(s)
    return out.format(**kw) if kw else out


def nice_date(d: str, short: bool = False) -> str:
    x = date.fromisoformat(d)
    wd, l = x.weekday(), LANG
    if short:
        return f"{DAYS_SHORT[l][wd]} {x.day}" if l != "zh" else f"{DAYS_SHORT[l][wd]} {x.day}日"
    if l == "zh":
        return f"{x.month}月{x.day}日（{DAYS_SHORT[l][wd]}）"
    if l == "de":
        return f"{DAYS[l][wd]}, {x.day}. {MONTHS[l][x.month - 1]}"
    if l == "en":
        return f"{DAYS[l][wd]} {x.day} {MONTHS[l][x.month - 1]}"
    if l == "es":
        return f"{DAYS[l][wd]} {x.day} de {MONTHS[l][x.month - 1]}"
    return f"{DAYS[l][wd]} {x.day} {MONTHS[l][x.month - 1]}"


def day_name(d: str) -> str:
    x = date.fromisoformat(d)
    n = DAYS[LANG][x.weekday()]
    return n[:1].upper() + n[1:]


def day_short(d: str) -> str:
    return DAYS_SHORT[LANG][date.fromisoformat(d).weekday()]


def cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s
