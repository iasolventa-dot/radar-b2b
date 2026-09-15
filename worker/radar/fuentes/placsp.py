"""Parseo de licitaciones adjudicadas de la Plataforma de Contratación del
Sector Público (PLACSP) — tercera pieza del plan de conexión de fuentes
pendientes (2026-09-15), tras CartoCiudad y DIRCE.

Da lo que ninguna fuente conectada da hoy: **NIF real del adjudicatario**,
verificado contra entradas reales de PLACSP el 2026-09-15 (ver fixtures
en `worker/tests/fixtures/placsp/`, extraídas de la sindicación 643 —
"Licitaciones publicadas... excluyendo los contratos menores").

## Alcance de esta entrega — solo el parser, no el conector completo

A diferencia de CartoCiudad y DIRCE (donde se entregó la pieza completa,
descarga + escritura en BD), aquí solo se entrega el **parseo** de una
`<entry>` CODICE ya en memoria, probado contra 4 entradas reales
guardadas como fixtures. No se entrega el conector de descubrimiento
(descargar los ficheros ZIP mensuales, seguir la cadena `<link rel="next">`
entre ficheros .atom, filtrar por fecha) por un motivo concreto y
verificado, no por pereza: **PLACSP no tiene API REST** (confirmado
2026-09-15) — el único mecanismo oficial es descargar ficheros ZIP
mensuales (uno por sindicación, ~decenas de MB cada uno, con TODAS las
licitaciones de España, sin filtro de zona/CPV en la descarga). Al
intentar verificar esa descarga completa desde este entorno, la conexión
se truncaba siempre en el mismo punto exacto (278 KB) en dos intentos
distintos — no pude confirmar un ciclo de descarga íntegro de principio a
fin, así que no lo entrego como si funcionara: mejor una pieza más
pequeña bien probada que un conector grande sin verificar de verdad.

Lo que SÍ se pudo verificar con lo recuperado parcialmente (descomprimiendo
el flujo deflate a mano, sin necesitar el fichero completo): la estructura
real de las entradas, incluido que una licitación con varios lotes trae
varios `cac:TenderResult`, cada uno con su propio `cac:WinningParty` —
verificado con una licitación real de 3 lotes y 3 adjudicatarios
distintos (fixture `entrada_multiples_lotes.xml`).

## CPV, no CNAE

`cbc:ItemClassificationCode` usa CPV (Common Procurement Vocabulary,
taxonomía de la UE para contratación pública) — una clasificación
DISTINTA de CNAE, no traducible 1:1. La división 45 ("Trabajos de
construcción") es la que interesa al piloto; no se intenta mapear a un
código CNAE aquí — quien reciba un `ContratoAdjudicado` decide qué hacer
con el CPV (guardarlo tal cual como observación, no forzarlo a CNAE).

## Un hallazgo real al construir las fixtures de prueba

El único ganador de CPV de construcción que se pudo recuperar en la
verificación es una **UTE** (Unión Temporal de Empresas, muy habitual en
obra pública grande) — PLACSP la identifica con `schemeName="OTROS"` y un
id interno, no con un NIF real. `parsear_entrada` no la confunde con un
NIF: sin NIF, ese lote se omite (nunca inventar, principio 5), aunque el
resto de los datos estén completos. Quien construya el conector de
descubrimiento sobre este parser debe saber que una fracción real de
adjudicaciones de construcción quedará así fuera — es lo correcto, no un
defecto a corregir sumando un identificador que no es un NIF.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cac-place-ext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
}

# CPV división 45 = "Trabajos de construcción" -- verificado contra
# entradas reales de PLACSP el 2026-09-15 (10 de 70 entradas recuperadas
# tenían un ItemClassificationCode que empieza por "45").
PREFIJOS_CPV_CONSTRUCCION: tuple[str, ...] = ("45",)


@dataclass
class ContratoAdjudicado:
    """Un lote adjudicado (una licitación con varios lotes produce una
    instancia por lote — `parsear_entrada` siempre devuelve una lista,
    nunca "el primer ganador", precisamente para no perder los demás)."""

    id_licitacion: str | None
    titulo: str | None
    cpv: str | None
    nuts: str | None  # código NUTS del lugar de ejecución, p. ej. "ES618" (Sevilla)
    fecha_adjudicacion: str | None
    importe_adjudicado: float | None
    adjudicatario_nif: str
    adjudicatario_nombre: str
    organo_contratante_nombre: str | None


def es_cpv_relevante(cpv: str | None, prefijos: tuple[str, ...] = PREFIJOS_CPV_CONSTRUCCION) -> bool:
    """Mismo papel que `radar.fuentes.borme._coincide_sector`, pero sobre
    CPV en vez de objeto social: decide si vale la pena procesar esta
    licitación para el piloto de construcción."""
    if not cpv:
        return False
    return any(cpv.startswith(p) for p in prefijos)


def _texto(el: ET.Element | None, ruta: str) -> str | None:
    if el is None:
        return None
    return el.findtext(ruta, namespaces=NS)


def _nif_de_party(party: ET.Element) -> str | None:
    """El NIF vive en un `cac:PartyIdentification` cuyo `cbc:ID` tiene
    `schemeName="NIF"` -- un `cac:Party`/`cac:WinningParty` puede tener
    VARIOS `PartyIdentification` (NIF, ID_PLATAFORMA...), así que hay que
    comprobar el atributo, no asumir que el primero es el NIF."""
    for ident in party.findall("cac:PartyIdentification", NS):
        id_el = ident.find("cbc:ID", NS)
        if id_el is not None and id_el.get("schemeName") == "NIF":
            return id_el.text
    return None


def parsear_entrada(entry: ET.Element) -> list[ContratoAdjudicado]:
    """Extrae un `ContratoAdjudicado` por cada lote adjudicado de esta
    `<entry>` -- una lista vacía si la licitación todavía no tiene ningún
    ganador (estado "PUB", solo publicada) o si a algún lote le falta el
    NIF/nombre del adjudicatario (nunca inventar, principio 5: ese lote
    se omite, no se inventa un valor ni se cuenta como si tuviera ganador).
    """
    id_licitacion = _texto(entry, "atom:id")
    titulo = _texto(entry, "atom:title")
    cpv = _texto(entry, ".//cac:RequiredCommodityClassification/cbc:ItemClassificationCode")
    nuts = _texto(entry, ".//cac:RealizedLocation/cbc:CountrySubentityCode")
    organo = _texto(entry, ".//cac-place-ext:LocatedContractingParty/cac:Party/cac:PartyName/cbc:Name")

    contratos: list[ContratoAdjudicado] = []
    for resultado in entry.findall(".//cac:TenderResult", NS):
        ganador = resultado.find("cac:WinningParty", NS)
        if ganador is None:
            continue
        nif = _nif_de_party(ganador)
        nombre = _texto(ganador, "cac:PartyName/cbc:Name")
        if not nif or not nombre:
            continue  # nunca inventar (principio 5): sin NIF+nombre, se omite el lote

        importe_texto = _texto(
            resultado, "cac:AwardedTenderedProject/cac:LegalMonetaryTotal/cbc:PayableAmount"
        )
        try:
            importe = float(importe_texto) if importe_texto else None
        except ValueError:
            importe = None

        contratos.append(
            ContratoAdjudicado(
                id_licitacion=id_licitacion,
                titulo=titulo,
                cpv=cpv,
                nuts=nuts,
                fecha_adjudicacion=_texto(resultado, "cbc:AwardDate"),
                importe_adjudicado=importe,
                adjudicatario_nif=nif,
                adjudicatario_nombre=nombre,
                organo_contratante_nombre=organo,
            )
        )
    return contratos
