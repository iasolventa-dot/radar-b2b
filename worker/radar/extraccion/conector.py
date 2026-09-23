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

import dataclasses

import httpx

from radar.extraccion import reglas
from radar.extraccion.descarga import descargar, encontrar_enlaces_legales
from radar.extraccion.llm import RespuestaExtraccionLLM, extraer_con_llm
from radar.fuentes.base import CamposExtraidos, RegistroBruto
from radar.normalizacion.dominio import extraer_dominio

MAX_PAGINAS_LEGALES = 3


async def _texto_relevante(cliente: httpx.AsyncClient, url_portada: str) -> tuple[str, list[str]]:
    """Descarga la portada y hasta `MAX_PAGINAS_LEGALES` páginas legales
    enlazadas desde ella; devuelve el texto visible concatenado y las URLs
    que sí se pudieron leer (para guardarlas como evidencia, doc 04 §3)."""
    portada = await descargar(url_portada, cliente)
    if portada is None:
        return "", []
    textos = [reglas.html_a_texto(portada.html)]
    urls = [url_portada]
    for enlace in encontrar_enlaces_legales(portada.html, url_portada)[:MAX_PAGINAS_LEGALES]:
        pagina = await descargar(enlace, cliente)
        if pagina:
            textos.append(reglas.html_a_texto(pagina.html))
            urls.append(enlace)
    return "\n\n".join(textos), urls


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
    texto, urls = await _texto_relevante(cliente, url_portada)
    if not texto:
        return None
    return registro_desde_texto(texto, urls, url_portada, dominio)


# Una web de empresa tiene unos pocos teléfonos/emails; un directorio o
# portal (listados de "fontaneros en X") tiene decenas. Visto en vivo
# 2026-09-23: instaladoresdemadrid.com se guardó como UNA empresa con 100
# teléfonos y 100 emails de otros negocios. Estos umbrales cortan eso sin
# afectar a empresas reales con varias delegaciones (HomeServe: 5 y 4).
MAX_TELEFONOS_WEB_EMPRESA = 8
MAX_EMAILS_WEB_EMPRESA = 8


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

    return RegistroBruto(
        fuente="web_empresa",
        id_externo=None,
        url=url_portada,
        payload={"urls_consultadas": urls, "reglas": dataclasses.asdict(resultado_reglas), "llm": resultado_llm_dict},
        campos=campos,
    )
