// Exportación a CSV de los resultados de una búsqueda (doc 01, Fase 3:
// "no hay exportación CSV/Excel" quedaba listado como simplificación
// conocida frente al entregable de esa fase). Puramente cliente: los
// resultados ya están cargados en memoria (progreso-busqueda.tsx los
// trae para pintar la tabla), así que no hace falta ningún endpoint
// nuevo ni tocar el worker -- se serializa lo que ya se está mostrando.
//
// Deliberadamente una fila por empresa con el contacto "principal" (el
// mismo criterio que ya usa la tabla: el teléfono/email no marcado como
// inválido, el cargo de mayor prioridad) en vez de todos los teléfonos/
// cargos de cada empresa -- para importar en un CRM o repartir entre
// comerciales, una fila por lead es lo que de verdad se puede usar; el
// detalle completo (todos los teléfonos, todos los cargos, el historial
// con fuente) sigue disponible en /empresas/[id] para quien lo necesite.

interface FilaExportable {
  empresa_id: string;
  razon_social: string;
  nif: string | null;
  contacto: string | null;
  telefono: string | null;
  email: string | null;
  dominio_web: string | null;
  estado: string | null;
  confianza_global: number | null;
  motivo: string | null;
}

const CABECERA = [
  "Razón social", "NIF", "Contacto", "Teléfono", "Email", "Web", "Estado", "Confianza", "Fuente", "Ficha",
];

/** RFC 4180: solo hay que entrecomillar un campo si contiene coma, comilla
 * o salto de línea -- entrecomillar siempre también sería correcto, pero
 * así el CSV queda más legible abierto en un editor de texto plano. */
function celda(valor: string | number | null | undefined): string {
  const texto = valor == null ? "" : String(valor);
  if (/[",\n]/.test(texto)) {
    return `"${texto.replace(/"/g, '""')}"`;
  }
  return texto;
}

export function exportarResultadosCsv(filas: FilaExportable[], nombreBusqueda: string) {
  const origen =
    typeof window !== "undefined" ? window.location.origin : "";
  const lineas = [
    CABECERA.join(","),
    ...filas.map((f) =>
      [
        celda(f.razon_social),
        celda(f.nif),
        celda(f.contacto),
        celda(f.telefono),
        celda(f.email),
        celda(f.dominio_web),
        celda(f.estado),
        celda(f.confianza_global?.toFixed(2)),
        celda(f.motivo),
        celda(`${origen}/empresas/${f.empresa_id}`),
      ].join(",")
    ),
  ];
  // BOM UTF-8: sin esto, Excel en Windows (el uso previsto, doc 08) abre
  // los acentos mal -- "Construcción" sale como "ConstrucciÃ³n" -- porque
  // asume Windows-1252 si no hay marca de orden de bytes.
  const contenido = "\uFEFF" + lineas.join("\r\n");
  const blob = new Blob([contenido], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const enlace = document.createElement("a");
  const fecha = new Date().toISOString().slice(0, 10);
  const nombreLimpio = nombreBusqueda
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  enlace.href = url;
  enlace.download = `radar-b2b_${nombreLimpio || "busqueda"}_${fecha}.csv`;
  document.body.appendChild(enlace);
  enlace.click();
  document.body.removeChild(enlace);
  URL.revokeObjectURL(url);
}
