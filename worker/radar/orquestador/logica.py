"""Lógica pura del orquestador: nada de aquí toca la base de datos, para
poder testearlo sin Postgres (`worker/tests/unit/test_orquestador.py`). Las
funciones que sí necesitan la BD (cargar candidatos, escribir) viven en
`bd.py`; `procesar.py` combina ambas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from radar.fuentes.base import CamposExtraidos
from radar.resolucion.scoring import comparar
from radar.verificacion.confianza import ResultadoConsolidacion

AccionResolucion = Literal["vincular", "crear", "crear_y_revisar"]


def campos_a_dict_normalizacion(campos: CamposExtraidos) -> dict:
    """`CamposExtraidos` (contrato de los conectores, doc 02 §5) → dict de
    entrada de `radar.normalizacion.registro.normalizar_registro`."""
    return {
        "nif": campos.nif,
        "razon_social": campos.razon_social,
        "nombre_comercial": campos.nombre_comercial,
        "forma_juridica": campos.forma_juridica,
        "telefonos": campos.telefonos,
        "emails": campos.emails,
        "web": campos.web,
        "cp": campos.codigo_postal,
        "provincia": campos.provincia,
        "municipio": campos.municipio,
        "lat": campos.lat,
        "lon": campos.lon,
        "place_id": campos.extra.get("place_id"),
    }


@dataclass
class DecisionResolucion:
    accion: AccionResolucion
    empresa_id: str | None  # a la que vincular, solo si accion == "vincular"
    mejor_candidato_id: str | None
    puntuacion: float | None
    resultado_comparacion: dict | None


def decidir_resolucion(
    campos_norm: dict,
    candidatos: list[dict],
    telefonos_compartidos: set[str] | None = None,
) -> DecisionResolucion:
    """Puntúa `campos_norm` (el registro nuevo, ya normalizado) contra cada
    candidato de bloqueo (dicts con la misma forma, más la clave
    ``empresa_id`` — los produce `bd.cargar_registro_empresa_normalizado`)
    y decide qué hacer, siguiendo doc 05 §2.4.

    El arbitraje LLM de la franja "revisión" (doc 05 §2.5) todavía no está
    conectado (es la pieza del agente, tarea #21): mientras tanto, para no
    perder ni bloquear datos, "revisión" se resuelve como **crear una
    empresa nueva y además dejar un `candidatos_duplicado` pendiente** que
    apunta al mejor candidato — si más adelante se confirma que son la
    misma, se fusiona con `fusiones` (que ya está pensado para poder
    deshacerse). Es una decisión de este proyecto, no del doc 05.
    """
    if not candidatos:
        return DecisionResolucion("crear", None, None, None, None)

    evaluados = [(c["empresa_id"], comparar(campos_norm, c, telefonos_compartidos)) for c in candidatos]
    mejor_id, mejor = max(evaluados, key=lambda par: par[1]["puntuacion"])

    if mejor["decision"] == "misma":
        return DecisionResolucion("vincular", mejor_id, mejor_id, mejor["puntuacion"], mejor)
    if mejor["decision"] == "revision":
        return DecisionResolucion("crear_y_revisar", None, mejor_id, mejor["puntuacion"], mejor)
    return DecisionResolucion("crear", None, mejor_id, mejor["puntuacion"], mejor)


def combinar_dimension_identidad(
    nif: ResultadoConsolidacion | None, razon_social: ResultadoConsolidacion | None
) -> float:
    """Confianza de "identidad" para `calcular_confianza_global` (doc 05
    §6: "identidad (NIF + razón social)"): el doc no da una fórmula exacta
    de cómo combinar las dos, así que se promedian las que estén
    disponibles (ninguna disponible → 0.0)."""
    valores = [r.ganador.confianza_efectiva for r in (nif, razon_social) if r and r.ganador]
    return round(sum(valores) / len(valores), 4) if valores else 0.0


def combinar_dimension_contacto(
    telefono: ResultadoConsolidacion | None, email: ResultadoConsolidacion | None
) -> float:
    """Doc 05 §6: "contacto (mejor teléfono o email genérico)" → el máximo
    de los dos, no el promedio."""
    valores = [r.ganador.confianza_efectiva for r in (telefono, email) if r and r.ganador]
    return max(valores) if valores else 0.0


def texto_representativo(observaciones: list[dict], valor_norm: str | None) -> str | None:
    """De las observaciones de un campo, el `valor_original` de la que
    respalda `valor_norm` con más confianza (empate → más reciente).
    Se usa para escribir en `empresas.razon_social` / `nombre_comercial`
    el texto legible (con mayúsculas y forma jurídica) del valor que ganó
    la consolidación — `consolidar_campo` solo conoce el `valor_norm`
    (sin forma jurídica, en minúsculas), que no es el que se quiere
    mostrar."""
    if not valor_norm:
        return None
    candidatas = [o for o in observaciones if o.get("valor_norm") == valor_norm and o.get("valor_original")]
    if not candidatas:
        return None
    mejor = max(candidatas, key=lambda o: (o.get("confianza_fuente") or 0.0, o["observado_en"]))
    return mejor["valor_original"]
