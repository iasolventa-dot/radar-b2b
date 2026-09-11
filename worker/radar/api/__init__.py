"""Endpoint HTTP del worker (tarea #22, doc 02 §3: "Frontend Next.js en
Vercel — chat con el agente..."): la única forma en que la web (`web/`,
Vercel) puede lanzar una búsqueda con el agente y consultar su progreso,
sin hablar nunca directo con Python ni con las claves de LLM.

Por qué hace falta esto y no basta con que la web llame a Supabase
directamente (como hace hoy el panel del golden set, doc D-13): lanzar una
búsqueda ejecuta `radar.agente.planificador.planificar`, que puede tardar
varios minutos en varias rondas de peticiones de red reales — no cabe en
una function serverless de Vercel con timeout corto, y las claves de
OpenAI/Anthropic no deben llegar nunca al navegador. El worker (Railway,
D-07, siempre encendido) es el único sitio con esas claves y con tiempo de
sobra para procesos largos (doc 02 §3, "¿Por qué el worker en Python...").

Ver `radar.api.main` para los endpoints, `radar.api.esquemas` para los
modelos de petición/respuesta y `radar.api.estado` para cómo se traduce el
`ResultadoPlanificador` de una ronda a lo que se guarda en `busquedas`.
"""
