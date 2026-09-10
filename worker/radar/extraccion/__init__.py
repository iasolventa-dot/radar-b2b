"""Extracción de datos desde HTML no estructurado (doc 02 §5-6, doc 04 §3).

Dos niveles, siempre en este orden:
1. Reglas (regex de NIF, teléfonos, emails en el aviso legal) — barato y determinista.
2. Solo si faltan campos tras las reglas: LLM con salida estructurada (modelo
   rápido/barato, ver doc 07 §2).

Pendiente: Fase 1.
"""
