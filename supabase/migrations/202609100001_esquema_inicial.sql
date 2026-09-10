-- =====================================================================
-- Radar B2B — Esquema inicial (migración 0001)
-- Postgres / Supabase. Probado en PostgreSQL 16 + PostGIS 3.
-- Aplicar como: supabase/migrations/202609100001_esquema_inicial.sql
--
-- Capas:
--   BRONCE  registros_brutos      → lo que devuelve cada fuente, tal cual
--   PLATA   observaciones         → cada dato normalizado, con fuente y fecha
--   ORO     empresas, sedes,      → registro consolidado ("golden record")
--           canales_contacto,       con confianza y última verificación
--           identificadores
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. Extensiones (en Supabase viven en el esquema "extensions")
-- ---------------------------------------------------------------------
create schema if not exists extensions;
create extension if not exists pg_trgm  with schema extensions;
create extension if not exists unaccent with schema extensions;
create extension if not exists postgis  with schema extensions;

-- ---------------------------------------------------------------------
-- 1. Tipos enumerados
-- ---------------------------------------------------------------------
do $$ begin
  create type estado_empresa as enum (
    'activa',               -- confirmada activa por fuente fiable y reciente
    'probablemente_activa', -- señales de actividad, sin confirmación fuerte
    'dudosa',               -- señales contradictorias
    'inactiva',             -- sin actividad detectable (web caída, cerrada en mapas…)
    'en_liquidacion',
    'en_concurso',
    'disuelta',
    'extinguida',
    'desconocida'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type tipo_fuente as enum (
    'registro_oficial', 'datos_abiertos', 'api_mapas', 'buscador',
    'web_empresa', 'directorio', 'red_social', 'proveedor_comercial',
    'manual', 'inferencia_llm'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type tipo_canal as enum ('telefono', 'email', 'web', 'linkedin', 'facebook', 'instagram', 'x', 'youtube', 'otro');
exception when duplicate_object then null; end $$;

do $$ begin
  create type tipo_sede as enum ('domicilio_social', 'domicilio_fiscal', 'sede_operativa', 'delegacion', 'establecimiento', 'almacen', 'desconocido');
exception when duplicate_object then null; end $$;

do $$ begin
  create type estado_resolucion as enum ('pendiente', 'vinculado', 'nueva_empresa', 'en_revision', 'descartado', 'error');
exception when duplicate_object then null; end $$;

do $$ begin
  create type estado_revision as enum ('pendiente', 'confirmado_duplicado', 'rechazado', 'aplazado');
exception when duplicate_object then null; end $$;

do $$ begin
  create type rango_tamano as enum ('micro', 'pequena', 'mediana', 'grande', 'desconocido');
exception when duplicate_object then null; end $$;

-- ---------------------------------------------------------------------
-- 2. Funciones auxiliares
-- ---------------------------------------------------------------------

-- Normaliza texto para comparar: minúsculas, sin tildes, sin signos, espacios simples.
create or replace function normalizar_texto(t text)
returns text language sql stable as $$
  select nullif(
    trim(regexp_replace(
      regexp_replace(lower(extensions.unaccent(coalesce(t, ''))), '[^a-z0-9ñ ]', ' ', 'g'),
      '\s+', ' ', 'g')),
    '')
$$;

-- Normaliza una razón social quitando la forma jurídica (SL, SA, SLU, S COOP…)
-- para poder comparar "Construcciones Pérez, S.L." con "CONSTRUCCIONES PEREZ SL".
create or replace function normalizar_razon_social(t text)
returns text language sql stable as $$
  select nullif(trim(regexp_replace(
    ' ' || coalesce(normalizar_texto(
      regexp_replace(coalesce(t, ''), '(?i)s\.\s*l\.\s*u\.?|s\.\s*l\.?|s\.\s*a\.\s*u\.?|s\.\s*a\.?|s\.\s*coop\.?\s*(and\.?)?|s\.\s*l\.\s*l\.?|s\.\s*a\.\s*l\.?|s\.\s*c\.?|c\.\s*b\.?', ' ', 'g')
    ), '') || ' ',
    ' (sociedad limitada unipersonal|sociedad limitada laboral|sociedad limitada|sociedad anonima unipersonal|sociedad anonima laboral|sociedad anonima|sociedad cooperativa andaluza|sociedad cooperativa|sociedad civil|comunidad de bienes|slu|sl|sa|sau|sll|sal|slne|scoop|sca|coop|scp|sc|cb) ',
    ' ', 'g')), '')
$$;

-- updated_at automático
create or replace function tg_actualizado_en()
returns trigger language plpgsql as $$
begin
  new.actualizado_en := now();
  return new;
end $$;

-- ---------------------------------------------------------------------
-- 3. Catálogos
-- ---------------------------------------------------------------------

-- Fuentes de datos y sus condiciones (ver doc 04)
create table if not exists fuentes (
  id                  smallserial primary key,
  codigo              text not null unique,          -- 'borme', 'google_places', 'web_empresa', 'rea'…
  nombre              text not null,
  tipo                tipo_fuente not null,
  fiabilidad_base     numeric(3,2) not null check (fiabilidad_base between 0 and 1),
  permite_almacenar   boolean not null default false, -- ¿las condiciones permiten persistir su contenido?
  campos_almacenables text[] not null default '{}',   -- p. ej. Google Places: '{place_id}'
  grupo_independencia text,                           -- fuentes del mismo grupo NO cuentan como confirmación independiente
  notas_condiciones   text,
  activa              boolean not null default true,
  creado_en           timestamptz not null default now()
);

-- CNAE (cargar CNAE-2025 como principal, con correspondencia a CNAE-2009; ver D-09)
create table if not exists cnae (
  codigo       text primary key,        -- '4121', '41', 'F'
  version      text not null default 'CNAE-2025',
  descripcion  text not null,
  nivel        smallint not null,       -- 1 sección, 2 división, 3 grupo, 4 clase
  codigo_padre text references cnae(codigo)
);

-- Municipios INE (código de 5 dígitos: 2 de provincia + 3 de municipio)
create table if not exists municipios (
  codigo_ine   char(5) primary key,
  nombre       text not null,
  provincia    text not null,
  cod_provincia char(2) not null,
  ccaa         text not null,
  geom         extensions.geography(MultiPolygon, 4326)   -- opcional: límites municipales (IGN)
);

-- Sectores propios (taxonomía comercial) mapeados a CNAE + palabras clave
create table if not exists sectores (
  id              serial primary key,
  nombre          text not null unique,         -- 'Reformas integrales'
  codigos_cnae    text[] not null default '{}',
  palabras_clave  text[] not null default '{}', -- para buscar en objeto social / web
  descripcion     text
);

-- ---------------------------------------------------------------------
-- 4. Capa ORO: empresas y lo que cuelga de ellas
-- ---------------------------------------------------------------------
create table if not exists empresas (
  id                    uuid primary key default gen_random_uuid(),
  nif                   text unique,                 -- CIF/NIF normalizado (B12345678). Null si aún no se conoce
  nif_valido            boolean,                     -- dígito de control correcto
  razon_social          text,                        -- denominación legal
  razon_social_norm     text,                        -- rellenado por trigger
  nombre_comercial      text,
  nombre_comercial_norm text,
  forma_juridica        text,                        -- 'SL', 'SA', 'SCOOP', 'AUTONOMO'…
  es_persona_fisica     boolean not null default false, -- autónomos / empresarios individuales
  estado                estado_empresa not null default 'desconocida',
  estado_confianza      numeric(3,2),
  estado_verificado_en  timestamptz,
  fecha_constitucion    date,
  objeto_social         text,
  cnae_principal        text references cnae(codigo),
  cnae_secundarios      text[] not null default '{}',
  sector_id             int references sectores(id),
  tamano                rango_tamano not null default 'desconocido',
  empleados_min         int,
  empleados_max         int,
  tamano_fuente         text,
  dominio_web           text,                        -- 'ejemplo.es' (sin www)
  confianza_global      numeric(3,2),                -- calculada (doc 05)
  ultima_verificacion   timestamptz,
  fusionada_en          uuid references empresas(id), -- si se fusionó, apunta a la superviviente
  creado_en             timestamptz not null default now(),
  actualizado_en        timestamptz not null default now(),
  constraint chk_empleados check (empleados_min is null or empleados_max is null or empleados_min <= empleados_max)
);

create index if not exists ix_empresas_razon_trgm   on empresas using gin (razon_social_norm extensions.gin_trgm_ops);
create index if not exists ix_empresas_comercial_trgm on empresas using gin (nombre_comercial_norm extensions.gin_trgm_ops);
create index if not exists ix_empresas_dominio      on empresas (dominio_web);
create index if not exists ix_empresas_cnae         on empresas (cnae_principal);
create index if not exists ix_empresas_estado       on empresas (estado);
create index if not exists ix_empresas_activas      on empresas (id) where fusionada_en is null;

create or replace function tg_empresas_normalizar()
returns trigger language plpgsql as $$
begin
  new.razon_social_norm     := normalizar_razon_social(new.razon_social);
  new.nombre_comercial_norm := normalizar_razon_social(new.nombre_comercial);
  new.nif                   := nullif(upper(regexp_replace(coalesce(new.nif, ''), '[^A-Za-z0-9]', '', 'g')), '');
  new.dominio_web           := nullif(lower(regexp_replace(coalesce(new.dominio_web, ''), '^(https?://)?(www\.)?|/.*$', '', 'g')), '');
  return new;
end $$;

drop trigger if exists trg_empresas_normalizar on empresas;
create trigger trg_empresas_normalizar before insert or update on empresas
  for each row execute function tg_empresas_normalizar();
drop trigger if exists trg_empresas_actualizado on empresas;
create trigger trg_empresas_actualizado before update on empresas
  for each row execute function tg_actualizado_en();

-- Identificadores externos (un registro por identificador)
create table if not exists identificadores (
  id          bigserial primary key,
  empresa_id  uuid not null references empresas(id) on delete cascade,
  tipo        text not null,          -- 'nif','vat_ue','google_place_id','linkedin_url','borme_hoja','rea','dominio'…
  valor       text not null,
  fuente_id   smallint references fuentes(id),
  verificado  boolean not null default false,
  creado_en   timestamptz not null default now(),
  unique (tipo, valor)                -- un mismo place_id no puede pertenecer a dos empresas
);
create index if not exists ix_identificadores_empresa on identificadores (empresa_id);

-- Sedes / ubicaciones
create table if not exists sedes (
  id                  uuid primary key default gen_random_uuid(),
  empresa_id          uuid not null references empresas(id) on delete cascade,
  tipo                tipo_sede not null default 'desconocido',
  direccion_original  text,
  tipo_via            text,
  nombre_via          text,
  numero              text,
  resto               text,              -- piso, nave, polígono…
  codigo_postal       char(5),
  municipio_ine       char(5) references municipios(codigo_ine),
  municipio_nombre    text,
  provincia           text,
  pais                char(2) not null default 'ES',
  geom                extensions.geography(Point, 4326),
  geocodificador      text,              -- 'cartociudad', 'manual'…
  precision_geo       text,              -- 'portal', 'calle', 'municipio'
  activa              boolean not null default true,
  confianza           numeric(3,2),
  ultima_verificacion timestamptz,
  creado_en           timestamptz not null default now(),
  actualizado_en      timestamptz not null default now(),
  constraint chk_cp check (codigo_postal is null or codigo_postal ~ '^(0[1-9]|[1-4][0-9]|5[0-2])[0-9]{3}$')
);
create index if not exists ix_sedes_empresa   on sedes (empresa_id);
create index if not exists ix_sedes_geom      on sedes using gist (geom);
create index if not exists ix_sedes_municipio on sedes (municipio_ine);
create index if not exists ix_sedes_cp        on sedes (codigo_postal);
drop trigger if exists trg_sedes_actualizado on sedes;
create trigger trg_sedes_actualizado before update on sedes
  for each row execute function tg_actualizado_en();

-- Canales de contacto (teléfonos, emails, webs, redes)
create table if not exists canales_contacto (
  id                  uuid primary key default gen_random_uuid(),
  empresa_id          uuid not null references empresas(id) on delete cascade,
  sede_id             uuid references sedes(id) on delete set null,
  tipo                tipo_canal not null,
  valor               text not null,          -- tal como se mostrará
  valor_norm          text not null,          -- teléfono E.164, email en minúsculas, URL canónica
  es_generico         boolean,                -- info@, centralita… (true) vs. personal (false)
  es_movil            boolean,
  estado              text not null default 'sin_verificar', -- 'verificado','sin_verificar','invalido','baja'
  confianza           numeric(3,2),
  ultima_verificacion timestamptz,
  creado_en           timestamptz not null default now(),
  actualizado_en      timestamptz not null default now(),
  unique (empresa_id, tipo, valor_norm)
);
create index if not exists ix_canales_valor on canales_contacto (tipo, valor_norm); -- para detectar el mismo teléfono en dos empresas
drop trigger if exists trg_canales_actualizado on canales_contacto;
create trigger trg_canales_actualizado before update on canales_contacto
  for each row execute function tg_actualizado_en();

-- ---------------------------------------------------------------------
-- 5. Búsquedas (trabajos del agente)
-- ---------------------------------------------------------------------
create table if not exists busquedas (
  id                uuid primary key default gen_random_uuid(),
  usuario_id        uuid,                      -- auth.users(id) en Supabase
  peticion          text not null,             -- texto original del usuario
  filtros           jsonb not null default '{}'::jsonb, -- filtros estructurados confirmados
  presupuesto_eur   numeric(8,2),
  estado            text not null default 'pendiente', -- 'pendiente','en_curso','completada','cancelada','error'
  rondas            int not null default 0,
  estadisticas      jsonb not null default '{}'::jsonb, -- candidatos, verificadas, duplicados, por fuente…
  coste_eur         numeric(10,4) not null default 0,
  creado_en         timestamptz not null default now(),
  finalizado_en     timestamptz
);

create table if not exists busqueda_resultados (
  busqueda_id  uuid not null references busquedas(id) on delete cascade,
  empresa_id   uuid not null references empresas(id) on delete cascade,
  relevancia   numeric(3,2),
  motivo       text,                   -- por qué encaja con los filtros
  primary key (busqueda_id, empresa_id)
);

-- ---------------------------------------------------------------------
-- 6. Capa BRONCE: registros brutos por fuente
-- ---------------------------------------------------------------------
create table if not exists registros_brutos (
  id                 uuid primary key default gen_random_uuid(),
  busqueda_id        uuid references busquedas(id) on delete set null,
  fuente_id          smallint not null references fuentes(id),
  id_externo         text,                    -- id en la fuente (place_id, id de anuncio BORME…)
  url                text,
  payload            jsonb not null,          -- respuesta cruda (solo si la fuente permite almacenarla)
  campos             jsonb not null default '{}'::jsonb, -- campos extraídos con el contrato del doc 02
  hash_contenido     text,                    -- para no reprocesar lo mismo
  capturado_en       timestamptz not null default now(),
  estado             estado_resolucion not null default 'pendiente',
  empresa_id         uuid references empresas(id) on delete set null,
  puntuacion_match   numeric(4,3),
  error              text
);
create index if not exists ix_brutos_estado  on registros_brutos (estado);
create index if not exists ix_brutos_fuente  on registros_brutos (fuente_id, id_externo);
create unique index if not exists ux_brutos_hash on registros_brutos (fuente_id, hash_contenido) where hash_contenido is not null;

-- ---------------------------------------------------------------------
-- 7. Capa PLATA: observaciones (evidencia a nivel de campo)
-- ---------------------------------------------------------------------
-- Cada vez que una fuente afirma algo de una empresa, se guarda una fila.
-- El valor consolidado en la capa ORO se calcula a partir de estas filas (doc 05).
create table if not exists observaciones (
  id                 bigserial primary key,
  empresa_id         uuid not null references empresas(id) on delete cascade,
  registro_bruto_id  uuid references registros_brutos(id) on delete set null,
  fuente_id          smallint not null references fuentes(id),
  campo              text not null,        -- 'nif','razon_social','telefono','direccion','estado','empleados','web'…
  valor_original     text,
  valor_norm         text,
  url_evidencia      text,
  ruta_evidencia     text,                 -- ruta en Supabase Storage (captura HTML), si se permite
  observado_en       timestamptz not null default now(),
  confianza_fuente   numeric(3,2),         -- fiabilidad de ESA fuente para ESE campo
  vigente            boolean not null default true  -- false si otra observación posterior la contradice/sustituye
);
create index if not exists ix_obs_empresa_campo on observaciones (empresa_id, campo);
create index if not exists ix_obs_valor on observaciones (campo, valor_norm);

-- ---------------------------------------------------------------------
-- 8. Resolución de entidades: candidatos a duplicado y fusiones
-- ---------------------------------------------------------------------
create table if not exists candidatos_duplicado (
  id            bigserial primary key,
  empresa_a     uuid not null references empresas(id) on delete cascade,
  empresa_b     uuid not null references empresas(id) on delete cascade,
  puntuacion    numeric(4,3) not null,
  senales       jsonb not null default '{}'::jsonb,  -- qué coincide y qué choca
  opinion_llm   jsonb,                               -- veredicto y razonamiento del arbitraje
  estado        estado_revision not null default 'pendiente',
  revisado_por  text,
  revisado_en   timestamptz,
  creado_en     timestamptz not null default now(),
  constraint chk_orden check (empresa_a < empresa_b),
  unique (empresa_a, empresa_b)
);

create table if not exists fusiones (
  id              bigserial primary key,
  empresa_origen  uuid not null,       -- la que desaparece (se conserva con fusionada_en)
  empresa_destino uuid not null references empresas(id),
  motivo          text not null,
  puntuacion      numeric(4,3),
  decidido_por    text not null,       -- 'auto','llm','usuario:<id>'
  instantanea     jsonb,               -- copia del registro origen antes de fusionar (para deshacer)
  creado_en       timestamptz not null default now()
);

-- Eventos de verificación / cambios (historial legible)
create table if not exists eventos_empresa (
  id          bigserial primary key,
  empresa_id  uuid not null references empresas(id) on delete cascade,
  tipo        text not null,     -- 'cambio_estado','cambio_domicilio','telefono_invalido','web_caida','borme_acto'…
  detalle     jsonb not null default '{}'::jsonb,
  fuente_id   smallint references fuentes(id),
  creado_en   timestamptz not null default now()
);
create index if not exists ix_eventos_empresa on eventos_empresa (empresa_id, creado_en desc);

-- ---------------------------------------------------------------------
-- 9. Vistas útiles
-- ---------------------------------------------------------------------

-- Empresas "entregables": no fusionadas, activas o probablemente activas.
create or replace view v_empresas_entregables as
select e.*,
       s.municipio_nombre, s.provincia, s.codigo_postal,
       (select c.valor from canales_contacto c
         where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado <> 'invalido'
         order by c.confianza desc nulls last limit 1) as telefono_principal,
       (select c.valor from canales_contacto c
         where c.empresa_id = e.id and c.tipo = 'email' and c.es_generico is true and c.estado <> 'invalido'
         order by c.confianza desc nulls last limit 1) as email_generico
from empresas e
left join lateral (
  select * from sedes s
  where s.empresa_id = e.id and s.activa
  order by (s.tipo = 'sede_operativa') desc, (s.tipo = 'domicilio_social') desc, s.confianza desc nulls last
  limit 1
) s on true
where e.fusionada_en is null
  and e.estado in ('activa', 'probablemente_activa');

-- Pares de empresas que comparten teléfono (posibles duplicados o centralitas compartidas)
create or replace view v_telefonos_compartidos as
select c1.valor_norm as telefono, c1.empresa_id as empresa_a, c2.empresa_id as empresa_b
from canales_contacto c1
join canales_contacto c2
  on c1.tipo = 'telefono' and c2.tipo = 'telefono'
 and c1.valor_norm = c2.valor_norm and c1.empresa_id < c2.empresa_id;

-- ---------------------------------------------------------------------
-- 10. Búsqueda de candidatos para matching (usada por el worker)
-- ---------------------------------------------------------------------
-- Devuelve empresas parecidas por nombre, opcionalmente cerca de un punto.
create or replace function buscar_candidatos_empresa(
  p_nombre text,
  p_lon double precision default null,
  p_lat double precision default null,
  p_radio_m int default 20000,
  p_limite int default 20
)
returns table (empresa_id uuid, razon_social text, nombre_comercial text, nif text,
               similitud real, distancia_m double precision)
language sql stable as $$
  with q as (select normalizar_razon_social(p_nombre) as n)
  select e.id, e.razon_social, e.nombre_comercial, e.nif,
         greatest(extensions.similarity(e.razon_social_norm, q.n),
                  coalesce(extensions.similarity(e.nombre_comercial_norm, q.n), 0)) as similitud,
         case when p_lon is null then null
              else (select min(extensions.st_distance(s.geom, extensions.st_setsrid(extensions.st_makepoint(p_lon, p_lat), 4326)::extensions.geography))
                    from sedes s where s.empresa_id = e.id and s.geom is not null) end as distancia_m
  from empresas e, q
  where e.fusionada_en is null
    and (e.razon_social_norm operator(extensions.%) q.n or e.nombre_comercial_norm operator(extensions.%) q.n)
    and (p_lon is null or exists (
          select 1 from sedes s where s.empresa_id = e.id and s.geom is not null
            and extensions.st_dwithin(s.geom, extensions.st_setsrid(extensions.st_makepoint(p_lon, p_lat), 4326)::extensions.geography, p_radio_m)))
  order by similitud desc
  limit p_limite
$$;

-- ---------------------------------------------------------------------
-- 11. Seguridad (RLS). El worker usa la service_role key (se salta RLS).
--     Los usuarios autenticados de la web solo leen. Ajustar en Fase 5.
-- ---------------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['fuentes','cnae','municipios','sectores','empresas','identificadores','sedes',
                           'canales_contacto','busquedas','busqueda_resultados','registros_brutos',
                           'observaciones','candidatos_duplicado','fusiones','eventos_empresa']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;
end $$;

-- En Supabase existe el rol "authenticated". Se crea la política solo si el rol existe
-- (así el script también funciona en un Postgres local de pruebas).
do $$
declare t text;
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    foreach t in array array['fuentes','cnae','municipios','sectores','empresas','identificadores','sedes',
                             'canales_contacto','busquedas','busqueda_resultados','eventos_empresa']
    loop
      execute format('drop policy if exists lectura_autenticados on %I', t);
      execute format('create policy lectura_autenticados on %I for select to authenticated using (true)', t);
    end loop;
  end if;
end $$;

-- ---------------------------------------------------------------------
-- 12. Datos iniciales de fuentes (fiabilidades de partida; calibrar con el golden set)
-- ---------------------------------------------------------------------
insert into fuentes (codigo, nombre, tipo, fiabilidad_base, permite_almacenar, campos_almacenables, grupo_independencia, notas_condiciones) values
  ('borme',          'BORME (Boletín Oficial del Registro Mercantil)', 'registro_oficial', 0.95, true,  '{}', 'registro_mercantil', 'Publicación oficial.'),
  ('placsp',         'Plataforma de Contratación del Sector Público',   'datos_abiertos',   0.90, true,  '{}', 'sector_publico',     'Datos abiertos de licitaciones y adjudicatarios.'),
  ('rea',            'Registro de Empresas Acreditadas (construcción)', 'registro_oficial', 0.90, true,  '{}', 'rea',                'Consulta pública por CCAA. Verificar condiciones de reutilización.'),
  ('web_empresa',    'Web corporativa (aviso legal, contacto)',         'web_empresa',      0.85, true,  '{}', 'web_propia',         'Respetar robots.txt. Aviso legal obligatorio por LSSI art. 10.'),
  ('cartociudad',    'CartoCiudad (IGN) — geocodificación',             'datos_abiertos',   0.90, true,  '{}', 'ign',                'Datos abiertos. Citar fuente.'),
  ('google_places',  'Google Places API',                               'api_mapas',        0.80, false, '{place_id}', 'google',     'Solo place_id almacenable indefinidamente. Revisar términos EEA vigentes.'),
  ('buscador_web',   'API de buscador web',                             'buscador',         0.40, false, '{}', 'buscador',           'Solo para descubrir URLs; los snippets no son evidencia suficiente.'),
  ('directorio',     'Directorios de empresas genéricos',               'directorio',       0.50, false, '{}', 'directorios',        'Se copian entre sí: nunca cuentan como confirmación independiente entre ellos.'),
  ('linkedin',       'LinkedIn (página de empresa / perfil)',           'red_social',       0.60, false, '{}', 'linkedin',           'Evaluar como cualquier fuente; cuidado con bloqueos/rate limits técnicos de la plataforma.'),
  ('manual',         'Verificación manual',                             'manual',           0.98, true,  '{}', 'manual',             'Llamada o comprobación humana documentada.'),
  ('inferencia_llm', 'Inferencia de un LLM sin evidencia directa',      'inferencia_llm',   0.20, true,  '{}', 'llm',                'Nunca basta por sí sola para marcar un dato como verificado.')
on conflict (codigo) do nothing;
