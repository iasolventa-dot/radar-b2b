-- Relevancia de cada resultado de búsqueda y resolución automática de dudas
-- (2026-09-25).

-- Cada empresa enlazada a una búsqueda se clasifica con IA al terminar
-- (radar/agente/relevancia.py): ¿es de verdad del sector y la zona pedidos?
--   relevante  -> se muestra
--   dudoso     -> se muestra marcado y va a la «Cola de revisión»
--   descartado -> NO se muestra en los resultados; queda en la «Cola de
--                 revisión» para poder recuperarla
--   aceptado / rechazado -> decisión de una persona (gana siempre)
-- NULL = todavía sin evaluar (resultados anteriores a este cambio).
-- (La columna de clasificación se añade en 202609251100: `relevancia` ya
-- existía como numeric y este add column no tenía efecto.)
alter table busqueda_resultados add column if not exists motivo_relevancia text;
alter table busqueda_resultados add column if not exists relevancia_revisada boolean not null default false;

-- Sugerencia de la IA (o de la verificación dirigida) para una duda que no se
-- pudo resolver sola: {"valor", "decision", "confianza", "motivo", "origen"}.
alter table conflictos_datos add column if not exists sugerencia jsonb;

-- Decisiones tomadas por el propio sistema (evidencia encontrada en la web de
-- la empresa o sugerencia de IA con confianza alta). Se distingue de 'manual'
-- (persona) por su código y grupo (el enum tipo_fuente no tiene un valor
-- propio): una persona siempre puede corregirla (0,98 > 0,90).
insert into fuentes (codigo, nombre, tipo, fiabilidad_base, permite_almacenar, campos_almacenables, grupo_independencia, notas_condiciones) values
  ('verificacion_automatica', 'Verificación automática (evidencia o IA)', 'manual', 0.90, true, '{}', 'verificacion_automatica',
   'Decisión del sistema al resolver una duda: valor encontrado en la web propia de la empresa o sugerido por IA con confianza alta. Revisable en la Cola de revisión.')
on conflict (codigo) do nothing;

-- El panel marca resultados como aceptados/rechazados directamente.
drop policy if exists actualizar_relevancia_autenticados on busqueda_resultados;
create policy actualizar_relevancia_autenticados on busqueda_resultados for update to authenticated using (true) with check (true);
