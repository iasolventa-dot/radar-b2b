"""Consolidación del registro oro y confianza de cada campo (doc 05 §3).

Opera sobre observaciones ya normalizadas (capa PLATA, tabla `observaciones`):
cada observación es un dict con, como mínimo, ``valor_norm``,
``confianza_fuente`` (0-1, copiada de ``fuentes.fiabilidad_base`` al capturar
la observación), ``grupo_independencia`` (de la fuente que la afirma),
``observado_en`` (``datetime``) y opcionalmente ``es_registro_oficial``
(``fuentes.tipo == 'registro_oficial'``). El orquestador del pipeline es
quien las lee de la base de datos y filtra ``vigente = true`` antes de
llamar aquí — este módulo no toca la base de datos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import prod

# Doc 05 §3 "Semividas iniciales". ``None`` = sin decaimiento (el valor no
# pierde confianza con el tiempo; solo lo sustituye una observación que lo
# contradiga). Claves = valores del campo `observaciones.campo` (doc 03b).
# `direccion` sin sufijo se trata como domicilio social (sin decaimiento);
# usa `sede_operativa` para la sede operativa, que sí decae.
SEMIVIDAS_DIAS: dict[str, int | None] = {
    "nif": None,
    "razon_social": None,
    "fecha_constitucion": None,
    "domicilio_social": None,
    "direccion": None,
    "estado": 180,
    "sede_operativa": 540,
    "telefono": 365,
    "email": 365,
    "web": 90,
    "tamano": 365,
    "empleados": 365,
}

# Doc 05 §3: campos donde, en caso de empate de confianza efectiva, gana el
# valor respaldado por un registro oficial (antes de mirar la fecha).
_CAMPOS_PRIORIDAD_REGISTRO_OFICIAL = {"razon_social", "domicilio_social", "direccion"}

# Doc 05 §3.5: campos multivalor (se guardan todos los valores por encima
# del umbral, no solo el ganador).
UMBRAL_MULTIVALOR = 0.5

# Doc 05 §3.6: si el segundo valor supera esta confianza efectiva y es
# distinto del ganador, hay conflicto. La magnitud de la rebaja no la fija
# el doc 05 ("se rebaja la confianza del campo"); aquí se aplica un factor
# de 0,7 sobre la confianza efectiva del ganador — valor inicial, a
# calibrar con el golden set igual que el resto de umbrales de este módulo.
FACTOR_REBAJA_CONFLICTO = 0.7


def semivida_dias(campo: str) -> int | None:
    """Semivida en días para `campo`, o ``None`` si no está en la tabla (se
    trata como sin decaimiento, igual que NIF/razón social)."""
    return SEMIVIDAS_DIAS.get(campo)


@dataclass
class ValorConsolidado:
    valor: str
    confianza: float  # c: combinación de fuentes independientes, sin decaimiento
    confianza_efectiva: float  # c_efectiva: con decaimiento por antigüedad
    dias_desde_ultima: int
    n_observaciones: int
    n_fuentes_independientes: int
    tiene_registro_oficial: bool = False


@dataclass
class ResultadoConsolidacion:
    campo: str
    valores: list[ValorConsolidado] = field(default_factory=list)
    conflicto: bool = False

    @property
    def ganador(self) -> ValorConsolidado | None:
        return self.valores[0] if self.valores else None

    @property
    def multivalor(self) -> list[ValorConsolidado]:
        """Todos los valores por encima de `UMBRAL_MULTIVALOR` (doc 05 §3.5),
        para campos como teléfonos o emails donde se guarda más de uno."""
        return [v for v in self.valores if v.confianza_efectiva > UMBRAL_MULTIVALOR]


def _combinar_independientes(confianzas_por_grupo: dict[str | None, float]) -> float:
    """c = 1 − Π(1 − cᵢ), una cᵢ por grupo de independencia (doc 05 §3.2)."""
    if not confianzas_por_grupo:
        return 0.0
    return round(1 - prod(1 - c for c in confianzas_por_grupo.values()), 4)


def consolidar_campo(
    campo: str,
    observaciones: list[dict],
    ahora: datetime | None = None,
) -> ResultadoConsolidacion:
    """Consolida las observaciones vigentes de un campo en valor(es) ganador(es).

    ``observaciones`` ya deben estar filtradas a `vigente = true` y al mismo
    ``empresa_id``. Cada dict necesita ``valor_norm``, ``confianza_fuente``,
    ``grupo_independencia``, ``observado_en``; ``es_registro_oficial`` es
    opcional (por defecto False).
    """
    ahora = ahora or datetime.now(UTC)
    semivida = semivida_dias(campo)

    por_valor: dict[str, list[dict]] = {}
    for obs in observaciones:
        valor = obs.get("valor_norm")
        if not valor:
            continue
        por_valor.setdefault(valor, []).append(obs)

    calculados: list[ValorConsolidado] = []
    for valor, obs_valor in por_valor.items():
        # Doc 05 §3.2: solo la mayor cᵢ dentro de cada grupo_independencia
        # cuenta (dos directorios que dicen lo mismo cuentan como uno).
        mejor_por_grupo: dict[str | None, float] = {}
        for obs in obs_valor:
            grupo = obs.get("grupo_independencia")
            c = float(obs.get("confianza_fuente") or 0.0)
            if c > mejor_por_grupo.get(grupo, -1.0):
                mejor_por_grupo[grupo] = c
        c = _combinar_independientes(mejor_por_grupo)

        fecha_mas_reciente = max(obs["observado_en"] for obs in obs_valor)
        dias = max(0, (ahora - fecha_mas_reciente).days)
        if semivida is None:
            c_efectiva = c
        else:
            c_efectiva = round(c * (0.5 ** (dias / semivida)), 4)

        calculados.append(
            ValorConsolidado(
                valor=valor,
                confianza=c,
                confianza_efectiva=c_efectiva,
                dias_desde_ultima=dias,
                n_observaciones=len(obs_valor),
                n_fuentes_independientes=len(mejor_por_grupo),
                tiene_registro_oficial=any(obs.get("es_registro_oficial") for obs in obs_valor),
            )
        )

    prioridad_registro_oficial = campo in _CAMPOS_PRIORIDAD_REGISTRO_OFICIAL

    def orden(v: ValorConsolidado) -> tuple:
        fecha = max(obs["observado_en"] for obs in por_valor[v.valor])
        return (
            -v.confianza_efectiva,
            0 if (prioridad_registro_oficial and v.tiene_registro_oficial) else 1,
            -fecha.timestamp(),
        )

    calculados.sort(key=orden)

    conflicto = (
        len(calculados) >= 2
        and calculados[1].confianza_efectiva > 0.7
        and calculados[1].valor != calculados[0].valor
    )
    if conflicto:
        # Se rebaja la confianza del campo (doc 05 §3.6), pero el ganador
        # sigue siendo el que ya decidieron las reglas de tie-break de
        # arriba — la rebaja no vuelve a barajar el orden.
        calculados[0] = ValorConsolidado(
            **{
                **calculados[0].__dict__,
                "confianza_efectiva": round(calculados[0].confianza_efectiva * FACTOR_REBAJA_CONFLICTO, 4),
            }
        )

    return ResultadoConsolidacion(campo=campo, valores=calculados, conflicto=conflicto)
