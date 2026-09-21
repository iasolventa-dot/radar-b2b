"""Extracción de datos desde HTML no estructurado (doc 02 §5-6, doc 04 §3).

Dos niveles, siempre en este orden:
1. `radar.extraccion.reglas` — regex de NIF, teléfonos, emails en el aviso
   legal — barato y determinista.
2. `radar.extraccion.llm` — solo si faltan campos tras las reglas
   (`DatosLegalesExtraidos.necesita_llm`): modelo rápido/barato con salida
   estructurada (doc 07 §2, prompt #3 de la skill `agente-busqueda-empresas`).

`radar.extraccion.descarga` resuelve robots.txt, caché y enlaces a
aviso legal/contacto; `radar.extraccion.conector` junta todo en un
`RegistroBruto` de fuente `web_empresa`, listo para
`radar.orquestador.procesar_registro`.
"""

from radar.extraccion.conector import enriquecer_desde_web, registro_desde_texto
from radar.extraccion.reglas import DatosLegalesExtraidos, extraer

__all__ = ["DatosLegalesExtraidos", "enriquecer_desde_web", "extraer", "registro_desde_texto"]
