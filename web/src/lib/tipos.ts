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
