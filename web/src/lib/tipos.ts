// Tipos y constantes compartidas del panel de revisión del golden set.
// Reflejan las tablas de supabase/migrations/202609102000_golden_set_revision.sql
// y el desglose de worker/tests/golden/README.md §2.

export type EstadoRevision = "pendiente" | "promovido" | "descartado";

export type CasoDificil =
  | "homonimo"
  | "franquicia"
  | "grupo"
  | "disuelta"
  | "traslado"
  | "autonomo"
  | "web_agencia"
  | "nombre_generico";

export interface GoldenCandidato {
  id_fila: string;
  categoria_candidato: string;
  confianza_sector: string | null;
  fuente: string;
  id_externo: string | null;
  razon_social: string;
  municipio: string | null;
  codigo_postal: string | null;
  es_municipio_principal: boolean;
  hoja_registral: string | null;
  tipos_acto: string[];
  objeto_social: string | null;
  capital_eur: string | null;
  administradores: string[];
  posible_homonimo_de: string[];
  posible_grupo_con: string[];
  url_evidencia: string | null;
  fecha_publicacion: string | null;
  identificador_boletin: string | null;
  estado_revision: EstadoRevision;
  entidad_id_real: string | null;
  notas: string | null;
}

export interface GoldenEntidad {
  id_golden: string;
  nif: string | null;
  razon_social: string;
  nombre_comercial: string | null;
  forma_juridica: string | null;
  es_persona_fisica: boolean;
  cnae_principal: string | null;
  estado: string | null;
  municipio: string | null;
  municipio_ine: string | null;
  provincia: string | null;
  cp: string | null;
  direccion_domicilio_social: string | null;
  direccion_sede_operativa: string | null;
  telefono: string | null;
  telefono_verificado_llamada: "si" | "no" | "no_aplica";
  web: string | null;
  email_generico: string | null;
  caso_dificil: CasoDificil | null;
  fuente_verificacion: string | null;
  url_evidencia: string | null;
  fecha_verificacion: string | null;
  verificado_por: string | null;
  notas: string | null;
  candidato_origen_id: string | null;
}

// Objetivo del golden set (doc 07 §6 / worker/tests/golden/README.md §2).
// La clave "" representa los casos "normales" (caso_dificil vacío).
export const OBJETIVO_POR_CASO: Record<string, number> = {
  "": 140,
  homonimo: 10,
  franquicia: 10,
  grupo: 10,
  disuelta: 10,
  traslado: 10,
  autonomo: 5,
  web_agencia: 3,
  nombre_generico: 2,
};

export const ETIQUETA_CASO: Record<string, string> = {
  "": "Normales",
  homonimo: "Homónimos",
  franquicia: "Franquicias",
  grupo: "Grupo empresarial",
  disuelta: "Disueltas",
  traslado: "Traslados",
  autonomo: "Autónomos",
  web_agencia: "Web con aviso legal de agencia",
  nombre_generico: "Nombre genérico",
};

export const ETIQUETA_CATEGORIA_CANDIDATO: Record<string, string> = {
  pool_normal_construccion: "Normal (construcción)",
  candidato_grupo: "Grupo empresarial",
  candidato_homonimo: "Homónimo",
  candidato_disuelta: "Disuelta",
  candidato_traslado: "Traslado",
  revisar_objeto_generico: "Objeto social genérico (revisar)",
};

// ---------------------------------------------------------------------
// Agente de búsqueda (tarea #23) — reflejan worker/radar/agente/interpretacion.py
// (FiltrosBusqueda y anidados) y worker/radar/api/esquemas.py. Si cambia el
// esquema Python, cambiar esto a la vez (no hay generación automática todavía).
// ---------------------------------------------------------------------

export type EstadoEmpresa =
  | "activa"
  | "probablemente_activa"
  | "dudosa"
  | "inactiva"
  | "en_liquidacion"
  | "en_concurso"
  | "disuelta"
  | "extinguida"
  | "desconocida";

export interface UbicacionFiltro {
  tipo: "provincias" | "municipios" | "ccaa";
  provincias: string[];
  municipios: string[];
  ccaa: string[];
}

export interface SectorFiltro {
  sector_interno: string;
  codigos_cnae: string[];
  palabras_clave: string[];
  exclusiones: string[];
}

export interface TamanoFiltro {
  empleados_min: number | null;
  empleados_max: number | null;
}

export interface RequisitosFiltro {
  web: boolean;
  telefono: boolean;
  email_generico: boolean;
}

export interface CalidadFiltro {
  confianza_minima: number;
  frescura_max_dias: number;
}

export interface FiltrosBusqueda {
  ubicacion: UbicacionFiltro;
  sector: SectorFiltro;
  tamano: TamanoFiltro;
  formas_juridicas: string[];
  incluir_autonomos: boolean;
  estados: EstadoEmpresa[];
  requisitos: RequisitosFiltro;
  calidad: CalidadFiltro;
  limite_resultados: number | null;
  presupuesto_eur: number | null;
  supuestos: string[];
  preguntas: string[];
}

// worker/radar/api/estado.py::EstadoBusqueda
export type EstadoBusqueda = "interpretada" | "en_curso" | "completada" | "esperando_respuesta" | "error";

export interface RondaEstadistica {
  numero: number;
  herramienta: string;
  argumentos: Record<string, unknown>;
  resultado: Record<string, unknown>;
}

export interface EstadisticasBusqueda {
  max_rondas: number;
  rondas: RondaEstadistica[];
  motivo_fin?: string;
  resumen?: string;
  pregunta?: { pregunta: string; opciones: string[] } | null;
  error?: string | null;
}

// worker/radar/api/esquemas.py::BusquedaInterpretadaOut
export interface BusquedaInterpretadaOut {
  id: string;
  filtros: FiltrosBusqueda;
  supuestos: string[];
  preguntas: string[];
}

// worker/radar/api/esquemas.py::ConfirmarBusquedaOut
export interface ConfirmarBusquedaOut {
  id: string;
  estado: EstadoBusqueda;
}

// worker/radar/api/esquemas.py::ProfundizarOut -- resultado de "búsqueda en
// profundidad" de una empresa concreta (worker/radar/agente/profundizar.py).
export interface ProfundizarOut {
  empresa_id: string;
  consultas: string[];
  resultado: Record<string, unknown>;
  error?: string | null;
}

// Fila de la tabla `busquedas` (doc 03b) tal como la lee el panel, ya sea
// del worker (GET /busquedas) o directamente de Supabase (RLS, igual que el
// resto del panel) — misma forma en ambos casos salvo `filtros`/`estadisticas`,
// que Supabase devuelve ya como objeto (jsonb) y no hace falta parsear.
export interface BusquedaFila {
  id: string;
  peticion: string;
  filtros: FiltrosBusqueda;
  presupuesto_eur: number | null;
  estado: string;
  rondas: number;
  estadisticas: EstadisticasBusqueda;
  coste_eur: number;
  creado_en: string;
  finalizado_en: string | null;
}

export const ETIQUETA_ESTADO_BUSQUEDA: Record<string, string> = {
  interpretada: "Esperando confirmación",
  en_curso: "En curso",
  esperando_respuesta: "Esperando respuesta",
  completada: "Completada",
  error: "Error",
  pendiente: "Pendiente",
  cancelada: "Cancelada",
};

export const COLOR_ESTADO_BUSQUEDA: Record<string, string> = {
  interpretada: "bg-slate-100 text-slate-700",
  en_curso: "bg-brand-50 text-brand-700",
  esperando_respuesta: "bg-amber-50 text-amber-700",
  completada: "bg-emerald-50 text-emerald-700",
  error: "bg-rose-50 text-rose-700",
  pendiente: "bg-slate-100 text-slate-700",
  cancelada: "bg-slate-100 text-slate-500",
};

export const ETIQUETA_HERRAMIENTA: Record<string, string> = {
  consultar_bd: "Consultar base de datos",
  estimar_cobertura: "Estimar cobertura (INE)",
  descubrir_borme: "Descubrir en el BORME",
  buscar_web: "Buscar en la web",
  descubrir_osm: "Descubrir en OpenStreetMap",
  descubrir_places: "Descubrir en Google Places",
  descubrir_apify_maps: "Descubrir en Google Maps (Apify)",
  descubrir_google_search: "Buscar en Google (Apify)",
  enriquecer_con_apify: "Rastrear webs (Apify)",
  enriquecer_con_linkedin: "Enriquecer con LinkedIn (Apify)",
  enriquecer_con_facebook: "Enriquecer con Facebook (Apify)",
  completar_contacto: "Completar contacto (web, teléfono, email)",
  enriquecer_borme: "Identidad y directivos desde el BORME",
  evaluar_relevancia: "Filtrar resultados que no son del sector (IA)",
  resolver_dudas: "Resolver datos sin contrastar",
  preguntar_usuario: "Pregunta al usuario",
  finalizar_busqueda: "Finalizar búsqueda",
  // No es una herramienta real (el LLM nunca la "llama") -- la genera el
  // propio planificador para dejar constancia del coste de tokens de cada
  // turno (radar.agente.planificador.PLANIFICADOR_LLM, 2026-09-21).
  planificador_llm: "Coste del planificador (LLM)",
};

// `busqueda_resultados.motivo` (doc 03b) lo escribe
// `radar.orquestador.bd.registrar_resultado_busqueda` como "<fuente>: <acción>"
// (p. ej. "borme: nueva_empresa") — combina de dónde salió el dato con qué se
// hizo con él. Esto es lo que el panel muestra como "fuente" de cada
// resultado; para el detalle campo a campo con URL de evidencia hay que ir
// a `observaciones` (todavía sin pantalla propia).
const ETIQUETA_FUENTE_MOTIVO: Record<string, string> = {
  borme: "BORME",
  buscador_web: "Búsqueda web",
  osm: "OpenStreetMap",
  "google_places+web": "Google Places + web propia",
  google_places: "Google Places",
  apify_maps: "Google Maps (Apify)",
  "apify_maps+web": "Google Maps + web propia",
  apify_google_search: "Google (Apify)",
  facebook: "Facebook",
  linkedin: "LinkedIn",
  "apify+web": "Web (rastreo Apify)",
  contacto_web: "Web propia (contacto)",
  contacto_maps: "Google Maps (contacto)",
  "contacto_maps+web": "Google Maps + web (contacto)",
};

const ETIQUETA_ACCION_MOTIVO: Record<string, string> = {
  nueva_empresa: "nueva",
  vinculado: "vinculada a una empresa existente",
  en_revision: "unida con dudas (sin contrastar)",
  // Faltaba: AccionFinal (radar.orquestador.procesar) tiene 4 valores, no 3
  // -- "ya_procesado" es real en producción (esta misma búsqueda ya había
  // encontrado la empresa antes, p. ej. un acto BORME que la vuelve a
  // mencionar), no un caso de borde teórico.
  ya_procesado: "ya encontrada antes en esta búsqueda",
};

export function etiquetaFuenteResultado(motivo: string | null): string {
  if (!motivo) return "—";
  const [fuente, accion] = motivo.split(": ");
  const etiquetaFuente = ETIQUETA_FUENTE_MOTIVO[fuente] ?? fuente;
  const etiquetaAccion = accion ? ETIQUETA_ACCION_MOTIVO[accion] ?? accion : null;
  return etiquetaAccion ? `${etiquetaFuente} — ${etiquetaAccion}` : etiquetaFuente;
}

// personas/cargos (migración 202609141600) -- radar.fuentes.borme.PATRONES_CARGO
// es la fuente de verdad de qué valores de `cargo` existen; esto solo es
// la traducción a español legible para el panel.
export const ETIQUETA_CARGO: Record<string, string> = {
  administrador_unico: "Administrador único",
  administrador_solidario: "Administrador solidario",
  administrador_mancomunado: "Administrador mancomunado",
  consejero_delegado: "Consejero delegado",
  consejero: "Consejero",
  presidente: "Presidente",
};

// Para elegir qué cargo mostrar como "el" contacto principal cuando una
// persona tiene varios en la misma empresa (p. ej. presidente Y consejero
// delegado) -- orden de más a menos relevante para un lead comercial.
// No es un orden legal de precedencia, es una elección de qué enseñar
// primero en una tabla compacta.
export const PRIORIDAD_CARGO: string[] = [
  "presidente",
  "consejero_delegado",
  "administrador_unico",
  "administrador_solidario",
  "administrador_mancomunado",
  "consejero",
];

// worker/radar/api/esquemas.py::EstadoPlacesOut / ProbarPlacesOut (sección Ajustes)
export interface EstadoPlaces {
  configurada: boolean;
  clave_enmascarada: string | null;
  origen: "panel" | "env" | null;
  presupuesto_mensual_eur: number;
  gasto_mes_eur: number;
}

export interface ProbarPlacesOut {
  ok: boolean;
  mensaje: string;
}

// worker/radar/api/esquemas.py::EstadoApifyOut (sección Ajustes)
export interface EstadoApify {
  configurado: boolean;
  token_enmascarado: string | null;
  presupuesto_mensual_usd: number;
  gasto_mes_usd: number;
}

// worker/radar/api/esquemas.py::ConfirmarBusquedaIn.apify_actores -- un Actor
// de Apify por checkbox en "Nueva búsqueda" (radar/agente/herramientas.py::_HERRAMIENTAS_APIFY).
export type ApifyActor = "web_crawler" | "google_search" | "google_maps" | "linkedin" | "facebook";
