"""Puntuación de duplicados entre dos registros normalizados (doc 05 §2.2-2.4).

Opera sobre la salida de `radar.normalizacion.registro.normalizar_registro`.
No toca la base de datos — eso lo hace `radar.resolucion.blocking` (para
encontrar candidatos) y el orquestador del pipeline (para decidir fusión /
cola de revisión / arbitraje LLM a partir de `decision`).

Los umbrales y pesos son valores iniciales (doc 05: "se calibran con el
golden set", doc 07). Si cambian aquí, hay que cambiarlos también en doc 05
y en la skill `verificacion-empresas-es` (`scripts/lib_empresas.py`), que
implementa la misma lógica para limpieza de listados fuera del pipeline.
"""

from __future__ import annotations

from radar.normalizacion.direccion import distancia_m
from radar.normalizacion.nombre import similitud_nombres, tokens_distintivos

# Doc 05 §2.4
UMBRAL_FUSION_AUTO = 0.80
UMBRAL_REVISION = 0.55

# Doc 05 §2.3
PESOS = {
    "nombre_095": 0.45,
    "nombre_088": 0.30,
    "nombre_080": 0.15,
    "nombre_bajo": -0.15,  # similitud < 0,50 con ambos nombres presentes
    "nombre_solo_genericas": 0.15,  # tope si no hay palabras distintivas en común
    "dominio": 0.45,
    "dominio_minimo": 0.60,  # un dominio común garantiza al menos revisión
    "telefono": 0.35,
    "email": 0.25,
    "dist_50": 0.25,
    "dist_300": 0.15,
    "dist_2000": 0.05,
    "dist_lejos": -0.20,  # > 50 km
    "cp_igual": 0.10,  # solo si no hay coordenadas
    "provincia_distinta": -0.20,  # solo si no hay coordenadas
    "forma_distinta": -0.30,
}


def _mejor_similitud(a: dict, b: dict) -> tuple[float, bool]:
    """Máxima similitud entre las combinaciones de nombres y si comparten palabras distintivas."""
    na = [x for x in (a.get("nombre_norm"), a.get("comercial_norm")) if x]
    nb = [x for x in (b.get("nombre_norm"), b.get("comercial_norm")) if x]
    if not na or not nb:
        return 0.0, False
    mejor, distintivas = 0.0, False
    for x in na:
        for y in nb:
            s = similitud_nombres(x, y)
            mejor = max(mejor, s)
            if tokens_distintivos(x) & tokens_distintivos(y):
                distintivas = True
    return mejor, distintivas


def comparar(a: dict, b: dict, telefonos_compartidos: set | None = None) -> dict:
    """Compara dos registros NORMALIZADOS (salida de `normalizar_registro`).

    Devuelve ``{puntuacion, decision, regla, senales, similitud_nombre}``.
    ``decision`` es una de ``"misma" | "revision" | "distinta"`` — el
    orquestador decide qué hacer con "revision" (arbitraje LLM, doc 05 §2.5,
    y si sigue incierto, cola humana en `candidatos_duplicado`).

    ``telefonos_compartidos`` son teléfonos vistos en más de 3 empresas con
    NIF distinto (gestorías, centralitas) — se calculan aparte, sobre toda
    la base, y no puntúan como señal de identidad (doc 05 §2.3).
    """
    compartidos = telefonos_compartidos or set()
    senales: list[str] = []
    sim, distintivas = _mejor_similitud(a, b)

    def resultado(p: float, regla: str) -> dict:
        p = max(0.0, min(1.0, round(p, 3)))
        decision = "misma" if p >= UMBRAL_FUSION_AUTO else ("revision" if p >= UMBRAL_REVISION else "distinta")
        return {"puntuacion": p, "decision": decision, "regla": regla, "senales": senales, "similitud_nombre": sim}

    # --- Reglas duras (doc 05 §2.2), en orden ---
    if a.get("nif_valido") and b.get("nif_valido"):
        if a["nif"] != b["nif"]:
            senales.append(f"NIF distintos ({a['nif']} ≠ {b['nif']})")
            return resultado(0.0, "R1_nif_distinto")
        senales.append(f"NIF igual ({a['nif']})")
        if sim < 0.5 and not distintivas:
            senales.append("nombres muy distintos con mismo NIF: ¿NIF de un tercero (agencia web, gestoría)?")
            return resultado(0.70, "R2_nif_igual_nombres_distintos")
        return resultado(1.0, "R2_nif_igual")
    if a.get("place_id") and a.get("place_id") == b.get("place_id"):
        senales.append("mismo place_id de Google")
        return resultado(0.95, "R3_place_id")

    p = 0.0
    # --- Nombre ---
    if (a.get("nombre_norm") or a.get("comercial_norm")) and (b.get("nombre_norm") or b.get("comercial_norm")):
        if sim >= 0.95:
            aporte = PESOS["nombre_095"]
        elif sim >= 0.88:
            aporte = PESOS["nombre_088"]
        elif sim >= 0.80:
            aporte = PESOS["nombre_080"]
        elif sim < 0.50:
            aporte = PESOS["nombre_bajo"]
        else:
            aporte = 0.0
        if aporte > 0 and not distintivas:
            aporte = min(aporte, PESOS["nombre_solo_genericas"])
            senales.append("nombres parecidos pero solo con palabras genéricas en común")
        if aporte:
            senales.append(f"similitud de nombre {sim:.2f} ({aporte:+.2f})")
        p += aporte
    # --- Forma jurídica ---
    if a.get("forma_juridica") and b.get("forma_juridica") and a["forma_juridica"] != b["forma_juridica"]:
        p += PESOS["forma_distinta"]
        senales.append(f"formas jurídicas distintas ({a['forma_juridica']} vs {b['forma_juridica']})")
    # --- Dominio ---
    dominio_comun = bool(a.get("dominio") and a.get("dominio") == b.get("dominio"))
    if dominio_comun:
        p += PESOS["dominio"]
        senales.append(f"mismo dominio ({a['dominio']})")
    # --- Teléfono ---
    tel_comunes = (
        (set(a.get("telefonos", [])) & set(b.get("telefonos", [])))
        - set(a.get("telefonos_especiales", []))
        - compartidos
    )
    if tel_comunes:
        p += PESOS["telefono"]
        senales.append(f"mismo teléfono ({', '.join(sorted(tel_comunes))})")
    # --- Email ---
    if set(a.get("emails", [])) & set(b.get("emails", [])):
        p += PESOS["email"]
        senales.append("mismo email")
    # --- Ubicación ---
    d = distancia_m(a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
    if d is not None:
        if d <= 50:
            p += PESOS["dist_50"]
        elif d <= 300:
            p += PESOS["dist_300"]
        elif d <= 2000:
            p += PESOS["dist_2000"]
        elif d > 50000:
            p += PESOS["dist_lejos"]
        senales.append(f"distancia {d:.0f} m")
    else:
        if a.get("cp") and a.get("cp") == b.get("cp"):
            p += PESOS["cp_igual"]
            senales.append(f"mismo CP ({a['cp']})")
        if a.get("cod_provincia") and b.get("cod_provincia") and a["cod_provincia"] != b["cod_provincia"]:
            p += PESOS["provincia_distinta"]
            senales.append("provincias distintas")
    if dominio_comun:
        p = max(p, PESOS["dominio_minimo"])

    # --- Nombre casi idéntico sin ninguna señal de ubicación (2026-09-18) ---
    # Nombre solo nunca pasa de PESOS["nombre_095"] (0.45), por debajo de
    # UMBRAL_REVISION (0.55) -- confirmado con datos reales de BORME: la
    # misma empresa registrada varias veces bajo el mismo nombre exacto
    # ("VIMOINSA VIVIENDAS PREFABRICADAS SL" x3, "SPAI INNOVA ASTIGITAS" x8
    # en un único mes de Sevilla) se creaba como empresa nueva cada vez, sin
    # dejar ni rastro en candidatos_duplicado. La diferencia con
    # test_homonimos_en_otra_provincia_no_fusionan (que debe seguir dando
    # "distinta") es que ahí SÍ hay una señal de ubicación que las distingue
    # (CP de provincias distintas); esta regla solo actúa cuando NINGUNO de
    # los dos registros aporta ninguna ubicación (ni coordenadas ni CP) --
    # es decir, cuando de verdad no hay forma de saber si son la misma o dos
    # homónimas, nunca cuando hay evidencia de que son distintas.
    if (
        p < UMBRAL_REVISION
        and sim >= 0.95
        and distintivas
        and d is None
        and not a.get("cp")
        and not b.get("cp")
    ):
        senales.append("nombre casi idéntico sin ninguna señal de ubicación en ninguno de los dos registros")
        return resultado(UMBRAL_REVISION, "R4_nombre_identico_sin_senal_ubicacion")

    return resultado(p, "puntuacion")
