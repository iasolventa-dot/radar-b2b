-- =====================================================================
-- Radar B2B — Migración 0003: catálogos CNAE versionados y municipios
--
-- Motivo (ver doc 08, decisión propuesta D-18):
--   1. La tabla `cnae` de la migración 0001 tiene `codigo` como clave
--      primaria ella sola, pero los códigos se solapan entre versiones
--      ('41' existe en CNAE-2009 y en CNAE-2025 con contenidos distintos).
--      Cargar las dos versiones a la vez era imposible.
--   2. D-09 da por hecha una tabla de correspondencias CNAE-2009 ↔ CNAE-2025
--      que nunca se creó. La correspondencia NO es 1:1: de las 629 clases
--      de CNAE-2009 solo 425 (68 %) tienen destino único.
--   3. `sedes.municipio_ine` estaba siempre a null porque la tabla
--      `municipios` estaba vacía. No hace falta geocodificar para
--      rellenarlo: es un lookup determinista nombre+provincia.
--
-- Idempotente: se puede aplicar varias veces sin efecto adicional.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. cnae: clave primaria compuesta (codigo, version)
-- ---------------------------------------------------------------------

-- 1.1 Quitar las claves ajenas que apuntan a la PK antigua.
--     Se localizan por introspeccion, no por nombre: el nombre que genera
--     Postgres depende de como se aplicara la migracion 0001, y un
--     `drop constraint if exists` con el nombre equivocado no fallaria,
--     solo dejaria la FK viva y haria fallar el cambio de PK mas abajo
--     con un error dificil de leer.
do $$
declare r record;
begin
  for r in
    select c.conname, t.relname as tabla
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    join pg_class d on d.oid = c.confrelid
    where c.contype = 'f' and d.relname = 'cnae'
  loop
    execute format('alter table %I drop constraint %I', r.tabla, r.conname);
    raise notice 'Eliminada FK % sobre %', r.conname, r.tabla;
  end loop;
end $$;

-- 1.2 A partir de ahora la versión de referencia es CNAE-2025 (D-09).
alter table cnae alter column version set default 'CNAE-2025';

-- 1.3 Sustituir la PK. Si ya es compuesta, no se toca.
do $$
begin
  if exists (
    select 1
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    where t.relname = 'cnae' and c.contype = 'p' and array_length(c.conkey, 1) = 1
  ) then
    alter table cnae drop constraint cnae_pkey;
  end if;

  if not exists (
    select 1
    from pg_constraint c
    join pg_class t on t.oid = c.conrelid
    where t.relname = 'cnae' and c.contype = 'p'
  ) then
    alter table cnae add constraint cnae_pkey primary key (codigo, version);
  end if;
end $$;

-- 1.4 Jerarquía dentro de la MISMA versión (una división de 2025 nunca
--     cuelga de una sección de 2009).
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'cnae_padre_fkey') then
    alter table cnae add constraint cnae_padre_fkey
      foreign key (codigo_padre, version) references cnae (codigo, version);
  end if;
end $$;

create index if not exists ix_cnae_version on cnae (version, nivel);

-- ---------------------------------------------------------------------
-- 2. empresas: el CNAE guardado necesita saber de qué versión es
-- ---------------------------------------------------------------------
-- Trazabilidad (principio 2): se guarda el código TAL COMO lo declara la
-- fuente, con su versión. La traducción a otra versión se hace al
-- consultar, vía `cnae_correspondencias`, no al ingerir — porque en el
-- 32 % de los casos la traducción es ambigua y perderíamos el original.

alter table empresas add column if not exists cnae_version text not null default 'CNAE-2025';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'empresas_cnae_fkey') then
    -- MATCH SIMPLE: si `cnae_principal` es null, la restriccion no se aplica.
    alter table empresas add constraint empresas_cnae_fkey
      foreign key (cnae_principal, cnae_version) references cnae (codigo, version);
  end if;
end $$;

comment on column empresas.cnae_version is
  'Version de la CNAE a la que pertenece cnae_principal y cnae_secundarios. Por defecto CNAE-2025 (D-09).';

-- ---------------------------------------------------------------------
-- 3. Correspondencias entre versiones (relacion N:M)
-- ---------------------------------------------------------------------
create table if not exists cnae_correspondencias (
  codigo_origen   text     not null,
  version_origen  text     not null,
  codigo_destino  text     not null,
  version_destino text     not null,
  nivel           smallint not null,
  creado_en       timestamptz not null default now(),
  primary key (codigo_origen, version_origen, codigo_destino, version_destino)
);

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'cnae_corr_origen_fkey') then
    alter table cnae_correspondencias add constraint cnae_corr_origen_fkey
      foreign key (codigo_origen, version_origen) references cnae (codigo, version) on delete cascade;
  end if;
  if not exists (select 1 from pg_constraint where conname = 'cnae_corr_destino_fkey') then
    alter table cnae_correspondencias add constraint cnae_corr_destino_fkey
      foreign key (codigo_destino, version_destino) references cnae (codigo, version) on delete cascade;
  end if;
end $$;

create index if not exists ix_cnae_corr_destino on cnae_correspondencias (codigo_destino, version_destino);

comment on table cnae_correspondencias is
  'Correspondencias teoricas del INE entre versiones de la CNAE. NO es 1:1: '
  'p. ej. CNAE-2009 41.10 (Promocion inmobiliaria) pasa a CNAE-2025 68.12, '
  'fuera de la division 41. Verificado 2026-09-14 contra los ficheros del INE.';

-- ---------------------------------------------------------------------
-- 4. Municipios: columna normalizada para el lookup
-- ---------------------------------------------------------------------
-- No se usa columna generada ni indice por expresion porque
-- `normalizar_texto` es STABLE (depende de unaccent), no IMMUTABLE.
-- La rellena el seed y la mantiene el trigger de abajo.

alter table municipios add column if not exists nombre_norm text;

create or replace function tg_municipios_normalizar()
returns trigger language plpgsql as $$
begin
  new.nombre_norm := normalizar_texto(new.nombre);
  return new;
end $$;

drop trigger if exists trg_municipios_normalizar on municipios;
create trigger trg_municipios_normalizar before insert or update on municipios
  for each row execute function tg_municipios_normalizar();

-- Unico dentro de una provincia. Verificado 2026-09-14 sobre los 8.132
-- municipios del INE: 0 colisiones de nombre normalizado dentro de una
-- misma provincia (17 nombres se repiten, pero en provincias distintas).
create unique index if not exists ux_municipios_prov_nombre
  on municipios (cod_provincia, nombre_norm);

create index if not exists ix_municipios_nombre_norm on municipios (nombre_norm);

-- ---------------------------------------------------------------------
-- 5. Lookup determinista de codigo INE de municipio
-- ---------------------------------------------------------------------
-- La provincia es OBLIGATORIA: sin ella el nombre puede ser ambiguo
-- (17 municipios homonimos en provincias distintas). Ante la duda se
-- devuelve null y el campo se queda vacio — principio 1: calidad antes
-- que volumen; nunca un codigo inventado.

create or replace function buscar_municipio_ine(p_nombre text, p_provincia text)
returns char(5)
language sql stable as $$
  select m.codigo_ine
  from municipios m
  where m.nombre_norm = normalizar_texto(p_nombre)
    and normalizar_texto(m.provincia) = normalizar_texto(p_provincia)
  limit 1
$$;

comment on function buscar_municipio_ine(text, text) is
  'Devuelve el codigo INE de 5 digitos de un municipio a partir de su nombre '
  'y su provincia, o null si no hay coincidencia exacta tras normalizar. '
  'Maneja la convencion del INE con articulo pospuesto ("Palacios y '
  'Villafranca, Los") frente al texto del BORME ("PALACIOS Y VILLAFRANCA (LOS").';

-- Rellena `sedes.municipio_ine` donde falte. Devuelve cuantas actualizo.
create or replace function actualizar_municipio_ine_sedes()
returns integer
language plpgsql as $$
declare n integer;
begin
  with candidatas as (
    select s.id, buscar_municipio_ine(s.municipio_nombre, s.provincia) as cod
    from sedes s
    where s.municipio_ine is null
      and s.municipio_nombre is not null
      and s.provincia is not null
  )
  update sedes s
     set municipio_ine = c.cod
    from candidatas c
   where s.id = c.id and c.cod is not null;
  get diagnostics n = row_count;
  return n;
end $$;

-- El `insert into sedes` de `radar/orquestador/bd.py` no incluye la columna
-- `municipio_ine` (solo `municipio_nombre` y `provincia`), asi que sin este
-- trigger toda sede nueva seguiria naciendo con el codigo a null y habria
-- que acordarse de lanzar la funcion de arriba a mano cada vez. El trigger
-- lo resuelve en el momento de escribir, venga de donde venga el insert.
-- Nunca pisa un valor puesto a proposito: solo actua si llega null.
create or replace function tg_sedes_municipio_ine()
returns trigger language plpgsql as $$
begin
  if new.municipio_ine is null
     and new.municipio_nombre is not null
     and new.provincia is not null then
    new.municipio_ine := buscar_municipio_ine(new.municipio_nombre, new.provincia);
  end if;
  return new;
end $$;

drop trigger if exists trg_sedes_municipio_ine on sedes;
create trigger trg_sedes_municipio_ine before insert or update on sedes
  for each row execute function tg_sedes_municipio_ine();

-- ---------------------------------------------------------------------
-- 6. Comparacion de CNAE por prefijo (para los filtros del agente)
-- ---------------------------------------------------------------------
-- `consultar_bd` comparaba `sector.codigos_cnae` por igualdad exacta, asi
-- que un filtro por la division '41' nunca casaba con la clase '4101'.
-- Esta funcion resuelve la jerarquia por prefijo: '41' casa con '41',
-- '410', '4101'... y 'F' casa con toda la seccion via `codigo_padre`.

create or replace function cnae_coincide(p_codigo text, p_prefijos text[])
returns boolean
language sql immutable as $$
  select case
    when p_prefijos is null or cardinality(p_prefijos) = 0 then true
    when p_codigo is null then false
    else exists (
      select 1 from unnest(p_prefijos) as p(pref)
      where upper(replace(p.pref, '.', '')) = upper(replace(p_codigo, '.', ''))
         or upper(replace(p_codigo, '.', '')) like upper(replace(p.pref, '.', '')) || '%'
    )
  end
$$;

comment on function cnae_coincide(text, text[]) is
  'True si el codigo CNAE cae bajo alguno de los prefijos dados. '
  'Ignora los puntos, de modo que 41, 41.0 y 4101 son comparables entre si. '
  'Un array vacio o null significa "sin filtro de sector".';

-- ---------------------------------------------------------------------
-- 7. Seguridad (RLS), coherente con la migracion 0001
-- ---------------------------------------------------------------------
alter table cnae_correspondencias enable row level security;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    drop policy if exists lectura_autenticados on cnae_correspondencias;
    create policy lectura_autenticados on cnae_correspondencias
      for select to authenticated using (true);
  end if;
end $$;
