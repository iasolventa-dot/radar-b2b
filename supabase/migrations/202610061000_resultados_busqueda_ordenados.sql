-- Resultados de una búsqueda ordenados y paginados en la base de datos
-- (2026-10-06). El panel pedía `busqueda_resultados ... limit 200` SIN orden y
-- ordenaba en el navegador: con 1.740 resultados («construcción en toda
-- España») cada refresco traía otros 200 al azar, las empresas aparecían y
-- desaparecían y el total se quedaba en 183. Ahora el orden (completitud de la
-- lista ideal: contacto, nombre, CIF, teléfono y email; luego confianza) y los
-- totales se calculan aquí, sobre TODOS los resultados.

create or replace function resultados_busqueda(p_busqueda uuid, p_limite integer default 100, p_desplazamiento integer default 0)
returns table (
  empresa_id uuid,
  motivo text,
  clasificacion text,
  motivo_relevancia text,
  razon_social text,
  nombre_comercial text,
  nif text,
  estado text,
  confianza_global numeric,
  dominio_web text,
  es_persona_fisica boolean,
  telefono text,
  email text,
  contacto_nombre text,
  contacto_cargo text,
  sin_contrastar integer,
  en_revision integer,
  completitud integer
)
language sql
stable
security invoker
set search_path = public
as $$
  with base as (
    select
      br.empresa_id, br.motivo, br.clasificacion, br.motivo_relevancia,
      e.razon_social, e.nombre_comercial, e.nif, e.estado::text as estado, e.confianza_global::numeric as confianza_global,
      e.dominio_web, e.es_persona_fisica,
      (select c.valor from canales_contacto c
        where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado is distinct from 'invalido'
        order by c.confianza desc nulls last limit 1) as telefono,
      (select c.valor from canales_contacto c
        where c.empresa_id = e.id and c.tipo = 'email' and c.estado is distinct from 'invalido'
        order by c.confianza desc nulls last limit 1) as email,
      cg.nombre as cargo_nombre, cg.cargo as cargo_cargo,
      (select count(*)::int from conflictos_datos x where x.empresa_id = e.id and x.estado = 'pendiente' and x.tipo = 'sin_contrastar') as sin_contrastar,
      (select count(*)::int from conflictos_datos x where x.empresa_id = e.id and x.estado = 'pendiente' and x.tipo <> 'sin_contrastar') as en_revision
    from busqueda_resultados br
    join empresas e on e.id = br.empresa_id
    left join lateral (
      -- Cargo principal: primero los de la web (gerente, CEO...), luego por
      -- jerarquía registral (mismo criterio que PRIORIDAD_CARGO del panel).
      select p.nombre, c.cargo
      from cargos c join personas p on p.id = c.persona_id
      where c.empresa_id = e.id
      order by case c.cargo
        when 'presidente' then 1 when 'consejero_delegado' then 2 when 'administrador_unico' then 3
        when 'administrador_solidario' then 4 when 'administrador_mancomunado' then 5 when 'consejero' then 6
        else 0 end
      limit 1
    ) cg on true
    where br.busqueda_id = p_busqueda
      and e.fusionada_en is null
      and coalesce(br.clasificacion, '') not in ('descartado', 'rechazado')
  ),
  con_contacto as (
    select b.*,
      coalesce(b.cargo_nombre, case when b.es_persona_fisica then b.razon_social end) as contacto_nombre,
      case when b.cargo_nombre is not null then b.cargo_cargo
           when b.es_persona_fisica and b.razon_social is not null then 'titular_autonomo' end as contacto_cargo
    from base b
  )
  select
    empresa_id, motivo, clasificacion, motivo_relevancia, razon_social, nombre_comercial, nif, estado, confianza_global,
    dominio_web, es_persona_fisica, telefono, email, contacto_nombre, contacto_cargo, sin_contrastar, en_revision,
    ((contacto_nombre is not null)::int + (coalesce(razon_social, nombre_comercial) is not null)::int
      + (nif is not null)::int + (telefono is not null)::int + (email is not null)::int) as completitud
  from con_contacto
  order by completitud desc, confianza_global desc nulls last, empresa_id
  limit greatest(p_limite, 0) offset greatest(p_desplazamiento, 0)
$$;

create or replace function resumen_resultados_busqueda(p_busqueda uuid)
returns table (
  total integer, descartadas integer, completas integer, con_nif integer, con_contacto integer,
  con_telefono integer, con_email integer
)
language sql
stable
security invoker
set search_path = public
as $$
  select
    count(*)::int,
    (select count(*)::int from busqueda_resultados br join empresas e on e.id = br.empresa_id
      where br.busqueda_id = p_busqueda and e.fusionada_en is null and br.clasificacion in ('descartado', 'rechazado')),
    count(*) filter (where r.completitud = 5)::int,
    count(*) filter (where r.nif is not null)::int,
    count(*) filter (where r.contacto_nombre is not null)::int,
    count(*) filter (where r.telefono is not null)::int,
    count(*) filter (where r.email is not null)::int
  from resultados_busqueda(p_busqueda, 1000000, 0) r
$$;

grant execute on function resultados_busqueda(uuid, integer, integer) to authenticated;
grant execute on function resumen_resultados_busqueda(uuid) to authenticated;
