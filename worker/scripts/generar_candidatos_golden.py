"""Genera `worker/tests/golden/registros_entrada.csv` automáticamente
consultando el BORME real (conector `radar.fuentes.borme`) — sin tocar
ninguna fuente de pago y sin que nadie tenga que buscar empresa por
empresa a mano.

Qué hace:
1. Recorre el BORME de la provincia de Sevilla día a día (por defecto,
   los últimos 90 días naturales) usando el API de datos abiertos del BOE.
2. Se queda con los actos que son candidatos razonables al sector
   construcción (doc 07 §6):
   - **Constituciones** cuyo objeto social menciona construcción → pool
     principal de casos "normales".
   - **Disoluciones/extinciones** cuya razón social sugiere construcción
     (heurística por nombre, débil a propósito) → candidatos para la
     categoría difícil "disuelta".
   - **Cambios de domicilio** con la misma heurística → candidatos para
     la categoría difícil "traslado".
3. Escribe cada candidato como una fila de `registros_entrada.csv`
   (estructura de la skill `agente-busqueda-empresas`, `references/evaluacion.md`).

Qué NO hace (a propósito, para no inventar datos): no asigna NIF, no
decide "es la misma empresa que...", no confirma que el candidato es
realmente del sector — todo eso lo hace la persona que arma
`entidades.csv` a partir de este listado, cruzando cada fila con REA o
la web de la empresa. Este script solo reduce el trabajo humano de
"buscar candidatos" a "confirmar candidatos".

Uso (con el entorno virtual del worker activado):
    python scripts\\generar_candidatos_golden.py
    python scripts\\generar_candidatos_golden.py --dias 180
    python scripts\\generar_candidatos_golden.py --provincia SEVILLA --dias 90 --municipio-principal "ALCALA DE GUADAIRA"
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from rapidfuzz import fuzz, process

RAIZ = Path(__file__).resolve().parents[2]  # .../radar-b2b
sys.path.insert(0, str(RAIZ / "worker"))

from radar.fuentes.borme import ConectorBorme

SALIDA = RAIZ / "worker" / "tests" / "golden" / "registros_entrada.csv"

COLUMNAS = [
    "id_fila",
    "categoria_candidato",
    "confianza_sector",
    "fuente",
    "id_externo",
    "razon_social",
    "municipio",
    "codigo_postal",
    "es_municipio_principal",
    "hoja_registral",
    "tipos_acto",
    "objeto_social",
    "capital_eur",
    "administradores",
    "posible_homonimo_de",
    "posible_grupo_con",
    "url_evidencia",
    "fecha_publicacion",
    "identificador_boletin",
    "entidad_id_real",
    "notas",
]

SUFIJOS_FORMA_JURIDICA = [
    "SOCIEDAD LIMITADA UNIPERSONAL", "SOCIEDAD LIMITADA", "SOCIEDAD ANONIMA",
    "SOCIEDAD COOPERATIVA", "SOCIEDAD CIVIL", "SLU", "SL", "SA", "SAU",
    "SCOOP", "CB", "EN LIQUIDACION",
]


def nombre_nucleo(razon_social: str) -> str:
    """Razón social sin forma jurídica ni "EN LIQUIDACION", para comparar homónimos."""
    norm = normalizar(razon_social)
    for sufijo in SUFIJOS_FORMA_JURIDICA:
        norm = re.sub(rf"\b{re.escape(sufijo)}\b\.?\s*$", "", norm).strip()
    return norm


def normalizar(s: str | None) -> str:
    if not s:
        return ""
    tabla = str.maketrans("áéíóúÁÉÍÓÚñÑ", "aeiouAEIOUnN")
    return s.translate(tabla).upper().strip()


async def generar(
    provincia_titulo: str, dias: int, municipio_principal: str
) -> list[dict]:
    hasta = datetime.now(UTC).date()
    desde = hasta - timedelta(days=dias)
    municipio_principal_norm = normalizar(municipio_principal)

    filas: list[dict] = []
    async with httpx.AsyncClient() as cliente:
        conector = ConectorBorme(cliente)
        n_procesados = 0
        async for registro in conector.descubrir(
            {"provincia_titulo": provincia_titulo, "desde": desde, "hasta": hasta},
            max_coste_eur=0.0,
        ):
            n_procesados += 1
            extra = registro.campos.extra
            tipos = extra.get("tipos_acto", [])
            objeto_social = extra.get("objeto_social")
            razon_social = registro.campos.razon_social or ""

            categoria = None
            confianza_sector = ""
            if "constitucion" in tipos and objeto_social:
                categoria, confianza_sector = _clasificar_objeto_social(objeto_social)
            elif ("disolucion" in tipos or "extincion" in tipos) and _nombre_sugiere_construccion(
                razon_social
            ):
                categoria = "candidato_disuelta"
                confianza_sector = "baja"  # heurística por nombre, no por objeto social
            elif "cambio_domicilio" in tipos and _nombre_sugiere_construccion(razon_social):
                categoria = "candidato_traslado"
                confianza_sector = "baja"  # heurística por nombre, no por objeto social

            if categoria is None:
                continue

            municipio = registro.campos.municipio or ""
            filas.append(
                {
                    "id_fila": f"BORME-{extra.get('id_borme') or len(filas) + 1}",
                    "categoria_candidato": categoria,
                    "confianza_sector": confianza_sector,
                    "fuente": "borme",
                    "id_externo": extra.get("id_borme") or "",
                    "razon_social": razon_social,
                    "municipio": municipio,
                    "codigo_postal": registro.campos.codigo_postal or "",
                    "es_municipio_principal": (
                        "si" if normalizar(municipio) == municipio_principal_norm else "no"
                    ),
                    "hoja_registral": extra.get("hoja_registral") or "",
                    "tipos_acto": ";".join(tipos),
                    "objeto_social": objeto_social or "",
                    "capital_eur": extra.get("capital_eur") or "",
                    # ConectorBorme da cada administrador como {"nombre": ..., "cargo": ...}
                    # (extracción de PATRONES_CARGO) desde que se distinguen roles -- antes
                    # este script esperaba una lista de strings sueltos y reventaba con
                    # TypeError en cuanto un acto real traía administradores (casi todas las
                    # constituciones). Confirmado en vivo, 2026-09-18.
                    "administradores": ";".join(
                        f"{a['nombre']} ({a['cargo']})" if isinstance(a, dict) else str(a)
                        for a in (extra.get("administradores") or [])
                    ),
                    "posible_homonimo_de": "",
                    "posible_grupo_con": "",
                    "url_evidencia": registro.url or "",
                    "fecha_publicacion": registro.payload.get("fecha_publicacion", ""),
                    "identificador_boletin": extra.get("identificador_boletin", ""),
                    "entidad_id_real": "",
                    "notas": (
                        "candidato automático — pendiente de confirmar NIF, "
                        "estado real y sector con REA/web antes de pasar a entidades.csv"
                    ),
                }
            )
        print(f"Actos BORME procesados en el rango: {n_procesados}", file=sys.stderr)

    _detectar_homonimos(filas)
    _detectar_grupos(filas)
    return filas


UMBRAL_FUZZY_HOMONIMO = 88  # rapidfuzz.fuzz.ratio (0-100); calibrar con el golden set real


def _detectar_homonimos(filas: list[dict]) -> None:
    """Dos filas con nombre "núcleo" igual o muy parecido (sin forma jurídica)
    pero distinta hoja registral son casi con certeza empresas distintas con
    nombre parecido: exactamente el caso "homónimo" que pide doc 07 §6.
    Coincidencia exacta primero; si no hay bastantes, se completa con
    similitud difusa (rapidfuzz, ya es dependencia del worker) para no
    depender de que dos razones sociales coincidan carácter a carácter.
    Señal automática, a confirmar por la persona que arme entidades.csv
    (nunca se fusionan solas)."""
    nucleos = [nombre_nucleo(f["razon_social"]) for f in filas]

    for i, fila in enumerate(filas):
        if not nucleos[i]:
            continue
        coincidencias = process.extract(
            nucleos[i], nucleos, scorer=fuzz.ratio, score_cutoff=UMBRAL_FUZZY_HOMONIMO, limit=10
        )
        otras_ids = []
        for _texto, _score, j in coincidencias:
            if j == i:
                continue
            if filas[j]["hoja_registral"] and filas[j]["hoja_registral"] == fila["hoja_registral"]:
                continue  # misma empresa (mismo acto o mismo registro), no homónimo
            otras_ids.append(filas[j]["id_fila"])
        if otras_ids:
            fila["posible_homonimo_de"] = ";".join(sorted(set(otras_ids)))
            if fila["categoria_candidato"] == "pool_normal_construccion":
                fila["categoria_candidato"] = "candidato_homonimo"


def _detectar_grupos(filas: list[dict]) -> None:
    """Dos empresas distintas (hoja registral distinta) con el mismo administrador
    son candidatas a "grupo empresarial" (doc 07 §6). Señal automática a partir
    de datos ya descargados del BORME — no hace falta ninguna llamada extra."""
    por_administrador: dict[str, list[dict]] = {}
    for fila in filas:
        for admin in fila["administradores"].split(";"):
            admin = admin.strip()
            if admin:
                por_administrador.setdefault(admin, []).append(fila)

    for admin, grupo in por_administrador.items():
        hojas = {f["hoja_registral"] for f in grupo if f["hoja_registral"]}
        if len(hojas) > 1:
            for fila in grupo:
                otras = [f["id_fila"] for f in grupo if f is not fila]
                previo = fila["posible_grupo_con"].split(";") if fila["posible_grupo_con"] else []
                fila["posible_grupo_con"] = ";".join(sorted(set(previo + otras)) if previo else otras)
                if fila["categoria_candidato"] == "pool_normal_construccion":
                    fila["categoria_candidato"] = "candidato_grupo"


PALABRAS_CONSTRUCCION_OBJETO = [
    "construccion", "obra", "edificacion", "reforma", "rehabilitacion",
    "promocion inmobiliaria", "albañileria", "fontaneria", "electricidad",
    "instalaciones electricas", "pintura", "climatizacion", "carpinteria",
    "excavacion", "demolicion", "urbanizacion", "saneamiento",
    "impermeabilizacion", "cubiertas", "estructuras metalicas", "hormigon",
    "andamios", "movimiento de tierras", "instalador",
]

# CNAE 41-43 = construcción (doc 07 §6). Muchas constituciones declaran el
# objeto social como lista de códigos CNAE con "Actividad principal: XX.XX"
# + "Otras actividades: ...". Cuando ese patrón existe, es una señal mucho
# más fiable que buscar palabras sueltas en un objeto social "todo tipo de
# actividades" (boilerplate habitual en SL de propósito genérico, donde
# "Construcción, instalaciones y mantenimiento" aparece junto a comercio,
# hostelería, etc. sin que la empresa vaya a dedicarse a eso).
_RE_ACTIVIDAD_PRINCIPAL = re.compile(r"Actividad principal:?\s*(\d{2})(?:\.\d{2})?", re.IGNORECASE)
_RE_CNAE_CUALQUIERA = re.compile(r"\b(4[1-3])\.\d{2}\b")


def _clasificar_objeto_social(objeto_social: str) -> tuple[str | None, str]:
    """Devuelve (categoria, confianza). confianza: alta / media / baja.

    - alta: la "Actividad principal" declarada es CNAE 41, 42 o 43.
    - media: aparece algún código CNAE 41-43 en el texto, pero no como
      actividad principal (construcción es una actividad secundaria).
    - baja: no hay códigos CNAE explícitos, solo coincide una palabra clave
      en un objeto social de propósito genérico ("todo tipo de actividades").
    """
    m_principal = _RE_ACTIVIDAD_PRINCIPAL.search(objeto_social)
    if m_principal and m_principal.group(1) in ("41", "42", "43"):
        return "pool_normal_construccion", "alta"

    if _RE_CNAE_CUALQUIERA.search(objeto_social):
        return "pool_normal_construccion", "media"

    obj_norm = normalizar(objeto_social).lower()
    if any(p in obj_norm for p in PALABRAS_CONSTRUCCION_OBJETO):
        # sin ningún código CNAE explícito en todo el texto -> probablemente
        # objeto social "todo tipo de actividades", no confirma el sector
        return "revisar_objeto_generico", "baja"

    return None, ""


def _nombre_sugiere_construccion(razon_social: str) -> bool:
    palabras = [
        "construc", "obras", "reformas", "edifica", "promocion", "contratas",
        "instalaciones", "urbaniza", "hormigon", "excavac",
    ]
    norm = normalizar(razon_social).lower()
    return any(p in norm for p in palabras)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provincia", default="SEVILLA", help="Título de provincia tal como lo usa el BORME")
    ap.add_argument("--dias", type=int, default=90, help="Días naturales hacia atrás desde hoy")
    ap.add_argument(
        "--municipio-principal",
        default="ALCALA DE GUADAIRA",
        help="Municipio piloto (doc 07 §6) — se marca aparte para priorizar la revisión",
    )
    args = ap.parse_args()

    filas = asyncio.run(generar(args.provincia, args.dias, args.municipio_principal))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with SALIDA.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNAS)
        writer.writeheader()
        writer.writerows(filas)

    por_categoria: dict[str, int] = {}
    for fila in filas:
        por_categoria[fila["categoria_candidato"]] = por_categoria.get(fila["categoria_candidato"], 0) + 1

    por_confianza: dict[str, int] = {}
    for fila in filas:
        clave = fila["confianza_sector"] or "n/a"
        por_confianza[clave] = por_confianza.get(clave, 0) + 1

    print(f"\nEscrito: {SALIDA}")
    print(f"Total candidatos: {len(filas)}")
    for categoria, n in sorted(por_categoria.items()):
        print(f"  - {categoria}: {n}")
    print("Confianza de sector (solo aplica a candidatos derivados del objeto social):")
    for confianza, n in sorted(por_confianza.items()):
        print(f"  - {confianza}: {n}")
    print(
        "\nSiguiente paso: revisar registros_entrada.csv, cruzar cada fila con "
        "REA/web para el NIF y volcar los que se confirmen en entidades.csv."
    )


if __name__ == "__main__":
    main()
