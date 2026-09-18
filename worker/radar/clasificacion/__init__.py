"""Clasificación objeto_social -> CNAE (doc 05, prompt #5 de la skill
agente-busqueda-empresas). Mismo patrón que `radar.resolucion`: bloqueo
determinista (`radar.clasificacion.reglas` cuando el código ya viene
explícito en el texto; si no, `buscar_candidatos_cnae` por trigram) + LLM
que elige/confirma entre candidatos (`radar.clasificacion.llm`) -- nunca
clasifica a ciegas por similitud de texto sola.
"""
