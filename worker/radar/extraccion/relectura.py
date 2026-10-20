"""Relectura de las webs de empresas ya guardadas con el extractor corregido
(2026-10-20): antes se leía la página que daba Google (un artículo, un
proyecto) y se guardaban sus teléfonos, emails y personas, aunque fueran de
otros (hoteles extranjeros, otra empresa, fichas de equipo mal emparejadas).

Criterio (trazabilidad: nada se borra):
- Lo nuevo que da la relectura se añade como evidencia normal
  (`procesar_registro` con la empresa como destino).
- Un teléfono, email o cargo se retira (canal `invalido`, observación o cargo
  `vigente = false`) SOLO si toda su evidencia vigente viene de la web
  corporativa y la relectura de esa misma web ya no lo encuentra. Lo que
  confirma otra fuente (Maps, Places, Facebook, BORME...) no se toca.
- Si la web no se puede leer, no se toca nada de esa empresa.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from radar.fuentes.base import RegistroBruto

FUENTE_WEB = "Web corporativa (aviso legal, contacto)"


def digitos_telefono(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")[-9:]


def nombre_plano(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", plano).strip()


@dataclass
class LeidoEnWeb:
    """Lo que la relectura encuentra en la web (portada + legales + equipo)."""

    telefonos: set[str] = field(default_factory=set)  # 9 últimas cifras
    emails: set[str] = field(default_factory=set)
    personas: set[str] = field(default_factory=set)  # nombres planos

    @classmethod
    def de_registro(cls, registro: RegistroBruto) -> LeidoEnWeb:
        reglas = (registro.payload or {}).get("reglas") or {}
        telefonos = list(registro.campos.telefonos or [])
        # Todos los españoles que vieron las reglas (los extranjeros ya se
        # descartaron en campos.telefonos si había alguno español).
        telefonos += [t for t in reglas.get("telefonos") or [] if str(t).startswith("+34")]
        emails = list(registro.campos.emails or []) + [e.get("email", "") for e in reglas.get("emails") or []]
        personas = [p.get("nombre", "") for p in registro.campos.extra.get("personas_contacto") or []]
        return cls(
            telefonos={digitos_telefono(t) for t in telefonos if digitos_telefono(t)},
            emails={e.strip().lower() for e in emails if e},
            personas={nombre_plano(n) for n in personas if n},
        )


def retirar_canal(fuentes_vigentes: set[str], encontrado: bool, leidos_del_tipo: int) -> bool:
    """¿Se retira un teléfono/email? Solo si nada más que la web lo respalda y
    la web ya no lo muestra. Sin evidencia registrada, no se decide nada; y si
    la relectura no encontró NINGUNO de ese tipo, tampoco (la portada no se
    leyó bien: p. ej. la de una multinacional es un selector de idioma)."""
    return leidos_del_tipo > 0 and fuentes_vigentes == {FUENTE_WEB} and not encontrado
