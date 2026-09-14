-- 202609141800_rls_observaciones.sql
--
-- docs/03b_schema_inicial.sql activa RLS (`enable row level security`)
-- sobre TODAS las tablas de la lista de la migración inicial, incluidas
-- `observaciones`, `registros_brutos`, `candidatos_duplicado` y
-- `fusiones` -- pero el segundo bucle, el que CREA la política de
-- lectura para `authenticated`, no incluye esas cuatro. El resultado:
-- RLS activado + cero políticas = cero filas, siempre, para cualquier
-- usuario autenticado del panel -- sin ningún error visible, la consulta
-- simplemente vuelve vacía.
--
-- Esto llevaba así desde el primer commit (docs/03b), no es algo que
-- rompiera esta sesión: `observaciones` es justo la tabla de
-- trazabilidad por campo (principio 2 del proyecto) que se ha ido
-- ampliando en esta sesión (de 1 campo a 10 por empresa) -- pero el
-- panel nunca ha podido leer ni una fila de ella, así que ese trabajo
-- era invisible desde el navegador aunque estuviera perfectamente
-- guardado en la base de datos.

do $$
declare t text;
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    foreach t in array array['observaciones', 'registros_brutos', 'candidatos_duplicado', 'fusiones']
    loop
      execute format('drop policy if exists lectura_autenticados on %I', t);
      execute format('create policy lectura_autenticados on %I for select to authenticated using (true)', t);
    end loop;
  end if;
end $$;
