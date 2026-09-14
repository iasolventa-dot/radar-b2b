-- 202609141200_normalizar_ccaa.sql
--
-- ubicacion.ccaa (interpretacion.py) se capturaba desde la primera sesión
-- del agente pero nunca se usaba en construir_where_empresas -- doc 08.
-- Al ir a activarlo aparece el mismo problema que ya tuvimos con los
-- municipios truncados del BORME (migracion 202609140001), pero peor: el
-- INE no solo usa mayusculas/tildes distintas, tambien pospone el
-- articulo y reordena la frase entera:
--
--   INE (municipios.ccaa)          Como lo escribiria una persona o un LLM
--   ------------------------------ --------------------------------------
--   Rioja, La                      La Rioja
--   Madrid, Comunidad de           Comunidad de Madrid
--   Asturias, Principado de        Principado de Asturias
--   Murcia, Región de              Región de Murcia
--   Navarra, Comunidad Foral de    Comunidad Foral de Navarra
--   Balears, Illes                 Illes Balears
--
-- extensions.unaccent + lower (lo que ya hace normalizar_texto) no basta
-- aqui: son las mismas palabras en OTRO ORDEN, no solo con tildes/mayus-
-- culas distintas. normalizar_ccaa quita ademas los articulos/preposi-
-- ciones mas comunes y ordena alfabeticamente las palabras que quedan,
-- asi el orden deja de importar. Verificado sobre los 19 valores reales
-- de "ccaa" en la tabla municipios (2026-09-14): las 6 variantes de
-- arriba normalizan igual en los dos ordenes.

create or replace function normalizar_ccaa(t text)
returns text
language sql immutable as $$
  select coalesce(string_agg(palabra, ' ' order by palabra), '')
  from unnest(
    string_to_array(
      regexp_replace(lower(extensions.unaccent(coalesce(t, ''))), '[^a-z ]+', ' ', 'g'),
      ' '
    )
  ) as palabra
  where palabra <> '' and palabra not in ('de', 'del', 'la', 'las', 'el', 'los')
$$;

comment on function normalizar_ccaa(text) is
  'Normaliza un nombre de CCAA para comparar sin que importe el orden de '
  'las palabras ni los articulos/preposiciones -- "La Rioja" y "Rioja, La" '
  'normalizan igual. Usada por construir_where_empresas (ubicacion.ccaa), '
  'doc 08.';
