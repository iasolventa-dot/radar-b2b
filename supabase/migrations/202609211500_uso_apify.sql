-- Gasto real de Apify (usageTotalUsd que devuelve cada ejecución), para el tope
-- mensual del panel. El token vive en `configuracion_secretos` (ver migración
-- 202609211000: RLS sin políticas, solo lo lee el worker).
create table if not exists uso_apify (
  id         bigserial primary key,
  creado_en  timestamptz not null default now(),
  actor      text not null,
  run_id     text,
  estado     text,
  coste_usd  numeric(10,4) not null default 0,
  detalle    jsonb not null default '{}'::jsonb
);
create index if not exists uso_apify_creado_idx on uso_apify (creado_en);
alter table uso_apify enable row level security;
drop policy if exists lectura_autenticados on uso_apify;
create policy lectura_autenticados on uso_apify for select to authenticated using (true);
