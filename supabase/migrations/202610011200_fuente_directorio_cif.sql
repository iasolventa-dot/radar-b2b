-- Fuente para el CIF/razón social de una empresa localizados en el extracto
-- de un resultado de búsqueda (directorios tipo infocif/empresite/einforma) o
-- por el modelo con búsqueda web, cuando su web no lo publica (2026-10-01:
-- solo un 25-40 % de las empresas de cada búsqueda tenía CIF). El código
-- valida el dígito de control y que el nombre coincida antes de guardarlo; la
-- fiabilidad es moderada porque el directorio es un tercero.
insert into fuentes (codigo, nombre, tipo, fiabilidad_base, permite_almacenar, campos_almacenables, grupo_independencia, notas_condiciones) values
  ('directorio_cif', 'Directorio de empresas (CIF localizado por búsqueda)', 'directorio', 0.55, true, '{nif,razon_social}', 'directorios',
   'Solo NIF y razón social, tomados del título/extracto de un resultado de búsqueda o de la respuesta de un modelo con búsqueda web, con la URL como evidencia. Dígito de control y coincidencia de nombre verificados por código.')
on conflict (codigo) do nothing;
