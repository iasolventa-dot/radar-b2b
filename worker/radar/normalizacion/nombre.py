"""Normalización de texto y de razón social / nombre comercial (doc 05 §1, §2.3).

Funciones de bajo nivel (`quitar_tildes`, `normalizar_texto`) que también usa
`radar.normalizacion.direccion` para comparar nombres de provincia.
"""

from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

# =====================================================================
# Texto
# =====================================================================


def quitar_tildes(t: str) -> str:
    """Quita tildes y diéresis; la ñ pasa a n (igual que `unaccent` en Postgres),
    porque muchas fuentes escriben MUNOZ en vez de MUÑOZ y deben casar."""
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def normalizar_texto(t: object) -> str:
    """minúsculas, sin tildes, sin signos, espacios simples."""
    if t is None or (isinstance(t, float) and math.isnan(t)):
        return ""
    s = quitar_tildes(str(t)).lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# =====================================================================
# Forma jurídica (doc 05 §1: "Razón social" — se extrae a un campo aparte)
# =====================================================================

# (patrón sobre texto ORIGINAL en minúsculas sin tildes, código). El orden
# importa: primero las formas más largas/específicas.
_FORMAS: list[tuple[str, str]] = [
    (r"sociedad limitada laboral|s\.?\s?l\.?\s?l\.?(?=\W|$)", "SLL"),
    (r"sociedad limitada unipersonal|s\.?\s?l\.?\s?u\.?(?=\W|$)", "SLU"),
    (r"sociedad limitada nueva empresa|s\.?\s?l\.?\s?n\.?\s?e\.?(?=\W|$)", "SLNE"),
    (
        r"sociedad de responsabilidad limitada|sociedad limitada"
        r"|s\.?\s?r\.?\s?l\.?(?=\W|$)|s\.?\s?l\.?(?=\W|$)",
        "SL",
    ),
    (r"sociedad anonima laboral|s\.?\s?a\.?\s?l\.?(?=\W|$)", "SAL"),
    (r"sociedad anonima unipersonal|s\.?\s?a\.?\s?u\.?(?=\W|$)", "SAU"),
    (r"sociedad anonima|s\.?\s?a\.?(?=\W|$)", "SA"),
    (
        r"sociedad cooperativa andaluza|s\.?\s?coop\.?\s?and\.?(?=\W|$)|s\.?\s?c\.?\s?a\.?(?=\W|$)",
        "SCA",
    ),
    (r"sociedad cooperativa|s\.?\s?coop\.?(?=\W|$)|cooperativa", "SCOOP"),
    (r"sociedad civil particular|s\.?\s?c\.?\s?p\.?(?=\W|$)", "SCP"),
    (r"sociedad civil|s\.?\s?c\.?(?=\W|$)", "SC"),
    (r"comunidad de bienes|c\.?\s?b\.?(?=\W|$)", "CB"),
]
_FORMAS_RE = [(re.compile(r"(?:(?<=\W)|^)(?:" + p + r")", re.IGNORECASE), c) for p, c in _FORMAS]


def extraer_forma_juridica(nombre: object) -> tuple[str | None, str]:
    """Devuelve (forma, nombre_sin_forma_normalizado).

    'Construcciones Pérez, S.L.' → ('SL', 'construcciones perez')
    """
    if nombre is None:
        return None, ""
    t = quitar_tildes(str(nombre)).lower()
    forma: str | None = None
    for rx, codigo in _FORMAS_RE:
        if rx.search(t):
            if forma is None:
                forma = codigo
            t = rx.sub(" ", t)
    return forma, normalizar_texto(t)


PALABRAS_VACIAS = {
    "de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "al", "para",
    "por", "con", "the", "and", "i",
}

# Palabras frecuentes en nombres de empresa que por sí solas NO identifican
# (doc 05 §2.3): si al quitarlas no queda ninguna palabra distintiva en
# común entre dos nombres, el aporte de la similitud se limita.
PALABRAS_GENERICAS = {
    "construcciones", "construccion", "constructora", "constructores", "reformas", "reforma",
    "servicios", "servicio", "grupo", "sur", "norte", "este", "oeste", "andalucia", "andaluza", "andaluz",
    "obras", "obra", "instalaciones", "instalacion", "instaladora", "ingenieria", "proyectos", "promociones",
    "inmobiliaria", "gestion", "soluciones", "empresa", "hermanos", "hnos", "asociados", "comercial",
    "industrial", "industriales", "tecnicas", "tecnica", "tecnicos", "multiservicios", "integrales", "integral",
    "mantenimiento", "mantenimientos", "electricidad", "electrica", "electricas", "fontaneria", "pintura", "pinturas",
    "carpinteria", "metalica", "metalicas", "estructuras", "excavaciones", "transportes", "general", "generales",
    "espana", "iberica", "global", "nuevas", "nueva", "hogar", "casa", "decoracion", "climatizacion",
    "sevilla", "huelva", "cadiz", "cordoba", "malaga", "granada", "jaen", "almeria", "madrid", "levante",
    "materiales", "suministros", "aluminios", "aluminio", "cristaleria", "rehabilitacion", "rehabilitaciones",
    "desarrollos", "inversiones", "consulting", "consultoria", "arquitectura", "diseno", "total", "plus",
}


def normalizar_nombre(nombre: object) -> str:
    """Nombre sin forma jurídica y sin palabras vacías, para comparar."""
    _, n = extraer_forma_juridica(nombre)
    return " ".join(w for w in n.split() if w not in PALABRAS_VACIAS)


def tokens_distintivos(nombre_norm: str) -> set[str]:
    return {
        w
        for w in nombre_norm.split()
        if w not in PALABRAS_GENERICAS and w not in PALABRAS_VACIAS and len(w) > 1
    }


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def similitud_nombres(a: str, b: str) -> float:
    """Mezcla 50/50 de token_set y token_sort (sobre nombres ya normalizados).

    Solo token_set daría 1,0 a 'construcciones perez' vs 'construcciones perez
    sevilla', que suelen ser empresas distintas; la mezcla lo baja a ~0,9
    (doc 05 §2.3).
    """
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    sort_a, sort_b = " ".join(sorted(ta)), " ".join(sorted(tb))
    token_sort = _ratio(sort_a, sort_b)
    inter = " ".join(sorted(ta & tb))
    t1 = (inter + " " + " ".join(sorted(ta - tb))).strip()
    t2 = (inter + " " + " ".join(sorted(tb - ta))).strip()
    token_set = max(_ratio(inter, t1), _ratio(inter, t2), _ratio(t1, t2)) if inter else _ratio(t1, t2)
    return round(0.5 * token_set + 0.5 * token_sort, 4)
