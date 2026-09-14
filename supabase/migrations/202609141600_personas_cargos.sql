-- 202609141600_personas_cargos.sql
--
-- doc 03 §7 lo dejaba explícitamente pendiente: "Tabla de personas con
-- cargo (administradores del BORME)... queda pendiente solo de diseño de
-- esquema". Opción elegida (de las 2 planteadas): tabla `personas`
-- (identidad) + tabla `cargos` (relación persona<->empresa, con
-- evidencia) -- mismo patrón que `observaciones`, porque el objetivo del
-- proyecto (doc 01 §1) es generar leads sobre "empresas Y EMPRESARIOS
-- encontrados", no solo sobre la empresa.
--
-- Deduplicación de personas: por `nombre_norm` exacto, sin NIF -- el
-- BORME casi nunca da NIF de personas físicas en los actos de
-- constitución/nombramiento. Limitación conocida y deliberada: dos
-- personas reales con el mismo nombre normalizado (p. ej. dos "GARCIA
-- LOPEZ JUAN" distintos) se tratan como la misma fila -- no hay
-- resolución de entidades para personas todavía (radar.resolucion solo
-- cubre empresas, doc 05). No es inventar datos, es no separar lo que no
-- se puede separar sin más señal -- a revisar con blocking geográfico o
-- cuando el volumen lo justifique.

create table if not exists personas (
  id             uuid primary key default gen_random_uuid(),
  nombre         text not null,           -- tal como lo declara la fuente
  nombre_norm    text not null,           -- normalizar_texto(nombre) -- clave de "blocking" sin NIF
  nif            text,                    -- casilla para cuando otra fuente sí lo traiga (aviso legal, proveedor comercial)
  nif_valido     boolean,
  creado_en      timestamptz not null default now(),
  actualizado_en timestamptz not null default now()
);

create index if not exists ix_personas_nombre_norm on personas (nombre_norm);
-- parcial: nif es null en casi todas las filas hoy, no tiene sentido un
-- índice único que solo se activa cuando SÍ hay nif (mismo patrón que
-- empresas.nif, doc 03b, pero permitiendo null a diferencia de esa).
create unique index if not exists ux_personas_nif on personas (nif) where nif is not null;

comment on table personas is
  'Personas físicas con cargo en una empresa (administradores, consejeros,
  presidentes -- doc 08). Lead objetivo por sí mismas, no solo metadato de
  la empresa (doc 01 §1).';

create table if not exists cargos (
  id                bigserial primary key,
  persona_id        uuid not null references personas(id) on delete cascade,
  empresa_id        uuid not null references empresas(id) on delete cascade,
  -- 'administrador_unico' | 'administrador_solidario' | 'administrador_mancomunado'
  -- | 'consejero_delegado' | 'consejero' | 'presidente' -- ver
  -- radar.fuentes.borme.PATRONES_CARGO. Texto libre, no enum: quedan
  -- pendientes más fuentes (aviso legal web, proveedor comercial) que
  -- declararán cargos con otro vocabulario y no queremos una migración
  -- por cada uno nuevo.
  cargo             text not null,
  fuente_id         smallint not null references fuentes(id),
  registro_bruto_id uuid references registros_brutos(id) on delete set null,
  url_evidencia     text,
  observado_en      timestamptz not null default now(),
  -- Siempre true por ahora: no hay detección de "cese" (haría falta un
  -- acto BORME posterior que lo declare y una función que lo cruce) --
  -- limitación conocida, igual que la vigencia de sedes.
  vigente           boolean not null default true,
  -- Sin esto, reprocesar el mismo acto (aunque insertar_registro_bruto ya
  -- debería evitarlo por hash_contenido) duplicaría la fila -- mismo
  -- criterio defensivo que identificadores.
  unique (persona_id, empresa_id, cargo)
);

create index if not exists ix_cargos_empresa on cargos (empresa_id);
create index if not exists ix_cargos_persona on cargos (persona_id);

comment on table cargos is
  'Relación persona<->empresa con evidencia (doc 08) -- mismo patrón que
  observaciones: nunca se sobreescribe, solo se añade. Un cambio de cargo
  en la misma empresa (p. ej. de administrador_unico a consejero) añade
  una fila nueva, no sustituye la anterior.';

do $$
declare t text;
begin
  foreach t in array array['personas', 'cargos']
  loop
    execute format('alter table %I enable row level security', t);
  end loop;

  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    foreach t in array array['personas', 'cargos']
    loop
      execute format('drop policy if exists lectura_autenticados on %I', t);
      execute format('create policy lectura_autenticados on %I for select to authenticated using (true)', t);
    end loop;
  end if;
end $$;
