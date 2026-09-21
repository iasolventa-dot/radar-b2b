"""Comprobación EN VIVO (contra la base real, todo dentro de una transacción
que se revierte al final -- no deja nada escrito) de que el cruce entre
fuentes casa lo que debe y NO casa lo que no debe.

Toma empresas reales ya guardadas y simula el registro que otra fuente
(estilo OpenStreetMap: solo nombre comercial, sin razón social ni NIF)
traería sobre ellas:

  A. mismo negocio, nombre comercial abreviado + mismas coordenadas
     -> debe VINCULARSE a la empresa existente.
  B. mismo dominio web que una empresa existente pero nombre distinto
     -> debe llegar al menos a REVISIÓN (nunca crearse como nueva sin más).
  C. mismo nombre pero en OTRA provincia (homónimo)
     -> NO debe vincularse.
  D. mismo nombre exacto sin ninguna señal de ubicación
     -> debe ir a REVISIÓN (regla R4), nunca fusionarse sola.

Uso: python scripts\\verificar_cruce_fuentes.py
"""

from __future__ import annotations

import psycopg

from radar.config import get_settings
from radar.fuentes.base import CamposExtraidos, RegistroBruto
from radar.orquestador import procesar_registro


def _reg(id_ext: str, **campos) -> RegistroBruto:
    return RegistroBruto(fuente="osm", id_externo=id_ext, url=f"https://www.openstreetmap.org/{id_ext}",
                         payload={"prueba": id_ext}, campos=CamposExtraidos(**campos))


def main() -> None:
    settings = get_settings()
    with psycopg.connect(settings.supabase_db_url) as conn:
        fila = conn.execute(
            """
            select e.id, e.razon_social, e.nif, extensions.st_y(s.geom::extensions.geometry), extensions.st_x(s.geom::extensions.geometry),
                   s.municipio_nombre, s.provincia
            from empresas e join sedes s on s.empresa_id = e.id and s.activa and s.geom is not null
            where e.fusionada_en is null and e.razon_social ~ '^[A-ZÁÉÍÓÚ]{4,} [A-ZÁÉÍÓÚ]{4,}' and e.dominio_web is null
              and not exists (select 1 from registros_brutos rb join fuentes f on f.id=rb.fuente_id where rb.empresa_id=e.id and f.codigo='osm')
            order by e.creado_en limit 1
            """
        ).fetchone()
        if not fila:
            print("No hay empresas geocodificadas para probar.")
            return
        eid, razon, nif, lat, lon, municipio, provincia = fila
        print(f"Empresa base: {razon} ({municipio}, {provincia}) @ {lat:.5f},{lon:.5f}\n")

        corto = " ".join(razon.replace(".", "").split()[:2]).title()
        casos = {
            "A abreviado + mismas coordenadas": _reg("node/9000001", nombre_comercial=corto, lat=lat, lon=lon, municipio=municipio),
            "C homónimo en otra provincia": _reg("node/9000003", nombre_comercial=razon, lat=41.65, lon=-0.88, municipio="Zaragoza", provincia="Zaragoza"),
            "D mismo nombre sin ubicación": _reg("node/9000004", nombre_comercial=razon),
        }
        # B: se prepara un dominio en la empresa base dentro de la transacción
        conn.execute("update empresas set dominio_web = 'dominio-de-prueba-cruce.es' where id = %s", (eid,))
        casos["B mismo dominio, nombre distinto"] = _reg(
            "node/9000002", nombre_comercial="Totalmente Otro Nombre", web="https://www.dominio-de-prueba-cruce.es/", lat=lat, lon=lon
        )

        for nombre, registro in casos.items():
            resultado = procesar_registro(registro, conn, telefonos_compartidos=set())
            vinculada_a_base = str(resultado.empresa_id) == str(eid)
            print(f"[{nombre}] -> {resultado.accion} (puntuación {resultado.puntuacion_match}, "
                  f"a la empresa base: {'SÍ' if vinculada_a_base else 'no'})")
        conn.rollback()
        print("\n(transacción revertida: no se ha escrito nada)")


if __name__ == "__main__":
    main()
