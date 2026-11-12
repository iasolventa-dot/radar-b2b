"""Resultados repetidos dentro de una búsqueda. Sin BD."""

from __future__ import annotations

from radar.agente.repetidos import Ficha, agrupar_repetidas


def test_misma_web_mismo_cif_y_telefono_con_nombre_parecido() -> None:
    fichas = [
        Ficha("a", "SEVILLA FUGAS SL", nif="B26816876", dominio="sevillafugas.es", telefonos=["+34625739424"]),
        Ficha("b", "Sevilla Fugas", dominio="sevillafugas.es"),
        Ficha("c", "Fugas Sevilla 24h", telefonos=["625 739 424"]),
        Ficha("d", "OTRA SL", nif="B26816876"),
        Ficha("e", "Gestoría López", telefonos=["+34625739424"]),  # mismo teléfono, otro nombre: no se une
        Ficha("f", "Perfil en Facebook", dominio="facebook.com"),
        Ficha("g", "Otro perfil", dominio="facebook.com"),  # plataforma: no cuenta
    ]
    grupos = agrupar_repetidas(fichas)
    assert len(grupos) == 1
    queda, repetidas = grupos[0]
    assert queda.empresa_id == "a"
    assert {(f.empresa_id, m) for f, m in repetidas} == {
        ("b", "misma web"), ("c", "mismo teléfono y nombre parecido"), ("d", "mismo CIF"),
    }


def test_mismo_telefono_con_cif_distinto_no_se_une() -> None:
    fichas = [
        Ficha("a", "Construcciones Pérez SL", nif="B26816876", telefonos=["954000000"]),
        Ficha("b", "Construcciones Pérez Hermanos SL", nif="B91234567", telefonos=["954000000"]),
    ]
    assert agrupar_repetidas(fichas) == []
