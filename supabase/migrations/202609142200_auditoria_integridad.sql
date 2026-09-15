-- 202609142200_auditoria_integridad.sql
--
-- Hallazgos de la auditoría completa del proyecto (doc 08).
--
-- 1. `fusiones.empresa_origen` es `not null` pero NO tiene clave ajena a
--    `empresas(id)`, mientras que `empresa_destino` sí la tiene. Es la
--    columna que apunta a la empresa retirada, y `fusiones.instantanea`
--    es el registro que permitiría deshacer una fusión -- sin la FK,
--    nada impide que quede apuntando a un id inexistente, justo en la
--    tabla cuyo propósito es poder revertir.
--
--    Es seguro añadirla ahora: `fusionar_empresas` (migración
--    202609142000) NUNCA borra la fila de origen, solo le pone
--    `fusionada_en`. Sin `on delete cascade` a propósito: si alguien
--    borrase una empresa que fue origen de una fusión, es mejor que el
--    borrado falle a que desaparezca en silencio el registro de que esa
--    fusión ocurrió.
--
--    La migración es idempotente y tolerante: si por lo que sea ya
--    hubiera filas huérfanas (no debería, pero esto se aplica sobre una
--    base con datos reales), avisa y no añade la restricción en vez de
--    fallar la migración entera.

do $$
declare n_huerfanas integer;
begin
  if exists (
    select 1 from pg_constraint
    where conrelid = 'fusiones'::regclass and contype = 'f'
      and pg_get_constraintdef(oid) like '%empresa_origen%'
  ) then
    raise notice 'fusiones.empresa_origen ya tiene clave ajena, nada que hacer';
    return;
  end if;

  select count(*) into n_huerfanas
  from fusiones f
  where not exists (select 1 from empresas e where e.id = f.empresa_origen);

  if n_huerfanas > 0 then
    raise warning 'fusiones tiene % fila(s) con empresa_origen inexistente: no se añade la FK. Revisar a mano.', n_huerfanas;
  else
    alter table fusiones
      add constraint fusiones_empresa_origen_fkey
      foreign key (empresa_origen) references empresas(id);
    raise notice 'añadida FK fusiones.empresa_origen -> empresas(id)';
  end if;
end $$;

-- 2. Índice para la pantalla /duplicados: la consulta filtra por
--    `estado = 'pendiente'` y ordena por `puntuacion desc`, y no había
--    ningún índice que la cubriera -- irrelevante con las pocas filas de
--    hoy, pero esta tabla crece con cada búsqueda que encuentra un
--    candidato ambiguo.
create index if not exists ix_candidatos_duplicado_pendientes
  on candidatos_duplicado (estado, puntuacion desc)
  where estado = 'pendiente';

-- 3. Índice para el historial de /empresas/[id]: se consulta
--    `where empresa_id = ? order by observado_en desc`. El índice
--    existente `ix_obs_empresa_campo (empresa_id, campo)` no cubre bien
--    ese orden, y `observaciones` es la tabla que más crece del sistema
--    (10 filas por empresa desde que se amplió la trazabilidad).
create index if not exists ix_obs_empresa_fecha
  on observaciones (empresa_id, observado_en desc);
