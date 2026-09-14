-- 202609142000_fusionar_empresas.sql
--
-- candidatos_duplicado y fusiones estaban en el esquema desde el primer
-- commit (docs/03b), con estado_revision ya pensado
-- ('pendiente'/'confirmado_duplicado'/'rechazado'/'aplazado') -- pero
-- nada los usaba: radar.resolucion detecta candidatos ambiguos y los
-- inserta en candidatos_duplicado (bd.insertar_candidato_duplicado), pero
-- ninguna pantalla los mostraba, y nada escribía nunca en `fusiones` ni
-- reasignaba nada. Un candidato aprobado como duplicado se quedaba
-- exactamente igual que antes de aprobarlo: dos filas de `empresas`
-- separadas para siempre.
--
-- fusionar_empresas() hace la fusión completa en una sola transacción:
-- la empresa "origen" desaparece de los resultados de búsqueda
-- (fusionada_en, que construir_where_empresas ya usa) pero conserva su
-- fila -- toda su evidencia (sedes, canales_contacto, identificadores,
-- cargos, observaciones, busqueda_resultados) se reasigna a la empresa
-- "destino", para que el historial completo quede bajo un solo id
-- canónico. Se hace como función de Postgres, no como varios pasos
-- sueltos desde el navegador (como sí hace revision/[id]/acciones.ts
-- para el golden set): aquí hace falta que las seis tablas se muevan
-- junto con estado_revision y fusiones en una sola transacción atómica,
-- y las comprobaciones "not exists" para no chocar con restricciones
-- unique (dos teléfonos iguales, la misma persona con el mismo cargo en
-- las dos empresas...) son mucho más simples en SQL que reconstruidas a
-- mano en TypeScript.
--
-- Donde el destino YA tenía una fila equivalente (mismo canal de
-- contacto, misma persona+cargo, el mismo hueco en la misma búsqueda),
-- la fila de origen se deja sin reasignar -- no hace falta moverla, ya
-- hay una evidencia equivalente en destino, y forzarla chocaría con la
-- restricción unique de esa tabla. Queda como evidencia "huérfana" bajo
-- el id retirado, inalcanzable desde cualquier búsqueda futura (por el
-- filtro fusionada_en) pero recuperable si algún día hace falta deshacer.

-- security definer: la función necesita escribir en 8 tablas distintas
-- (empresas, sedes, canales_contacto, identificadores, cargos,
-- observaciones, busqueda_resultados, fusiones), y abrir una política de
-- escritura para `authenticated` en cada una solo para este caso sería
-- más superficie de permisos que la propia función -- que ya valida
-- ambos ids y solo hace exactamente esta reasignación, nada más. Con
-- `search_path` fijado explícitamente (recomendación estándar de
-- Postgres para funciones security definer, evita que alguien con
-- privilegios para crear objetos en otro esquema del `search_path`
-- pueda secuestrar una llamada a una función no cualificada).
create or replace function fusionar_empresas(
  p_origen uuid,
  p_destino uuid,
  p_motivo text,
  p_decidido_por text,
  p_puntuacion numeric default null,
  p_candidato_id bigint default null
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_instantanea jsonb;
begin
  if p_origen = p_destino then
    raise exception 'fusionar_empresas: origen y destino no pueden ser la misma empresa (%)', p_origen;
  end if;

  select to_jsonb(e) into v_instantanea from empresas e where e.id = p_origen;
  if v_instantanea is null then
    raise exception 'fusionar_empresas: no existe la empresa origen %', p_origen;
  end if;
  if not exists (select 1 from empresas where id = p_destino) then
    raise exception 'fusionar_empresas: no existe la empresa destino %', p_destino;
  end if;

  update sedes set empresa_id = p_destino where empresa_id = p_origen;
  update identificadores set empresa_id = p_destino where empresa_id = p_origen;
  update observaciones set empresa_id = p_destino where empresa_id = p_origen;

  update canales_contacto c set empresa_id = p_destino
   where c.empresa_id = p_origen
     and not exists (
       select 1 from canales_contacto d
        where d.empresa_id = p_destino and d.tipo = c.tipo and d.valor_norm = c.valor_norm
     );

  update cargos c set empresa_id = p_destino
   where c.empresa_id = p_origen
     and not exists (
       select 1 from cargos d
        where d.empresa_id = p_destino and d.persona_id = c.persona_id and d.cargo = c.cargo
     );

  update busqueda_resultados b set empresa_id = p_destino
   where b.empresa_id = p_origen
     and not exists (
       select 1 from busqueda_resultados d
        where d.empresa_id = p_destino and d.busqueda_id = b.busqueda_id
     );

  update empresas set fusionada_en = p_destino where id = p_origen;

  insert into fusiones (empresa_origen, empresa_destino, motivo, puntuacion, decidido_por, instantanea)
  values (p_origen, p_destino, p_motivo, p_puntuacion, p_decidido_por, v_instantanea);

  if p_candidato_id is not null then
    update candidatos_duplicado
       set estado = 'confirmado_duplicado', revisado_por = p_decidido_por, revisado_en = now()
     where id = p_candidato_id;
  end if;
end $$;

comment on function fusionar_empresas(uuid, uuid, text, text, numeric, bigint) is
  'Fusiona dos empresas duplicadas en una sola transacción: reasigna toda
  la evidencia de la empresa origen a la destino y marca fusionada_en en
  el origen (doc 08). Llamada desde el panel via supabase.rpc().';

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    grant execute on function fusionar_empresas(uuid, uuid, text, text, numeric, bigint) to authenticated;

    -- "Descartar" (no es duplicado, quedan como empresas distintas) es
    -- una única UPDATE sencilla en candidatos_duplicado -- no necesita
    -- una función security definer como la fusión, basta con una
    -- política de escritura para authenticated, mismo criterio que ya
    -- usa golden_candidatos (migración 202609102000). Sustituye a la de
    -- solo-lectura de la migración 202609141800 -- for all ya incluye
    -- select, tener las dos a la vez sería redundante.
    drop policy if exists lectura_autenticados on candidatos_duplicado;
    drop policy if exists autenticados_todo on candidatos_duplicado;
    create policy autenticados_todo on candidatos_duplicado
      for all to authenticated using (true) with check (true);
  end if;
end $$;
