"""Conector de enriquecimiento web (doc 02 paso 5, doc 04 §3): dado el
dominio/URL de la web de una empresa, descarga portada + aviso legal /
contacto, extrae con reglas (y LLM de respaldo si faltan campos) y produce
un `RegistroBruto` de fuente `web_empresa`, listo para
`radar.orquestador.procesar_registro`.

A diferencia de `radar.fuentes.borme` (que DESCUBRE candidatos nuevos),
esto ENRIQUECE una empresa cuya web ya se conoce — hoy se invoca a mano;
conectarlo automáticamente a "empresas con dominio pero sin NIF
confirmado" es trabajo del agente (tarea #21, doc 07 §4: "Empresas sin
NIF: buscar la web → aviso legal").
"""

from __future__ import annotations

import asyncio
import dataclasses
import re

import httpx

from radar.extraccion import reglas
from radar.extraccion.descarga import descargar, encontrar_enlaces_legales
from radar.extraccion.llm import RespuestaExtraccionLLM, extraer_con_llm
from radar.fuentes.base import CamposExtraidos, RegistroBruto
from radar.normalizacion.dominio import extraer_dominio

MAX_PAGINAS_LEGALES = 4


_RX_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RX_DESCRIPCION = re.compile(
    r"<meta[^>]+(?:name|property)=[\"'](?:description|og:description)[\"'][^>]*content=[\"']([^\"']*)", re.IGNORECASE
)


def _limpiar_meta(texto: str | None) -> str | None:
    return re.sub(r"\s+", " ", texto).strip()[:300] or None if texto else None


def metadatos_portada(html: str) -> dict[str, str | None]:
    """Título y meta-descripción: lo que la empresa dice de sí misma en una
    frase. Lo usa el filtro de relevancia (`radar.agente.relevancia`)."""
    titulo = _RX_TITULO.search(html)
    descripcion = _RX_DESCRIPCION.search(html)
    return {
        "titulo_web": _limpiar_meta(titulo.group(1)) if titulo else None,
        "descripcion_web": _limpiar_meta(descripcion.group(1)) if descripcion else None,
    }


async def leer_texto_web(cliente: httpx.AsyncClient, url_portada: str) -> str:
    """Solo el texto (portada + aviso legal/contacto/equipo): para comprobar si
    un dato concreto aparece en la web de una empresa (`resolver_dudas`)."""
    texto, _, _ = await _texto_relevante(cliente, url_portada)
    return texto


async def _texto_relevante(cliente: httpx.AsyncClient, url_portada: str) -> tuple[str, list[str], dict[str, str | None]]:
    """Descarga la portada y hasta `MAX_PAGINAS_LEGALES` páginas legales
    enlazadas desde ella; devuelve el texto visible concatenado, las URLs que
    sí se pudieron leer (evidencia, doc 04 §3) y los metadatos de la portada."""
    portada = await descargar(url_portada, cliente)
    if portada is None:
        return "", [], {}
    textos = [reglas.html_a_texto(portada.html)]
    urls = [url_portada]
    for enlace in encontrar_enlaces_legales(portada.html, url_portada)[:MAX_PAGINAS_LEGALES]:
        pagina = await descargar(enlace, cliente)
        if pagina:
            textos.append(reglas.html_a_texto(pagina.html))
            urls.append(enlace)
    return "\n\n".join(textos), urls, metadatos_portada(portada.html)


def campos_desde_reglas(r: reglas.DatosLegalesExtraidos, dominio: str | None) -> CamposExtraidos:
    razon = r.razones_sociales[0] if r.razones_sociales else None
    cp = r.codigos_postales[0] if r.codigos_postales else None
    email_del_dominio = next((e.email for e in r.emails if e.del_dominio), None)
    return CamposExtraidos(
        razon_social=razon,
        nif=r.nif_titular,
        codigo_postal=cp,
        telefonos=list(r.telefonos),
        # Doc 04 §2 (tabla resumen): "Email... Evitar como única fuente:
        # adivinar patrones (info@...)" — no adivinamos nada, pero si hay
        # varios emails preferimos el del propio dominio como principal.
        emails=[email_del_dominio] if email_del_dominio else [e.email for e in r.emails],
        web=dominio,
        extra={
            "hoja_registral": r.registro_mercantil.hoja if r.registro_mercantil else None,
            "registro_mercantil": dataclasses.asdict(r.registro_mercantil) if r.registro_mercantil else None,
            "avisos": r.avisos,
            "personas_contacto": list(r.personas),
            "fuente_dato": "reglas",
        },
    )


def campos_desde_llm(base: CamposExtraidos, llm_resp: RespuestaExtraccionLLM) -> CamposExtraidos:
    """Fusiona la respuesta del LLM sobre `base` (lo que ya habían
    encontrado las reglas): si el LLM da un valor para un campo, GANA —
    precisamente se le llamó porque las reglas tenían dudas en algún campo
    (NIF ambiguo entre varios candidatos, razón social o domicilio
    ausentes), y su lectura es sobre el mismo texto pero con criterio para
    descartar menciones de agencia/grupo/cliente que un regex no distingue.
    Si el LLM deja un campo en `null` (doc de prompt: "si un dato no
    aparece, null" — nunca inventa), se conserva lo que ya tenía `base`.
    """
    t = llm_resp.titular
    personas = list(base.extra.get("personas_contacto") or [])
    vistos = {p["nombre"].lower() for p in personas}
    for p in llm_resp.personas:
        nombre = (p.nombre or "").strip()
        if len(nombre.split()) >= 2 and nombre.lower() not in vistos and len(personas) < MAX_PERSONAS_POR_WEB:
            vistos.add(nombre.lower())
            personas.append({"nombre": nombre, "cargo": (p.cargo or "Contacto").strip()[:MAX_LONGITUD_CARGO]})
    return CamposExtraidos(
        razon_social=reglas.limpiar_razon_social(t.razon_social) or base.razon_social,
        nombre_comercial=t.nombre_comercial or base.nombre_comercial,
        nif=t.nif or base.nif,
        domicilio=t.domicilio or base.domicilio,
        codigo_postal=t.codigo_postal or base.codigo_postal,
        municipio=t.municipio or base.municipio,
        telefonos=t.telefonos or base.telefonos,
        emails=t.emails or base.emails,
        web=base.web,
        extra={
            **base.extra,
            "personas_contacto": personas,
            "fuente_dato": "llm",
            "confianza_llm": llm_resp.confianza,
            "notas_llm": llm_resp.notas,
            "otras_empresas_mencionadas": [e.model_dump() for e in llm_resp.otras_empresas_mencionadas],
        },
    )


async def enriquecer_desde_web(
    cliente: httpx.AsyncClient, url_portada: str, dominio: str | None = None
) -> RegistroBruto | None:
    """`None` si no se pudo leer nada (robots.txt lo prohíbe, la web está
    caída…) — el llamador decide qué hacer (reintentar más tarde, marcar
    la empresa sin enriquecer).
    """
    dominio = dominio or extraer_dominio(url_portada)
    texto, urls, meta = await _texto_relevante(cliente, url_portada)
    if not texto:
        return None
    # En un hilo: puede llamar al LLM (síncrono) y no debe bloquear las otras
    # webs que se están leyendo en paralelo (`enriquecer_varias`).
    registro = await asyncio.to_thread(registro_desde_texto, texto, urls, url_portada, dominio)
    if registro is not None:
        registro.campos.extra.update({k: v for k, v in meta.items() if v})
    return registro


# Una web de empresa tiene unos pocos teléfonos/emails; un directorio o
# portal (listados de "fontaneros en X") tiene decenas. Visto en vivo
# 2026-09-23: instaladoresdemadrid.com se guardó como UNA empresa con 100
# teléfonos y 100 emails de otros negocios. Estos umbrales cortan eso sin
# afectar a empresas reales con varias delegaciones (HomeServe: 5 y 4).
MAX_TELEFONOS_WEB_EMPRESA = 8
MAX_EMAILS_WEB_EMPRESA = 8


# Organismos públicos (ayuntamientos, juntas...) no son empresas objetivo:
# visto en vivo 2026-09-24, la web de un ayuntamiento entró como "empresa" con
# 15 concejales como personas de contacto.
_RX_ORGANISMO_PUBLICO = re.compile(
    r"^\s*(?:excmo\.?\s+|ilmo\.?\s+)?(?:ayuntamiento|junta\s+de|diputaci[oó]n|consejer[ií]a|gobierno\s+de|"
    r"comunidad\s+de\s+madrid|generalitat|xunta|cabildo|mancomunidad|universidad|ministerio|delegaci[oó]n\s+del\s+gobierno)\b",
    re.IGNORECASE,
)
MAX_PERSONAS_POR_WEB = 5
MAX_LONGITUD_CARGO = 60


def es_organismo_publico(nombre: str | None) -> bool:
    return bool(nombre and _RX_ORGANISMO_PUBLICO.search(nombre))


def parece_directorio(r: reglas.DatosLegalesExtraidos) -> bool:
    return len(set(r.telefonos)) > MAX_TELEFONOS_WEB_EMPRESA or len({e.email for e in r.emails}) > MAX_EMAILS_WEB_EMPRESA


def registro_desde_texto(texto: str, urls: list[str], url_portada: str, dominio: str | None) -> RegistroBruto | None:
    """Reglas (+ LLM si faltan campos) sobre un texto ya obtenido. Separado de
    `enriquecer_desde_web` para reutilizarlo cuando el texto lo ha descargado
    otro sistema (p. ej. el rastreador de Apify) en vez de `descargar()`.
    `None` si la página parece un directorio/portal (`parece_directorio`):
    no es la web de UNA empresa y no se puede atribuir su contenido a nadie."""
    resultado_reglas = reglas.extraer(texto, dominio)
    if parece_directorio(resultado_reglas):
        return None
    campos = campos_desde_reglas(resultado_reglas, dominio)

    resultado_llm_dict = None
    if resultado_reglas.necesita_llm:
        resultado = extraer_con_llm(texto, dominio, resultado_reglas)
        if resultado.respuesta:
            campos = campos_desde_llm(campos, resultado.respuesta)
            resultado_llm_dict = resultado.respuesta.model_dump()

    if es_organismo_publico(campos.razon_social) or es_organismo_publico(campos.nombre_comercial):
        return None

    return RegistroBruto(
        fuente="web_empresa",
        id_externo=None,
        url=url_portada,
        payload={"urls_consultadas": urls, "reglas": dataclasses.asdict(resultado_reglas), "llm": resultado_llm_dict},
        campos=campos,
    )


async def enriquecer_varias(
    cliente: httpx.AsyncClient, urls: list[str], concurrencia: int = 5
) -> dict[str, RegistroBruto | None]:
    """Lee varias webs a la vez (hasta `concurrencia`): cada web tarda de 1 a
    9 s y una búsqueda lee 15-20 -- en serie eran minutos. Solo descarga y
    extrae; procesar los registros (BD) lo hace después quien llama, en serie."""
    semaforo = asyncio.Semaphore(concurrencia)

    async def una(url: str) -> tuple[str, RegistroBruto | None]:
        async with semaforo:
            try:
                return url, await enriquecer_desde_web(cliente, url)
            except Exception:  # noqa: BLE001 -- una web rota no debe parar las demás
                return url, None

    return dict(await asyncio.gather(*(una(u) for u in dict.fromkeys(urls))))
