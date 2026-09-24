-- Datos contradictorios entre fuentes (2026-09-24). Sustituye, para los datos
-- nuevos, a `candidatos_duplicado`: en vez de crear una fila de empresa nueva
-- cuando hay dudas, el dato se une a la empresa más probable, se queda como
-- valor el más probable y la contradicción se registra aquí.
--
--   tipo = 'sin_contrastar'          -> pantalla «Datos sin contrastar»: no hay
--                                       evidencia suficiente para saber cuál es
--                                       el dato correcto; decide una persona.
--   tipo = 'resuelto_con_evidencia'  -> pantalla «Cola de revisión»: el sistema
--                                       lo resolvió solo con evidencia fuerte
--                                       (dato más reciente, varias fuentes contra
--                                       una...); ya está aplicado, solo se confirma
--                                       o se deshace.
--
-- campo = '_identidad' es la duda de si un registro es de ESTA empresa (unido
-- por coincidencia parcial); `registro_bruto_id` apunta a ese registro para
-- poder separarlo.
create table if not exists conflictos_datos (
  id                bigserial primary key,
  empresa_id        uuid not null references empresas(id) on delete cascade,
  campo             text not null,
  tipo              text not null check (tipo in ('sin_contrastar', 'resuelto_con_evidencia')),
  valor_elegido     text,
  alternativas      jsonb not null default '[]'::jsonb,
  motivo            text not null,
  registro_bruto_id uuid references registros_brutos(id) on delete set null,
  puntuacion        numeric(4,3),
  busqueda_id       uuid references busquedas(id) on delete set null,
  estado            text not null default 'pendiente'
                      check (estado in ('pendiente', 'confirmado', 'corregido', 'separado', 'resuelto_automaticamente')),
  valor_final       text,
  resuelto_por      text,
  resuelto_en       timestamptz,
  creado_en         timestamptz not null default now(),
  actualizado_en    timestamptz not null default now()
);

-- Una sola contradicción pendiente por empresa y campo (se actualiza al llegar
-- datos nuevos); las de identidad son una por registro unido.
create unique index if not exists conflictos_datos_pendiente_campo_idx
  on conflictos_datos (empresa_id, campo) where estado = 'pendiente' and campo <> '_identidad';
create unique index if not exists conflictos_datos_identidad_idx
  on conflictos_datos (empresa_id, registro_bruto_id) where campo = '_identidad';
create index if not exists conflictos_datos_cola_idx on conflictos_datos (tipo, estado, creado_en desc);

alter table conflictos_datos enable row level security;
drop policy if exists lectura_autenticados on conflictos_datos;
create policy lectura_autenticados on conflictos_datos for select to authenticated using (true);
