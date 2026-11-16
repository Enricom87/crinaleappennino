"""Tabella delle traduzioni: chiave = testo italiano, valore = {lingua: traduzione}."""
from i18n_content import ROWS as _C, SAME
from i18n_forecast import ROWS as _F
from i18n_pages import ROWS as _P
from i18n_ui import ROWS as _U

_LANGS = ("en", "de", "fr", "es", "zh")
STR: dict[str, dict[str, str]] = {r[0]: dict(zip(_LANGS, r[1:])) for r in _U + _P + _F + _C}
for _s in SAME:
    STR.setdefault(_s, {})
