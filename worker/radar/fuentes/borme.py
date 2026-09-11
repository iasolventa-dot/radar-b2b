"""Conector BORME (Boletín Oficial del Registro Mercantil).

API de datos abiertos del BOE, verificada el 2026-09-10 contra
`https://www.boe.es/datosabiertos/documentos/APIsumarioBORME.pdf` y probada
en vivo (ver `08_registro_decisiones.md`, D-11):

- Sumario diario: ``GET https://boe.es/datosabiertos/api/borme/sumario/{AAAAMMDD}``
  (``Accept: application/json``). Devuelve, por sección, un ``item`` por
  provincia con ``url_xml`` al listado de actos de esa provincia ese día.
- Listado de actos de una provincia: ``GET {url_xml}``. Responde SIEMPRE en
  XML (el ``Accept: application/json`` no cambia el formato de este segundo
  endpoint, a diferencia del primero — comprobado en vivo). Estructura:
  ``<p class="articulo">ID - RAZON SOCIAL.</p>`` seguido de uno o varios
  ``<p class="parrafo">texto del acto</p>``.

Qué NO da el BORME: el NIF no se publica en los anuncios (solo la razón
social, el domicilio y la "hoja registral" — p. ej. ``SE156285`` — que es un
identificador del Registro Mercantil, no el NIF). El NIF hay que
confirmarlo con otra fuente (REA, web + aviso legal, consulta puntual a un
proveedor tipo e-informa). Este conector nunca inventa un NIF: lo deja
``None`` y el resto del pipeline lo completa o lo deja pendiente.

Uso principal en este proyecto (Fase 1): generar candidatos automáticos
para el golden set a partir de:

1. **Constituciones** con objeto social que menciona construcción → pool
   principal de empresas "normales" del sector.
2. **Disoluciones/extinciones** y **cambios de domicilio** cuya razón
   social sugiere construcción (heurística débil por nombre, ya que el
   BORME no repite el objeto social en estos actos) → candidatos para las
   categorías difíciles "disuelta" y "traslado" (doc 07 §6).

Todo lo que este conector no puede confirmar por sí mismo queda marcado
explícitamente como pendiente de verificación humana — nunca se rellena
con una suposición.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .base import CamposExtraidos, Conector, RegistroBruto


def _es_reintentable(exc: BaseException) -> bool:
    """404 es una respuesta válida ('sin BORME ese día') y nunca debe reintentarse.
    Solo reintentamos errores de servidor o de transporte (red, timeout)."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)

BASE_SUMARIO = "https://boe.es/datosabiertos/api/borme/sumario/{fecha}"

# Palabras que, en el OBJETO SOCIAL de una constitución, indican sector
# construcción (CNAE 41-43, doc 07 §6). Se comparan sin tildes.
PALABRAS_CONSTRUCCION_OBJETO = [
    "construccion", "obra", "edificacion", "reforma", "rehabilitacion",
    "promocion inmobiliaria", "albañileria", "fontaneria", "electricidad",
    "instalaciones electricas", "pintura", "climatizacion", "carpinteria",
    "excavacion", "demolicion", "urbanizacion", "saneamiento",
    "impermeabilizacion", "cubiertas", "estructuras metalicas", "hormigon",
    "andamios", "movimiento de tierras", "instalador",
]

# Heurística débil por RAZÓN SOCIAL para actos que no repiten el objeto
# social (disolución, cambio de domicilio). Solo sirve para proponer
# candidatos a revisión humana, nunca para confirmar sector.
PALABRAS_CONSTRUCCION_NOMBRE = [
    "construc", "obras", "reformas", "edifica", "promocion", "contratas",
    "instalaciones", "urbaniza", "hormigon", "excavac",
]

TIPOS_ACTO = {
    "constitucion": r"\bConstituci[oó]n\b",
    "disolucion": r"\bDisoluci[oó]n\b",
    "extincion": r"\bExtinci[oó]n\b",
    "cambio_domicilio": r"Cambio de domicilio social",
    "cambio_denominacion": r"Cambio de denominaci[oó]n",
    "concurso": r"\bConcurso\b",
}

_TABLA_TILDES = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")


def _sin_tildes(s: str) -> str:
    return s.translate(_TABLA_TILDES)


def _contiene_alguna(texto: str, palabras: list[str]) -> bool:
    norm = _sin_tildes(texto.lower())
    return any(_sin_tildes(p) in norm for p in palabras)


@dataclass
class ActoBorme:
    """Un acto individual ya parseado del listado de una provincia."""

    id_borme: str | None
    razon_social: str
    tipos: list[str]
    codigo_postal: str | None
    municipio: str | None
    hoja_registral: str | None
    objeto_social: str | None
    capital_eur: str | None
    administradores: list[str]
    texto_completo: str
    identificador_boletin: str
    url_html: str
    url_xml: str
    fecha_publicacion: str

    @property
    def es_candidato_construccion_por_objeto(self) -> bool:
        if not self.objeto_social:
            return False
        return _contiene_alguna(self.objeto_social, PALABRAS_CONSTRUCCION_OBJETO)

    @property
    def es_candidato_construccion_por_nombre(self) -> bool:
        return _contiene_alguna(self.razon_social, PALABRAS_CONSTRUCCION_NOMBRE)


def parsear_acto(articulo_txt: str, parrafo_txt: str) -> tuple[str | None, str]:
    """Separa el prefijo numérico BORME de la razón social en `<p class="articulo">`."""
    m = re.match(r"\s*(\d+)\s*-\s*(.+?)\.?\s*$", articulo_txt.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return None, re.sub(r"\.\s*$", "", articulo_txt.strip())


def parsear_datos_acto(parrafo_txt: str) -> dict[str, Any]:
    tipos = [
        etiqueta for etiqueta, patron in TIPOS_ACTO.items() if re.search(patron, parrafo_txt, re.IGNORECASE)
    ]

    m_cp = re.search(r"C\.?\s?P\.?:?\s*(\d{1,2}\.?\d{3})\s*\(([^)]+)\)", parrafo_txt)
    codigo_postal = municipio = None
    if m_cp:
        codigo_postal = m_cp.group(1).replace(".", "")
        municipio = m_cp.group(2).strip()

    m_hoja = re.search(r"\bH\s?([A-Z]{1,2}\s?\d+)", parrafo_txt)
    hoja_registral = re.sub(r"\s+", "", m_hoja.group(1)) if m_hoja else None

    m_obj = re.search(
        r"Objeto social:\s*(.+?)(?:\.\s*-?\s*Domicilio|\.\s*Capital|\.\s*Nombramientos|\.\s*Datos registrales|$)",
        parrafo_txt,
        re.DOTALL,
    )
    objeto_social = m_obj.group(1).strip() if m_obj else None

    m_cap = re.search(r"Capital:\s*([\d.,]+)\s*Euros", parrafo_txt)
    capital_eur = m_cap.group(1) if m_cap else None

    administradores: list[str] = []
    for patron_rol in (
        r"Adm\.\s*(?:Unico|Solid\.?|Mancom\.?)\s*:\s*([^.]+)\.",
        r"Consejero(?:\s*Delegado)?\s*:\s*([^.]+)\.",
        r"Presidente\s*:\s*([^.]+)\.",
    ):
        for m_rol in re.finditer(patron_rol, parrafo_txt):
            administradores.extend(n.strip() for n in m_rol.group(1).split(";") if n.strip())

    return {
        "tipos": tipos,
        "codigo_postal": codigo_postal,
        "municipio": municipio,
        "hoja_registral": hoja_registral,
        "objeto_social": objeto_social,
        "capital_eur": capital_eur,
        "administradores": administradores,
    }


def parsear_listado_provincia(xml_bytes: bytes, url_xml: str) -> list[ActoBorme]:
    """Parsea el XML de actos de UNA provincia (un `item` del sumario) en `ActoBorme`s."""
    root = ET.fromstring(xml_bytes)
    metadatos = root.find("metadatos")
    identificador_boletin = (
        metadatos.findtext("identificador", default="") if metadatos is not None else ""
    )
    fecha_publicacion = (
        metadatos.findtext("fecha_publicacion", default="") if metadatos is not None else ""
    )
    url_html = f"https://www.boe.es/diario_borme/txt.php?id={identificador_boletin}"

    texto = root.find("texto")
    if texto is None:
        return []

    actos: list[ActoBorme] = []
    articulo_actual: str | None = None
    for p in texto:
        clase = p.get("class")
        if clase == "articulo":
            articulo_actual = p.text or ""
        elif clase == "parrafo" and articulo_actual is not None:
            id_borme, razon_social = parsear_acto(articulo_actual, p.text or "")
            datos = parsear_datos_acto(p.text or "")
            actos.append(
                ActoBorme(
                    id_borme=id_borme,
                    razon_social=razon_social,
                    texto_completo=p.text or "",
                    identificador_boletin=identificador_boletin,
                    url_html=url_html,
                    url_xml=url_xml,
                    fecha_publicacion=fecha_publicacion,
                    **datos,
                )
            )
            articulo_actual = None
    return actos


def acto_a_registro_bruto(acto: ActoBorme) -> RegistroBruto:
    campos = CamposExtraidos(
        razon_social=acto.razon_social,
        domicilio=None,
        codigo_postal=acto.codigo_postal,
        municipio=acto.municipio,
        provincia="Sevilla",
        estado="disuelta" if "extincion" in acto.tipos or "disolucion" in acto.tipos else None,
        extra={
            "id_borme": acto.id_borme,
            "hoja_registral": acto.hoja_registral,
            "tipos_acto": acto.tipos,
            "objeto_social": acto.objeto_social,
            "capital_eur": acto.capital_eur,
            "identificador_boletin": acto.identificador_boletin,
            "administradores": acto.administradores,
        },
    )
    return RegistroBruto(
        fuente="borme",
        id_externo=acto.id_borme,
        url=acto.url_html,
        payload={
            "identificador_boletin": acto.identificador_boletin,
            "id_borme": acto.id_borme,
            "razon_social": acto.razon_social,
            "texto": acto.texto_completo,
            "fecha_publicacion": acto.fecha_publicacion,
        },
        campos=campos,
    )


class ConectorBorme(Conector):
    codigo = "borme"
    coste_unitario_eur = 0.0  # API pública y gratuita (verificado 2026-09-10)

    def __init__(self, cliente: httpx.AsyncClient):
        self.cliente = cliente

    def estimar_coste(self, parametros: dict) -> float:
        return 0.0  # sin coste monetario; el "presupuesto" real es nº de peticiones/tiempo

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, max=30),
        retry=retry_if_exception(_es_reintentable),
        reraise=True,
    )
    async def _pedir_json(self, url: str) -> dict:
        r = await self.cliente.get(url, headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, max=30),
        retry=retry_if_exception(_es_reintentable),
        reraise=True,
    )
    async def _pedir_bytes(self, url: str) -> bytes:
        r = await self.cliente.get(url, timeout=30)
        r.raise_for_status()
        return r.content

    async def _actos_de_provincia(
        self, fecha: date, provincia_titulo: str
    ) -> list[ActoBorme]:
        url_sumario = BASE_SUMARIO.format(fecha=fecha.strftime("%Y%m%d"))
        try:
            datos = await self._pedir_json(url_sumario)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return []  # sin BORME ese día (fin de semana/festivo)
            raise
        diarios = datos.get("data", {}).get("sumario", {}).get("diario", [])
        actos: list[ActoBorme] = []
        for diario in diarios:
            for seccion in diario.get("seccion", []):
                if seccion.get("codigo") != "A":
                    continue
                for item in seccion.get("item", []):
                    if item.get("titulo", "").strip().upper() != provincia_titulo.upper():
                        continue
                    xml_bytes = await self._pedir_bytes(item["url_xml"])
                    actos.extend(parsear_listado_provincia(xml_bytes, item["url_xml"]))
        return actos

    async def descubrir(
        self, parametros: dict, max_coste_eur: float
    ) -> AsyncIterator[RegistroBruto]:
        """Parámetros esperados:

        - ``provincia_titulo``: título de sección tal como lo usa el BORME (p. ej. "SEVILLA").
        - ``desde`` / ``hasta``: fechas ``date`` (por defecto, últimos 30 días).
        - ``solo_dias_laborables``: si True (por defecto), salta sábados y domingos.
        """
        provincia_titulo = parametros.get("provincia_titulo", "SEVILLA")
        hasta = parametros.get("hasta", datetime.now(UTC).date())
        desde = parametros.get("desde", hasta - timedelta(days=30))
        solo_laborables = parametros.get("solo_dias_laborables", True)

        dia = desde
        while dia <= hasta:
            if solo_laborables and dia.weekday() >= 5:
                dia += timedelta(days=1)
                continue
            for acto in await self._actos_de_provincia(dia, provincia_titulo):
                yield acto_a_registro_bruto(acto)
            dia += timedelta(days=1)
