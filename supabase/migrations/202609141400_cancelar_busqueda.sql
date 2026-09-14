-- 202609141400_cancelar_busqueda.sql
--
-- doc 03b ya anticipaba 'cancelada' como valor de ejemplo de
-- busquedas.estado, pero nada lo implementaba (radar.api.estado.EstadoBusqueda
-- no lo incluía, y no había ningún endpoint para pedirlo).
--
-- La búsqueda corre en el mismo proceso del worker vía BackgroundTasks
-- (doc 08 D-16: sin cola de verdad) — no hay un "job" externo al que
-- mandarle una señal de cancelación. La única forma de parar un bucle que
-- ya está corriendo es cooperativa: el propio bucle del planificador
-- comprueba esta columna ENTRE rondas (radar.agente.planificador,
-- parámetro `debe_cancelar`) y para si la encuentra a true. No puede
-- interrumpir una llamada al LLM o a una herramienta ya en curso a media
-- ronda -- el efecto práctico es "para en la primera ronda que pueda
-- después de pedirlo", no instantáneo.

alter table busquedas add column if not exists cancelar_solicitado boolean not null default false;

comment on column busquedas.cancelar_solicitado is
  'Puesto a true por POST /busquedas/{id}/cancelar (radar.api.main). El '
  'planificador lo comprueba entre rondas -- no puede interrumpir una '
  'llamada ya en curso -- y termina con motivo_fin = ''cancelada_por_usuario'', '
  'que radar.api.estado.estado_final_de traduce a estado = ''cancelada''.';
