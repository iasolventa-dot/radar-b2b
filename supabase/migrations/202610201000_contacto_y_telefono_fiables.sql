-- Contacto principal y teléfono fiables en los resultados (2026-10-20, búsqueda
-- «reformas hoteleras y diseño de restaurantes»):
--
-- 1. El contacto principal se elegía con un `case` que solo conocía los cargos
--    del BORME: cualquier cargo leído en una web («Contacto», «Arquitecta»,
--    «Directora de arte») valía 0 y pasaba DELANTE del administrador o del
--    gerente. Ahora `prioridad_cargo()` ordena por relevancia comercial.
-- 2. Cargos mal leídos de fichas de equipo (el nombre guardado incluía otros
--    cargos en varias líneas: «Arquitecto\n Pol Puig\n Arquitecto»): se marcan
--    como no vigentes (no se borran: trazabilidad) y no se muestran.
-- 3. Teléfonos: primero los españoles; nunca uno que aparece en empresas de 3
--    o más webs distintas (901 100 099 estaba en 5 empresas sin relación), y
--    detrás los compartidos con otra web.

create or replace function prioridad_cargo(p_cargo text)
returns integer
language sql
immutable
set search_path = public
as $$
  select case
    when p_cargo = 'presidente' then 1
    when p_cargo = 'consejero_delegado' then 2
    when p_cargo = 'administrador_unico' then 3
    when p_cargo in ('administrador_solidario', 'administrador_mancomunado') then 4
    -- Cargos de dirección leídos en la web (mismo criterio que el exportador
    -- a Solventa DB: radar/exportacion/solventa.py::cargo_solventa).
    when c ~ '(director(a)? (general|gerente|ejecutiv)|direccion general|\mceo\M|managing director|gerent|gerencia|propietari|titular|fundador|administrador|representante legal)' then 4
    when p_cargo = 'consejero' then 5
    when c ~ '(\msoci[oa]\M|director|directora|direccion|responsable|jef[ea]|encargad|manager)' then 6
    when c ~ '^(contacto|persona de contacto)$' or c = '' then 8
    else 7
  end
  from (select translate(lower(coalesce(p_cargo, '')), 'áéíóúñü', 'aeiounu') as c) x
$$;

-- Webs distintas en las que aparece un teléfono (1 = solo la suya).
create or replace function webs_con_telefono(p_valor_norm text)
returns integer
language sql
stable
set search_path = public
as $$
  select count(distinct coalesce(e.dominio_web, e.id::text))::int
  from canales_contacto c join empresas e on e.id = c.empresa_id
  where c.tipo = 'telefono' and c.valor_norm = p_valor_norm and e.fusionada_en is null
$$;

update cargos set vigente = false
where vigente is not false
  and persona_id in (select id from personas where nombre ~ E'\n');

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
      (select t.valor from (
         select c.valor, c.confianza, webs_con_telefono(c.valor_norm) as webs
         from canales_contacto c
         where c.empresa_id = e.id and c.tipo = 'telefono' and c.estado is distinct from 'invalido'
       ) t
       where t.webs < 3
       order by (t.valor like '+34%') desc, (t.webs = 1) desc, t.confianza desc nulls last
       limit 1) as telefono,
      (select c.valor from canales_contacto c
        where c.empresa_id = e.id and c.tipo = 'email' and c.estado is distinct from 'invalido'
        order by c.confianza desc nulls last limit 1) as email,
      cg.nombre as cargo_nombre, cg.cargo as cargo_cargo,
      (select count(*)::int from conflictos_datos x where x.empresa_id = e.id and x.estado = 'pendiente' and x.tipo = 'sin_contrastar') as sin_contrastar,
      (select count(*)::int from conflictos_datos x where x.empresa_id = e.id and x.estado = 'pendiente' and x.tipo <> 'sin_contrastar') as en_revision
    from busqueda_resultados br
    join empresas e on e.id = br.empresa_id
    left join lateral (
      select p.nombre, c.cargo
      from cargos c join personas p on p.id = c.persona_id
      where c.empresa_id = e.id and c.vigente is not false
      order by prioridad_cargo(c.cargo), c.observado_en desc nulls last
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

grant execute on function prioridad_cargo(text) to authenticated;
grant execute on function webs_con_telefono(text) to authenticated;
grant execute on function resultados_busqueda(uuid, integer, integer) to authenticated;
