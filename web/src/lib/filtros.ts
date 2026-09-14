import type { FiltrosBusqueda } from "@/lib/tipos";

/** Resume `FiltrosBusqueda` en líneas legibles — solo lo que el agente
 * realmente fijó (nada de "sin restricción" repetido para cada campo
 * vacío, para no saturar la pantalla). Usado en la confirmación de una
 * búsqueda nueva y en su pantalla de progreso, para que ambas muestren
 * exactamente lo mismo. */
export function describirFiltros(f: FiltrosBusqueda): string[] {
  const lineas: string[] = [];

  const ubicaciones: string[] = [];
  if (f.ubicacion.provincias.length) {
    ubicaciones.push(`provincia${f.ubicacion.provincias.length > 1 ? "s" : ""} ${f.ubicacion.provincias.join(", ")}`);
  }
  if (f.ubicacion.municipios.length) {
    ubicaciones.push(`municipio${f.ubicacion.municipios.length > 1 ? "s" : ""} ${f.ubicacion.municipios.join(", ")}`);
  }
  if (f.ubicacion.ccaa.length) ubicaciones.push(`CCAA ${f.ubicacion.ccaa.join(", ")}`);
  lineas.push(`Zona: ${ubicaciones.length ? ubicaciones.join(" · ") : "sin restricción"}`);

  const sector: string[] = [];
  if (f.sector.sector_interno) sector.push(f.sector.sector_interno);
  if (f.sector.codigos_cnae.length) sector.push(`CNAE ${f.sector.codigos_cnae.join(", ")}`);
  if (f.sector.palabras_clave.length) sector.push(`palabras clave: ${f.sector.palabras_clave.join(", ")}`);
  lineas.push(`Sector: ${sector.length ? sector.join(" · ") : "sin restricción"}`);
  if (f.sector.exclusiones.length) lineas.push(`Excluye: ${f.sector.exclusiones.join(", ")}`);

  const tamano: string[] = [];
  if (f.tamano.empleados_min != null) tamano.push(`≥ ${f.tamano.empleados_min} empleados`);
  if (f.tamano.empleados_max != null) tamano.push(`≤ ${f.tamano.empleados_max} empleados`);
  if (tamano.length) {
    // Ninguna fuente conectada da el número de empleados todavía (ni
    // BORME ni la extracción web) -- empresas.empleados_min/max están
    // siempre a null para cualquier empresa real, así que este filtro no
    // descarta nada aunque se aplique en la consulta. Aviso siempre desde
    // aquí, no solo confiando en que el LLM lo declare en "supuestos".
    lineas.push(`Tamaño: ${tamano.join(" y ")} (⚠ sin efecto real: ninguna fuente da el nº de empleados todavía)`);
  }

  if (f.formas_juridicas.length) lineas.push(`Forma jurídica: ${f.formas_juridicas.join(", ")}`);
  lineas.push(`Autónomos: ${f.incluir_autonomos ? "incluidos" : "no incluidos"}`);
  lineas.push(`Estados de la empresa: ${f.estados.join(", ")}`);

  const requisitos: string[] = [];
  if (f.requisitos.web) requisitos.push("tiene web");
  if (f.requisitos.telefono) requisitos.push("tiene teléfono");
  if (f.requisitos.email_generico) requisitos.push("tiene email genérico (info@/contacto@...)");
  if (requisitos.length) lineas.push(`Solo empresas que: ${requisitos.join(", ")}`);

  lineas.push(
    `Calidad: confianza mínima ${f.calidad.confianza_minima} · dato confirmado en los últimos ${f.calidad.frescura_max_dias} días`
  );

  if (f.limite_resultados != null) lineas.push(`Límite de resultados: ${f.limite_resultados}`);

  return lineas;
}
