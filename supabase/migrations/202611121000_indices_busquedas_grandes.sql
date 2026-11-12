-- Búsquedas con miles de empresas (2026-11-12): «empresas de Madrid con CP
-- 28108» llegó a 19.413 resultados y la búsqueda acabó con «canceling statement
-- due to statement timeout». El filtro de sector, la fase de redes y la de
-- plantilla consultan `registros_brutos` por empresa (categoría de Maps, título
-- de la web, enlaces a redes...) y la tabla no tenía índice por empresa: cada
-- consulta recorría las ~50.000 filas. Desde que no hay tope fijo de empresas
-- por búsqueda, estas consultas tienen que escalar.

create index if not exists ix_brutos_empresa on registros_brutos (empresa_id);
create index if not exists ix_busqueda_resultados_clasificacion on busqueda_resultados (busqueda_id, clasificacion);
create index if not exists ix_sedes_empresa on sedes (empresa_id);
create index if not exists ix_canales_empresa_tipo on canales_contacto (empresa_id, tipo);
