"""Coste real de las llamadas a LLM, a partir de los tokens que devuelve
cada proveedor. Hasta esta sesión (2026-09-21) `radar.agente.planificador`
nunca leía `respuesta.usage` -- el coste mostrado en el panel solo incluía
las herramientas con coste explícito (`buscar_web`) y no el propio LLM que
planifica/interpreta/arbitra, pese a que la API ya lo da gratis en cada
respuesta (confirmado pidiéndolo el usuario en vivo, 2026-09-21).

Precios verificados en la documentación oficial de cada proveedor, no
inventados (principio 5 del proyecto):
- OpenAI: https://developers.openai.com/api/docs/pricing (verificado
  2026-09-21). `gpt-5.6-sol` está en precio promocional 4$/20$ por millón
  de tokens entrada/salida hasta el 21-11-2026 (precio normal después:
  5$/30$) -- si el coste mostrado empieza a desviarse de lo real, revisar
  primero si esa fecha ya pasó.
- Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
  (verificado 2026-09-21).

1 USD ≈ 1 EUR para el presupuesto (D-04) -- mismo criterio ya usado en
`radar.fuentes.buscador_web.COSTE_POR_BUSQUEDA_EUR`, no se complica con un
tipo de cambio real para cifras de este orden de magnitud.
"""

from __future__ import annotations

# {modelo: (usd_por_millon_tokens_entrada, usd_por_millon_tokens_salida)}
_PRECIOS_USD_POR_MILLON: dict[str, tuple[float, float]] = {
    # OpenAI -- developers.openai.com/api/docs/pricing, 2026-09-21.
    "gpt-5.6-sol": (4.00, 20.00),  # precio promocional hasta 2026-11-21 (normal 5.00/30.00)
    "gpt-5.6-luna": (0.20, 1.20),
    # Anthropic -- platform.claude.com/docs/en/about-claude/pricing, 2026-09-21.
    # No hay ninguna clave de Anthropic configurada en este proyecto a día
    # de hoy (proveedor_llm por defecto "openai"), pero se deja lista la
    # tabla de precios para que el coste no se quede en 0 en silencio el
    # día que se active.
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5": (5.00, 25.00),
}


def calcular_coste_eur(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    """Coste en EUR de una llamada, a partir de los tokens reales que
    devuelve la API (`usage.input_tokens`/`usage.output_tokens`, tanto en
    OpenAI como en Anthropic).

    Un modelo que no está en la tabla de precios devuelve 0.0 -- nunca se
    inventa un coste para un modelo sin verificar (principio 5): mejor
    infravalorar el coste mostrado que declarar uno inventado.
    """
    precios = _PRECIOS_USD_POR_MILLON.get(modelo)
    if precios is None:
        return 0.0
    usd_entrada, usd_salida = precios
    return (tokens_entrada / 1_000_000) * usd_entrada + (tokens_salida / 1_000_000) * usd_salida
