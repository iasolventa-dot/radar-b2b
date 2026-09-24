-- Índice local del BORME (2026-09-25).
--
-- Antes, cada búsqueda descargaba y parseaba de nuevo todos los actos de la
-- provincia para el rango de fechas (~21.000 actos para Madrid en 60 días,
-- varios minutos) aunque la búsqueda anterior ya los hubiera leído. Ahora
-- cada día/provincia se descarga UNA vez y sus actos quedan aquí, lo que
-- permite además buscar una empresa por su denominación exacta para
-- enriquecerla con administradores y hoja registral
-- (radar/agente/enriquecer_borme.py).
create table if not exists borme_actos (
  id                    bigserial primary key,
  fecha                 date not null,
  provincia             text not null,
  identificador_boletin text not null,
  id_borme              text,
  razon_social          text not null,
  razon_social_norm     text not null,
  hoja_registral        text,
  tipos                 text[] not null default '{}',
  domicilio             text,
  codigo_postal         text,
  municipio             text,
  objeto_social         text,
  capital_eur           text,
  administradores       jsonb not null default '[]'::jsonb,
  texto                 text,
  url_html              text,
  url_xml               text,
  unique (identificador_boletin, id_borme, razon_social)
);
create index if not exists borme_actos_nombre_idx on borme_actos (razon_social_norm);
create index if not exists borme_actos_hoja_idx on borme_actos (hoja_registral);
create index if not exists borme_actos_prov_fecha_idx on borme_actos (provincia, fecha);

-- Qué días ya se descargaron (también los que no tenían actos: festivos).
create table if not exists borme_dias_cargados (
  fecha      date not null,
  provincia  text not null,
  n_actos    integer not null default 0,
  cargado_en timestamptz not null default now(),
  primary key (fecha, provincia)
);

alter table borme_actos enable row level security;
alter table borme_dias_cargados enable row level security;
drop policy if exists lectura_autenticados on borme_actos;
create policy lectura_autenticados on borme_actos for select to authenticated using (true);
