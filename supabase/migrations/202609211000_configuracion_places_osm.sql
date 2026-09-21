-- Configuración editable desde el panel (clave de Google Places), control de
-- gasto de Places y nueva fuente libre OpenStreetMap.
--
-- `configuracion_secretos`: SOLO la lee/escribe el worker (conexión directa a
-- Postgres, que no pasa por RLS). RLS activado SIN ninguna política a
-- propósito: ni `anon` ni `authenticated` (el panel vía supabase-js) pueden
-- leer ni escribir esta tabla -- la clave nunca vuelve al navegador, el panel
-- solo puede preguntar al worker "¿hay clave configurada?" (GET /configuracion/...).

create table if not exists configuracion_secretos (
  clave          text primary key,            -- p. ej. 'google_places_api_key'
  valor          text not null,
  actualizado_en timestamptz not null default now()
);
alter table configuracion_secretos enable row level security;

-- Gasto real de Google Places, para aplicar el tope mensual del panel. El coste
-- se calcula con tarifas de lista (ver radar.fuentes.places) -- es una
-- estimación conservadora, no la factura de Google.
create table if not exists uso_google_places (
  id          bigserial primary key,
  creado_en   timestamptz not null default now(),
  operacion   text not null,                  -- 'text_search' | 'prueba_clave'
  peticiones  integer not null default 1,
  coste_eur   numeric(10,4) not null default 0,
  detalle     jsonb not null default '{}'::jsonb
);
create index if not exists uso_google_places_creado_idx on uso_google_places (creado_en);
alter table uso_google_places enable row level security;
drop policy if exists lectura_autenticados on uso_google_places;
create policy lectura_autenticados on uso_google_places for select to authenticated using (true);

-- Fuente libre nueva: OpenStreetMap (Overpass). Licencia ODbL: se puede
-- almacenar citando la fuente. Sin NIF (OSM nunca lo lleva).
insert into fuentes (codigo, nombre, tipo, fiabilidad_base, permite_almacenar, campos_almacenables, grupo_independencia, notas_condiciones) values
  ('osm', 'OpenStreetMap (Overpass API)', 'datos_abiertos', 0.60, true, '{}', 'osm',
   'ODbL: almacenable citando "© OpenStreetMap contributors". Datos aportados por voluntarios: cobertura y frescura irregulares, sin NIF.')
on conflict (codigo) do nothing;
