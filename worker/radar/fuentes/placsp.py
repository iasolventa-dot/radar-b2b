"""Licitaciones adjudicadas de la Plataforma de Contratación del Sector
Público (PLACSP) — tercera pieza del plan de conexión de fuentes
pendientes (2026-09-15), tras CartoCiudad y DIRCE.

Da lo que ninguna fuente conectada da hoy: **NIF real del adjudicatario**,
verificado contra entradas reales de PLACSP el 2026-09-15 (ver fixtures
en `worker/tests/fixtures/placsp/`, extraídas de la sindicación 643 —
"Licitaciones publicadas... excluyendo los contratos menores").

## Qué está verificado, y qué no

**PLACSP no tiene API REST** (confirmado 2026-09-15) — el único
mecanismo oficial es descargar ficheros ZIP mensuales (uno por
sindicación, con TODAS las licitaciones de España, sin filtro de
zona/CPV en la descarga; un mes puede pesar más de 100 MB). El parseo
(`parsear_entrada`, `es_cpv_relevante`, `provincia_de_nuts`) está probado
contra 4 entradas reales (fixtures) recuperadas descomprimiendo a mano un
ZIP que se cortó a los 278 KB en el entorno de desarrollo, dos veces —
esa parte del parseo no depende de tener el fichero completo.

`ConectorPLACSP.descubrir()` (la descarga + descompresión + recorrido de
los `.atom` internos del zip) se probó con un zip sintético en el
entorno de desarrollo (que no puede descargar el fichero real completo,
ver más abajo), y **se verificó por separado contra el fichero real de
un mes completo** desde una máquina sin esa limitación
(`worker/scripts/verificar_placsp.py`, 2026-09-15/16): 148.514.308 bytes,
47.114 `<entry>` totales, 36.189 contratos adjudicados con NIF real
extraídos, 4.515 de ellos con CPV de construcción (división 45). Las
26.964 entradas sin ningún lote con NIF+nombre válidos son, en su
mayoría, licitaciones todavía no adjudicadas ese mes o adjudicadas a una
UTE sin NIF (ver más abajo) — no un fallo del parseo: los ejemplos reales
de construcción que sí salieron (CONSTRUCTORA SAN JOSE SA, CONSTRUCCIONES
SERROT S.A....) tienen NIF de formato correcto e importes creíbles.

Sigue sin comprobar: cuántos de esos 4.515 contratos de construcción
mensuales van a UTEs (y por tanto se pierden, correctamente, por falta de
NIF real) — la verificación de arriba no desglosó ese dato específico
para CPV=45 en particular, solo el total general de la fuente.

## CPV, no CNAE

`cbc:ItemClassificationCode` usa CPV (Common Procurement Vocabulary,
taxonomía de la UE para contratación pública) — una clasificación
DISTINTA de CNAE, no traducible 1:1. La división 45 ("Trabajos de
construcción") es la que interesa al piloto; no se intenta mapear a un
código CNAE aquí — el CPV se guarda tal cual en `extra`, no se fuerza a
CNAE.

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

import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import CamposExtraidos, Conector, RegistroBruto

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

# NUTS3 (código de región de ejecución que da PLACSP en cac:RealizedLocation)
# -> nombre de provincia TAL COMO lo usa esta base de datos (municipios.provincia,
# la misma cadena exacta del INE) -- verificado contra el Reglamento (UE)
# 2019/1755 y la lista de las 52 provincias ya cargadas en `municipios`
# (2026-09-15). Baleares y Canarias son un caso especial: el INE las
# cuenta como 1 y 2 provincias respectivamente, pero NUTS3 las divide por
# isla (3 y 7 unidades) -- aquí se colapsan de vuelta a la provincia INE
# correspondiente, porque es la unidad que usa el resto de este proyecto
# (ubicacion.provincias en la interpretación del agente).
NUTS3_A_PROVINCIA: dict[str, str] = {
    "ES111": "A Coruña", "ES112": "Lugo", "ES113": "Ourense", "ES114": "Pontevedra",
    "ES120": "Asturias", "ES130": "Cantabria",
    "ES211": "Araba/Álava", "ES212": "Gipuzkoa", "ES213": "Bizkaia",
    "ES220": "Navarra", "ES230": "La Rioja",
    "ES241": "Huesca", "ES242": "Teruel", "ES243": "Zaragoza",
    "ES300": "Madrid",
    "ES411": "Ávila", "ES412": "Burgos", "ES413": "León", "ES414": "Palencia",
    "ES415": "Salamanca", "ES416": "Segovia", "ES417": "Soria", "ES418": "Valladolid", "ES419": "Zamora",
    "ES421": "Albacete", "ES422": "Ciudad Real", "ES423": "Cuenca", "ES424": "Guadalajara", "ES425": "Toledo",
    "ES431": "Badajoz", "ES432": "Cáceres",
    "ES511": "Barcelona", "ES512": "Girona", "ES513": "Lleida", "ES514": "Tarragona",
    "ES521": "Alicante/Alacant", "ES522": "Castellón/Castelló", "ES523": "Valencia/València",
    "ES531": "Illes Balears", "ES532": "Illes Balears", "ES533": "Illes Balears",
    "ES611": "Almería", "ES612": "Cádiz", "ES613": "Córdoba", "ES614": "Granada",
    "ES615": "Huelva", "ES616": "Jaén", "ES617": "Málaga", "ES618": "Sevilla",
    "ES620": "Murcia",
    "ES630": "Ciudad Autónoma de Ceuta", "ES640": "Ciudad Autónoma de Melilla",
    # Canarias: Las Palmas = Fuerteventura + Gran Canaria + Lanzarote;
    # Santa Cruz de Tenerife = El Hierro + La Gomera + La Palma + Tenerife.
    "ES703": "Santa Cruz de Tenerife", "ES704": "Las Palmas", "ES705": "Las Palmas",
    "ES706": "Santa Cruz de Tenerife", "ES707": "Santa Cruz de Tenerife",
    "ES708": "Las Palmas", "ES709": "Santa Cruz de Tenerife",
}


def provincia_de_nuts(nuts: str | None) -> str | None:
    """`None` si no hay NUTS o si es un código de nivel más ancho que
    provincia (p. ej. "ES61" sin el tercer dígito, o "ES" a secas) --
    nunca inventa una provincia a partir de un código que no la identifica
    con precisión (principio 5)."""
    if not nuts:
        return None
    return NUTS3_A_PROVINCIA.get(nuts)


# --- Conector (descarga + descubrimiento) ------------------------------
#
# URL verificada en vivo el 2026-09-15 (fuente: Ministerio de Hacienda,
# hacienda.gob.es/.../LicitacionesContratante.aspx) -- sindicación 643:
# "Licitaciones publicadas en los perfiles del contratante..., excluyendo
# los contratos menores". El fichero de un mes puede pesar más de 100 MB
# (confirmado: 148.514.308 bytes para 2025-08) -- por eso el timeout es
# mucho más largo que el de `ConectorBorme` (sumarios diarios, unos pocos
# KB cada uno).

URL_ZIP = "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_{anyo}{mes:02d}.zip"
_TAG_ENTRY = f"{{{NS['atom']}}}entry"


def _es_reintentable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)


def _entradas_de_zip(contenido_zip: bytes) -> Iterator[ET.Element]:
    """Un zip mensual puede contener MÁS DE UN fichero .atom (el manual de
    OpenPLACSP dice que cada .atom guarda como máximo 500 entries,
    encadenados entre sí) -- se procesan todos los que haya dentro, en
    el orden en que los devuelve el propio zip. `ET.iterparse` en vez de
    `ET.parse`: un fichero de un mes completo puede tener decenas de miles
    de entradas, cargarlo todo en memoria de una vez no es necesario
    cuando solo se necesita recorrerlo una vez."""
    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as zf:
        nombres_atom = sorted(n for n in zf.namelist() if n.endswith(".atom"))
        for nombre in nombres_atom:
            with zf.open(nombre) as fh:
                for _evento, elemento in ET.iterparse(fh, events=("end",)):
                    if elemento.tag == _TAG_ENTRY:
                        yield elemento
                        elemento.clear()


def _contrato_a_registro_bruto(contrato: ContratoAdjudicado) -> RegistroBruto:
    campos = CamposExtraidos(
        razon_social=contrato.adjudicatario_nombre,
        nif=contrato.adjudicatario_nif,
        provincia=provincia_de_nuts(contrato.nuts),
        extra={
            "id_licitacion": contrato.id_licitacion,
            "titulo_licitacion": contrato.titulo,
            "cpv": contrato.cpv,
            "nuts": contrato.nuts,
            "fecha_adjudicacion": contrato.fecha_adjudicacion,
            "importe_adjudicado": contrato.importe_adjudicado,
            "organo_contratante": contrato.organo_contratante_nombre,
        },
    )
    return RegistroBruto(
        fuente="placsp",
        id_externo=contrato.id_licitacion,
        url=contrato.id_licitacion,  # en PLACSP el id de la licitación YA es una URL
        payload={},  # campos_almacenables='{}' para 'placsp' (doc 03b) -- sin restricción especial, mismo caso que 'borme'
        campos=campos,
    )


class ConectorPLACSP(Conector):
    """Descubrimiento de adjudicatarios de contratos públicos, filtrado
    por CPV (sector) y NUTS resuelto a provincia (zona) — plan de conexión
    de fuentes pendientes (2026-09-15), tercera pieza.

    A diferencia de `ConectorBorme` (sumarios diarios de pocos KB), aquí
    cada llamada descarga un mes ENTERO de toda España de una vez (no hay
    forma de pedir solo una provincia o un CPV al servidor: el filtro es
    siempre posterior a la descarga, en este mismo conector) — por eso
    `descubrir` solo admite pedir un mes cada vez, no un rango de fechas
    como BORME.

    **Verificado contra un fichero real completo** (ver docstring del
    módulo): 47.114 `<entry>`, 36.189 contratos con NIF real extraídos,
    4.515 de CPV construcción, para el mes 2025-08 completo (148.514.308
    bytes) — ejecutado desde una máquina sin la limitación de red de
    este entorno de desarrollo (`worker/scripts/verificar_placsp.py`).
    """

    codigo = "placsp"
    coste_unitario_eur = 0.0  # dato abierto, gratuito (verificado 2026-09-15)

    def __init__(self, cliente: httpx.AsyncClient):
        self.cliente = cliente

    def estimar_coste(self, parametros: dict) -> float:
        return 0.0  # sin coste monetario; el "presupuesto" real es tiempo/ancho de banda

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, max=30),
        retry=retry_if_exception(_es_reintentable),
        reraise=True,
    )
    async def _descargar_zip(self, anyo: int, mes: int) -> bytes:
        url = URL_ZIP.format(anyo=anyo, mes=mes)
        # timeout largo a propósito: el fichero de un mes puede pesar más
        # de 100 MB (ver docstring del módulo) -- los 30s que basta para
        # BORME no alcanzarían ni para bajar la mitad.
        r = await self.cliente.get(url, timeout=280.0)
        r.raise_for_status()
        return r.content

    async def descubrir(self, parametros: dict, max_coste_eur: float) -> AsyncIterator[RegistroBruto]:
        """Parámetros esperados:

        - ``anyo`` / ``mes``: por defecto, el mes en curso.
        - ``provincias``: lista de nombres de provincia (p. ej. `["Sevilla"]`)
          tal como los usa `municipios.provincia` -- filtra por NUTS
          resuelto a provincia; sin este parámetro (o vacío), no filtra
          por zona (toda España).
        - ``prefijos_cpv``: por defecto `PREFIJOS_CPV_CONSTRUCCION` ("45").
        """
        hoy = datetime.now(UTC).date()
        anyo = parametros.get("anyo", hoy.year)
        mes = parametros.get("mes", hoy.month)
        provincias = set(parametros.get("provincias") or [])
        prefijos_cpv = tuple(parametros.get("prefijos_cpv") or PREFIJOS_CPV_CONSTRUCCION)

        contenido_zip = await self._descargar_zip(anyo, mes)
        for entry in _entradas_de_zip(contenido_zip):
            for contrato in parsear_entrada(entry):
                if not es_cpv_relevante(contrato.cpv, prefijos_cpv):
                    continue
                if provincias and provincia_de_nuts(contrato.nuts) not in provincias:
                    continue
                yield _contrato_a_registro_bruto(contrato)


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
