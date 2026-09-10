"""Conectores de fuentes de datos (doc 04, doc 02 §5).

Cada módulo de este paquete (`borme.py`, `places.py`, `web.py`, `rea.py`,
`placsp.py`…) implementa un conector y devuelve registros con el contrato
mínimo del doc 02 §5:

    {
        "fuente": "borme",
        "url": "https://…",
        "capturado_en": "2026-09-10T10:00:00Z",
        "id_externo": "…",
        "payload": {...},   # crudo, solo si fuentes.permite_almacenar
        "campos": {...},    # normalizado al contrato común
    }

Pendiente (Fase 1, Paso 11 de la guía de montaje): un conector por chat,
empezando por BORME, PLACSP y REA (fuentes oficiales con NIF).
"""
