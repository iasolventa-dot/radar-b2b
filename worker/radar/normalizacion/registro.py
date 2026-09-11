"""Normaliza un registro completo de empresa (doc 05 §1) componiendo los
módulos de campo individuales.

Punto de entrada principal del paquete `radar.normalizacion`: recibe los
`campos` de un `RegistroBruto` (o un dict equivalente) y devuelve un dict
normalizado, listo para `radar.resolucion.scoring.comparar` y para volcarse
como observaciones (capa plata).
"""

from __future__ import annotations

import math
import re

from radar.normalizacion.direccion import codigo_provincia, validar_cp
from radar.normalizacion.dominio import es_dominio_plataforma, extraer_dominio, normalizar_email
from radar.normalizacion.nif import forma_compatible_con_nif, validar_nif
from radar.normalizacion.nombre import PALABRAS_VACIAS, extraer_forma_juridica
from radar.normalizacion.telefono import normalizar_telefono


def _lista(v: object) -> list:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if x is not None and str(x).strip()]
    return [x for x in re.split(r"[;,/|]| y ", str(v)) if x.strip()]


def normalizar_registro(reg: dict) -> dict:
    """Recibe un dict con claves estándar (nif, razon_social, nombre_comercial,
    forma_juridica, telefono(s), email(s), web, direccion, cp, municipio,
    provincia, lat, lon, place_id) y devuelve una versión normalizada.

    Acepta tanto los nombres en singular (``telefono``, ``email``, como los
    produce `radar.fuentes.base.CamposExtraidos`) como en plural
    (``telefonos``, ``emails``).
    """
    forma_rs, rs_norm = extraer_forma_juridica(reg.get("razon_social"))
    _, nc_norm = extraer_forma_juridica(reg.get("nombre_comercial"))
    nif = validar_nif(reg.get("nif"))
    telefonos = [normalizar_telefono(t) for t in _lista(reg.get("telefonos") or reg.get("telefono"))]
    emails = [normalizar_email(e) for e in _lista(reg.get("emails") or reg.get("email"))]
    web = reg.get("web")
    dominio = extraer_dominio(web)
    host = str(web).lower() if web else None
    if dominio and es_dominio_plataforma(dominio, host):
        dominio_valido = None
    else:
        dominio_valido = dominio
    if not dominio_valido:  # si no hay web, usar el dominio de un email corporativo
        for e in emails:
            if e["valido"] and not e["proveedor_gratuito"] and not es_dominio_plataforma(e["dominio"]):
                dominio_valido = extraer_dominio(e["email"])
                break
    forma = (
        str(reg.get("forma_juridica")).upper().replace(".", "").replace(" ", "")
        if reg.get("forma_juridica") and str(reg.get("forma_juridica")) != "nan"
        else None
    ) or forma_rs
    cp = validar_cp(reg.get("cp"), reg.get("provincia"))
    return {
        "nif": nif["nif"] or None,
        "nif_valido": nif["valido"] if nif["nif"] else None,
        "nif_tipo": nif["tipo"],
        "nif_aviso": nif["aviso"] if nif["nif"] else None,
        "persona_fisica": nif["persona_fisica"],
        "razon_social": reg.get("razon_social"),
        "nombre_comercial": reg.get("nombre_comercial"),
        "nombre_norm": " ".join(w for w in rs_norm.split() if w not in PALABRAS_VACIAS),
        "comercial_norm": " ".join(w for w in nc_norm.split() if w not in PALABRAS_VACIAS),
        "forma_juridica": forma,
        "forma_coherente_nif": forma_compatible_con_nif(forma, nif["nif"]) if nif["valido"] else None,
        "telefonos": sorted({t["e164"] for t in telefonos if t["valido"]}),
        "telefonos_especiales": sorted(
            {t["e164"] for t in telefonos if t["valido"] and t["tipo"] == "especial"}
        ),
        "telefonos_invalidos": [
            str(x)
            for x, t in zip(_lista(reg.get("telefonos") or reg.get("telefono")), telefonos)
            if not t["valido"]
        ],
        "emails": sorted({e["email"] for e in emails if e["valido"]}),
        "emails_personales": sorted(
            {e["email"] for e in emails if e["valido"] and not e["es_generico"]}
        ),
        "dominio": dominio_valido,
        "cp": cp["cp"],
        "cp_aviso": cp["aviso"],
        "provincia": reg.get("provincia") or cp["provincia_cp"],
        "cod_provincia": (cp["cp"] or "")[:2] or codigo_provincia(reg.get("provincia")),
        "municipio": reg.get("municipio"),
        "lat": reg.get("lat"),
        "lon": reg.get("lon"),
        "place_id": reg.get("place_id") if reg.get("place_id") and str(reg.get("place_id")) != "nan" else None,
    }
