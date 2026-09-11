-- =====================================================================
-- Radar B2B — Cola de revisión del golden set (migración 0002)
-- Tablas de trabajo para promover candidatos de registros_entrada.csv
-- (generados por worker/scripts/generar_candidatos_golden.py) a
-- entidades verificadas, desde el panel web (D-13, worker/tests/golden/README.md).
--
-- Estas tablas NO son la capa oro del doc 03 (empresas/sedes/...): son el
-- taller de construcción del golden set en sí (doc 07 §6). Cuando el golden
-- set esté completo, `golden_entidades` es lo que se usa para evaluar el
-- pipeline (`worker/tests/golden/evaluar.py`), no una fuente de producción.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. golden_candidatos — candidatos generados automáticamente (BORME, etc.)
-- ---------------------------------------------------------------------
do $$ begin
  create type estado_revision_candidato as enum ('pendiente', 'promovido', 'descartado');
exception when duplicate_object then null; end $$;

create table if not exists golden_candidatos (
  id_fila                 text primary key,          -- p.ej. 'BORME-407615'
  categoria_candidato     text not null,              -- pool_normal_construccion, candidato_grupo, ...
  confianza_sector        text,                       -- alta / media / baja / vacío
  fuente                  text not null,              -- 'borme', ...
  id_externo               text,
  razon_social             text not null,
  municipio                text,
  codigo_postal            text,
  es_municipio_principal   boolean not null default false,
  hoja_registral           text,
  tipos_acto               text[] not null default '{}',
  objeto_social            text,
  capital_eur              text,
  administradores          text[] not null default '{}',
  posible_homonimo_de      text[] not null default '{}',
  posible_grupo_con        text[] not null default '{}',
  url_evidencia            text,
  fecha_publicacion        text,
  identificador_boletin    text,
  estado_revision          estado_revision_candidato not null default 'pendiente',
  entidad_id_real          text,                      -- rellenado al promover (ver golden_entidades.id_golden)
  notas                    text,
  creado_en                timestamptz not null default now(),
  actualizado_en           timestamptz not null default now()
);

drop trigger if exists trg_golden_candidatos_actualizado on golden_candidatos;
create trigger trg_golden_candidatos_actualizado before update on golden_candidatos
  for each row execute function tg_actualizado_en();

create index if not exists idx_golden_candidatos_categoria on golden_candidatos (categoria_candidato);
create index if not exists idx_golden_candidatos_estado on golden_candidatos (estado_revision);

-- ---------------------------------------------------------------------
-- 2. golden_entidades — verdad verificada a mano (doc 07 §6)
-- ---------------------------------------------------------------------
create table if not exists golden_entidades (
  id_golden                     text primary key,      -- p.ej. 'GS-0001'
  nif                           text,
  razon_social                  text not null,
  nombre_comercial              text,
  forma_juridica                text,
  es_persona_fisica             boolean not null default false,
  cnae_principal                text,
  estado                        estado_empresa,
  municipio                     text,
  municipio_ine                 text,
  provincia                     text,
  cp                            text,
  direccion_domicilio_social    text,
  direccion_sede_operativa      text,
  telefono                      text,
  telefono_verificado_llamada   text check (telefono_verificado_llamada in ('si','no','no_aplica')) default 'no_aplica',
  web                           text,
  email_generico                text,
  caso_dificil                  text check (caso_dificil in (
                                   'homonimo','franquicia','grupo','disuelta','traslado',
                                   'autonomo','web_agencia','nombre_generico'
                                 )),
  fuente_verificacion           text,
  url_evidencia                 text,
  fecha_verificacion            date,
  verificado_por                text,
  notas                         text,
  candidato_origen_id           text references golden_candidatos(id_fila),
  creado_en                     timestamptz not null default now(),
  actualizado_en                timestamptz not null default now()
);

drop trigger if exists trg_golden_entidades_actualizado on golden_entidades;
create trigger trg_golden_entidades_actualizado before update on golden_entidades
  for each row execute function tg_actualizado_en();

create index if not exists idx_golden_entidades_caso_dificil on golden_entidades (caso_dificil);

-- ---------------------------------------------------------------------
-- 3. Seguridad (RLS)
--
-- A diferencia de la capa oro (doc 03 §11, donde la web solo lee y el
-- worker con service_role escribe), estas dos tablas SÍ se editan desde
-- el panel web: es su función. Mientras el proyecto sea de un único
-- usuario interno, cualquier usuario autenticado puede leer y escribir
-- (se restringirá por email o rol cuando haya más de una persona
-- revisando, igual que el resto del esquema — doc 03 §6, punto 5).
-- ---------------------------------------------------------------------
alter table golden_candidatos enable row level security;
alter table golden_entidades enable row level security;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    drop policy if exists autenticados_todo on golden_candidatos;
    create policy autenticados_todo on golden_candidatos
      for all to authenticated using (true) with check (true);

    drop policy if exists autenticados_todo on golden_entidades;
    create policy autenticados_todo on golden_entidades
      for all to authenticated using (true) with check (true);
  end if;
end $$;
