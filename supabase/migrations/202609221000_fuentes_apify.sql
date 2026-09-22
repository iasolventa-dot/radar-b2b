-- Amplía qué Actors de Apify puede usar el agente (antes solo el rastreador de
-- webs). Los 4 nuevos usos comparten el mismo token y el mismo tope mensual
-- ya guardados en `configuracion_secretos` / `uso_apify` (migración
-- 202609211500) -- aquí solo se dan de alta las fuentes de datos nuevas.

-- 'linkedin' ya existía en el esquema inicial (202609100001) con
-- permite_almacenar=false -- se dejó así porque entonces no había ningún
-- conector que la usara. Ahora sí lo hay (radar/agente/enriquecer_apify_linkedin.py),
-- así que se habilita. No se edita la migración original (convención del
-- proyecto): se actualiza aquí.
update fuentes set permite_almacenar = true, campos_almacenables = '{}'::text[]
where codigo = 'linkedin';

-- Google Maps vía Apify (compass/crawler-google-places): mismos datos que
-- Google Places pero por scraping en vez de la API oficial -- por eso
-- comparte grupo_independencia='google' con 'google_places' (no cuentan como
-- confirmación independiente entre sí) y tiene una fiabilidad algo menor
-- (0.55 frente a 0.80): más propenso a romperse o quedar desactualizado que
-- una API con contrato.
-- Facebook (páginas de empresa) vía Apify (apify/facebook-pages-scraper):
-- dato que la propia empresa publica, como una web o un LinkedIn -- fiabilidad
-- similar a 'linkedin'.
insert into fuentes (codigo, nombre, tipo, fiabilidad_base, permite_almacenar, campos_almacenables, grupo_independencia, notas_condiciones) values
  ('apify_google_maps', 'Google Maps (vía Apify, no oficial)', 'api_mapas',  0.55, true, '{}', 'google', 'Scraping no oficial (compass/crawler-google-places). Mismos datos subyacentes que Google Places: no cuenta como confirmación independiente de esa fuente.'),
  ('facebook',          'Facebook (página de empresa)',        'red_social', 0.55, true, '{}', 'meta',   'Página pública de empresa (apify/facebook-pages-scraper). Evaluar como cualquier fuente.')
on conflict (codigo) do nothing;
