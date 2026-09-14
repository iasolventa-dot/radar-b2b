"""Tests de `radar.api.estado` — la única parte de `radar.api` que no toca
BD ni red (`radar.api.bd_busquedas` y `radar.api.main` se prueban de forma
manual/integración, ver docstring de esos módulos)."""

from __future__ import annotations

from radar.agente.planificador import ResultadoPlanificador, RondaPlanificador
from radar.api.estado import estado_final_de, serializar_estadisticas, serializar_ronda


def _ronda(numero: int = 1, herramienta: str = "consultar_bd") -> RondaPlanificador:
    return RondaPlanificador(numero=numero, herramienta=herramienta, argumentos={"a": 1}, resultado={"total": 3})


# ---------- serializar_ronda ----------


def test_serializar_ronda():
    r = _ronda()
    assert serializar_ronda(r) == {"numero": 1, "herramienta": "consultar_bd", "argumentos": {"a": 1}, "resultado": {"total": 3}}


# ---------- serializar_estadisticas ----------


def test_serializar_estadisticas_en_curso_sin_resultado():
    estadisticas = serializar_estadisticas([_ronda(1), _ronda(2, "buscar_web")], max_rondas=10)
    assert estadisticas["max_rondas"] == 10
    assert len(estadisticas["rondas"]) == 2
    assert "motivo_fin" not in estadisticas
    assert "resumen" not in estadisticas
    assert "pregunta" not in estadisticas
    assert "error" not in estadisticas


def test_serializar_estadisticas_con_resultado_final():
    resultado = ResultadoPlanificador(motivo_fin="cobertura_alcanzada", resumen="listo", pregunta=None, error=None)
    estadisticas = serializar_estadisticas([_ronda()], max_rondas=5, resultado=resultado)
    assert estadisticas["motivo_fin"] == "cobertura_alcanzada"
    assert estadisticas["resumen"] == "listo"
    assert estadisticas["pregunta"] is None
    assert estadisticas["error"] is None


def test_serializar_estadisticas_vacio():
    estadisticas = serializar_estadisticas([], max_rondas=0)
    assert estadisticas == {"max_rondas": 0, "rondas": []}


# ---------- estado_final_de ----------


def test_estado_final_de_error_tiene_prioridad():
    resultado = ResultadoPlanificador(error="la API falló", pregunta={"pregunta": "¿zona?"})
    assert estado_final_de(resultado) == "error"


def test_estado_final_de_cancelada_por_usuario():
    """migración 202609141400 — debe_cancelar() devolvió True entre rondas."""
    resultado = ResultadoPlanificador(motivo_fin="cancelada_por_usuario")
    assert estado_final_de(resultado) == "cancelada"


def test_estado_final_de_cancelada_tiene_prioridad_sobre_error():
    """Si debe_cancelar() falla comprobándolo (radar.agente.planificador
    también marca error en ese caso) DESPUÉS de que otra ronda ya hubiera
    puesto motivo_fin='cancelada_por_usuario', debe seguir ganando
    'cancelada' -- es una cancelación pedida por el usuario, no un fallo
    inesperado, aunque el error también esté presente."""
    resultado = ResultadoPlanificador(motivo_fin="cancelada_por_usuario", error="fallo comprobando cancelación: x")
    assert estado_final_de(resultado) == "cancelada"


def test_estado_final_de_pregunta_sin_error():
    resultado = ResultadoPlanificador(pregunta={"pregunta": "¿incluyo autónomos?", "opciones": []})
    assert estado_final_de(resultado) == "esperando_respuesta"


def test_estado_final_de_completada():
    resultado = ResultadoPlanificador(motivo_fin="cobertura_alcanzada", resumen="listo")
    assert estado_final_de(resultado) == "completada"
