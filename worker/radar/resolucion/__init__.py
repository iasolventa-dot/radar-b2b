"""Resolución de entidades: blocking, puntuación, fusión, cola de revisión (doc 05 §2-3).

Implementa las reglas duras y la puntuación por señales del doc 05, usando
`buscar_candidatos_empresa()` (función SQL de la migración inicial) como
paso de blocking. Toda fusión automática (puntuación >= 0.80) se registra
en `fusiones` con instantánea para poder deshacer.

Pendiente: Fase 1.
"""
