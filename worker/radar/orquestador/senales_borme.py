"""Traduce los actos del BORME a señales de estado (doc 05 §4).

Función pura, sin base de datos: separada de `bd.py`/`procesar.py` para
poder testearla sin Postgres. Si en el futuro se añade otro conector que
aporte señales de estado (Google Places "cerrado permanentemente", vida de
la web…), este es el patrón a seguir: un `mapear_senales_<fuente>` propio
por conector, combinado en `procesar.py`.
"""

from __future__ import annotations

from radar.verificacion.estado import SenalesEstado


def mapear_senales_borme(tipos_acto: list[str]) -> SenalesEstado:
    """`tipos_acto` es el campo que produce
    `radar.fuentes.borme.parsear_datos_acto` (constitucion, disolucion,
    extincion, cambio_domicilio, cambio_denominacion, concurso).

    Simplificación conocida: el texto que hoy parsea `ConectorBorme` no
    distingue disolución CON liquidación de disolución SIN liquidación (doc
    05 §4 sí los separa: 'en_liquidacion' vs 'disuelta'); mientras el
    conector no extraiga ese matiz, toda disolución detectada se trata como
    'sin_liquidacion'. A revisar si `radar.fuentes.borme` empieza a
    diferenciarlas.
    """
    tipos = set(tipos_acto)
    if "extincion" in tipos:
        return SenalesEstado(borme_extincion=True)
    if "disolucion" in tipos:
        return SenalesEstado(borme_disolucion="sin_liquidacion")
    if "concurso" in tipos:
        return SenalesEstado(borme_concurso=True)
    if tipos & {"constitucion", "cambio_domicilio", "cambio_denominacion"}:
        # Doc 05 §4.6: "acto societario no extintivo en BORME en los
        # últimos 24 meses" es una de las señales positivas de actividad.
        return SenalesEstado(acto_societario_no_extintivo_reciente=True)
    return SenalesEstado()
