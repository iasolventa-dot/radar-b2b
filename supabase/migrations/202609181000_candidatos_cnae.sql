-- 202609181000_candidatos_cnae.sql
--
-- Clasificador objeto_social -> CNAE (pendiente desde la sesión de
-- auditoría del 14-16/09: "se empezó a construir... no confirmado si se
-- terminó" -- no se terminó, no existía ningún módulo `cnae*` en
-- worker/radar). Mismo patrón que ya usa la resolución de duplicados
-- (blocking.buscar_candidatos + resolucion/arbitraje.py, ver commit
-- "duplicados sin NIF no llegaban ni a revision", 2026-09-18): bloqueo
-- determinista por similitud de texto (aquí, trigram contra
-- cnae.descripcion) que genera candidatos, y el LLM elige/confirma entre
-- ellos (radar/clasificacion/llm.py) -- nunca clasifica a ciegas por
-- similitud sola, el catálogo CNAE tiene descripciones demasiado parecidas
-- entre categorías vecinas para fiarse de un solo número.
--
-- Solo nivel 4 (el más específico, "grupo" en la jerga del INE, p. ej.
-- "4322") -- es el nivel que ya usan `codigos_cnae` en la interpretación
-- del agente y `cnae_coincide()` (migración 202609140001).
--
-- Sin índice GIN trigram: `normalizar_texto()` es `stable`, no `immutable`
-- (llama a `extensions.unaccent`, que tampoco lo es), así que Postgres
-- rechaza indexarla (42P17). No hace falta -- solo 664 filas en nivel 4 de
-- CNAE-2025, un escaneo secuencial con similitud calculada al vuelo es
-- instantáneo; el índice trigram de verdad importante ya existe en
-- `empresas.razon_social_norm` (migración inicial), que sí es una tabla
-- que crece.
create or replace function buscar_candidatos_cnae(
  p_texto text,
  p_version text default 'CNAE-2025',
  p_limite int default 8
)
returns table (codigo text, descripcion text, similitud real)
language sql stable as $$
  select c.codigo, c.descripcion,
         extensions.similarity(normalizar_texto(c.descripcion), normalizar_texto(p_texto)) as similitud
  from cnae c
  where c.nivel = 4 and c.version = p_version
    and normalizar_texto(c.descripcion) operator(extensions.%) normalizar_texto(p_texto)
  order by similitud desc
  limit p_limite
$$;

comment on function buscar_candidatos_cnae(text, text, int) is
  'Bloqueo determinista (trigram) para el clasificador objeto_social -> CNAE
  (radar.clasificacion): candidatos de nivel 4 a partir de la descripción
  del objeto social, para que el LLM elija entre ellos -- nunca decide la
  similitud sola, ver radar/clasificacion/llm.py.';
