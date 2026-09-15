-- 202609150001_dirce_cobertura.sql
--
-- Segunda pieza del plan de conexión de fuentes pendientes (2026-09-14):
-- INE DIRCE, para poder responder "¿cuánto nos falta?" -- hoy no hay
-- ninguna forma honesta de decir si una búsqueda está casi completa o
-- apenas ha empezado.
--
-- Verificado en vivo contra la API del INE (servicios.ine.es/wstempus)
-- antes de escribir esta migración: NO existe ninguna tabla oficial del
-- DIRCE que cruce provincia + CNAE + "Empresas" a la vez -- esa
-- combinación solo existe para "Locales" (establecimientos físicos, no
-- empresas: una empresa con dos sedes cuenta como dos locales, así que
-- usarlo como si fuera "número de empresas" sería una sobreestimación
-- silenciosa). La combinación con la unidad correcta ("Empresas") es
-- CCAA + actividad principal (CNAE-2009, división/grupo) + estrato de
-- asalariados (tabla 39372 del INE) -- más gruesa que provincia, pero
-- con la unidad de medida honesta. Preferible admitir menos precisión
-- geográfica que fingir una que no se tiene (principio 5).
--
-- codigo_cnae/version_cnae con FK compuesta a `cnae` -- verificado que
-- los 333 códigos que aparecen en la tabla 39372 (a nivel de división y
-- grupo) existen todos en el catálogo CNAE-2009 ya cargado
-- (migración 202609140001), cero huérfanos.

create table if not exists dirce_cobertura (
  id                  bigserial primary key,
  ccaa                text not null,
  codigo_cnae         text not null,
  version_cnae        text not null default 'CNAE-2009',
  -- 'Total' | 'Sin asalariados' | 'De 1 a 2 asalariados' | ... -- tal como
  -- el INE nombra cada tramo; para la estimación de cobertura se usa
  -- 'Total' (el único que no hay que sumar a mano combinando tramos).
  estrato_asalariados text not null,
  anyo                integer not null,
  empresas            integer not null,
  creado_en           timestamptz not null default now(),
  foreign key (codigo_cnae, version_cnae) references cnae(codigo, version),
  unique (ccaa, codigo_cnae, version_cnae, estrato_asalariados, anyo)
);

create index if not exists ix_dirce_ccaa_cnae on dirce_cobertura (ccaa, codigo_cnae, version_cnae)
  where estrato_asalariados = 'Total';

comment on table dirce_cobertura is
  'Número de empresas por CCAA + actividad (CNAE) + estrato de
  asalariados, según el INE (Directorio Central de Empresas, DIRCE) --
  para estimar cobertura ("hemos encontrado X de una base estimada de
  ~Y"), no para descubrir empresas nuevas. Se refresca una vez al año
  cuando el INE publica los nuevos datos (worker/scripts/generar_dirce.py
  + cargar_dirce.py), no en cada búsqueda.';

alter table dirce_cobertura enable row level security;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    drop policy if exists lectura_autenticados on dirce_cobertura;
    create policy lectura_autenticados on dirce_cobertura for select to authenticated using (true);
  end if;
end $$;
