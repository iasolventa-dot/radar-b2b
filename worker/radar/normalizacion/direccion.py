"""Normalización de código postal, provincia y distancia geográfica (doc 05 §1).

La geocodificación completa (CartoCiudad) es una pieza de Fase 2 aparte
(doc 02 §3); este módulo cubre lo que se puede validar sin llamar a un
servicio externo: coherencia CP↔provincia y distancia entre coordenadas.
"""

from __future__ import annotations

import math
import re

from radar.normalizacion.nombre import normalizar_texto

PROVINCIAS = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz",
    "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla",
    "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}
_ALIAS_PROVINCIA = {
    "araba": "01", "alava": "01", "vitoria": "01", "alacant": "03", "baleares": "07", "islas baleares": "07",
    "balears": "07", "mallorca": "07", "coruna": "15", "la coruna": "15", "a coruna": "15", "gerona": "17",
    "guipuzcoa": "20", "lerida": "25", "rioja": "26", "orense": "32", "principado de asturias": "33",
    "gran canaria": "35", "tenerife": "38", "santa cruz de tenerife": "38", "castello": "12",
    "castellon de la plana": "12", "valencia": "46", "vizcaya": "48", "nafarroa": "31",
    "comunidad foral de navarra": "31", "comunidad de madrid": "28", "region de murcia": "30",
}


def codigo_provincia(nombre: object) -> str | None:
    n = normalizar_texto(nombre)
    if not n:
        return None
    for cod, nom in PROVINCIAS.items():
        if normalizar_texto(nom) == n:
            return cod
    return _ALIAS_PROVINCIA.get(n)


def validar_cp(cp: object, provincia: object = None) -> dict:
    """Arregla el cero inicial perdido por Excel (4001 → 04001) y comprueba la provincia."""
    r: dict = {"cp": None, "valido": False, "provincia_cp": None, "coherente_provincia": None, "aviso": None}
    if cp is None or (isinstance(cp, float) and math.isnan(cp)):
        return r
    s = str(int(cp)) if isinstance(cp, float) and cp.is_integer() else re.sub(r"\D", "", str(cp))
    if len(s) == 4:
        s = "0" + s
        r["aviso"] = "cero inicial restaurado"
    if not re.fullmatch(r"(0[1-9]|[1-4]\d|5[0-2])\d{3}", s):
        r["aviso"] = "código postal no válido"
        return r
    r.update(cp=s, valido=True, provincia_cp=PROVINCIAS[s[:2]])
    if provincia:
        cod = codigo_provincia(provincia)
        if cod:
            r["coherente_provincia"] = cod == s[:2]
            if not r["coherente_provincia"]:
                r["aviso"] = f"CP de {PROVINCIAS[s[:2]]} pero provincia indicada '{provincia}'"
    return r


def distancia_m(lat1: object, lon1: object, lat2: object, lon2: object) -> float | None:
    """Distancia de Haversine en metros, o None si falta alguna coordenada."""
    try:
        f_lat1, f_lon1, f_lat2, f_lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    if any(math.isnan(x) for x in (f_lat1, f_lon1, f_lat2, f_lon2)):
        return None
    r_tierra = 6371000.0
    p1, p2 = math.radians(f_lat1), math.radians(f_lat2)
    dp, dl = math.radians(f_lat2 - f_lat1), math.radians(f_lon2 - f_lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_tierra * math.asin(math.sqrt(a))
