-- La columna `relevancia` que intentó añadir 202609251000 YA existía en
-- `busqueda_resultados` (numeric: puntuación de coincidencia, esquema inicial),
-- así que aquel `add column if not exists` no hizo nada. La clasificación del
-- filtro de relevancia con IA va en una columna propia:
--   relevante | dudoso | descartado  -> decisión de la IA
--   aceptado | rechazado              -> decisión de una persona (gana siempre)
--   NULL                              -> sin evaluar
alter table busqueda_resultados add column if not exists clasificacion text
  check (clasificacion in ('relevante', 'dudoso', 'descartado', 'aceptado', 'rechazado'));
