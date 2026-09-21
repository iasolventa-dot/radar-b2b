-- Opciones por búsqueda: qué fuentes de pago se permiten en ESTA búsqueda
-- (casillas del formulario "Nueva búsqueda"): {"usar_google_places": bool, "usar_apify": bool}.
-- Columna aparte (no dentro de `estadisticas`) porque el planificador reescribe
-- `estadisticas` entera tras cada ronda.
alter table busquedas add column if not exists opciones jsonb not null default '{}'::jsonb;
