"""`busquedas.rondas` cuenta turnos del agente, no pasos (2026-10-01)."""

from radar.agente.planificador import RondaPlanificador
from radar.api.estado import rondas_del_agente


def test_solo_cuentan_los_turnos_del_planificador() -> None:
    rondas = [
        RondaPlanificador(1, "descubrir_apify_maps", {}, {}),
        RondaPlanificador(2, "planificador_llm", {}, {}),
        RondaPlanificador(3, "consultar_bd", {}, {}),
        RondaPlanificador(4, "planificador_llm", {}, {}),
        RondaPlanificador(5, "buscar_web", {}, {}),
        RondaPlanificador(6, "completar_contacto", {}, {}),
    ]
    assert rondas_del_agente(rondas) == 2
