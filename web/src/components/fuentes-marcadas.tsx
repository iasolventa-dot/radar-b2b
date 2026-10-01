import { CheckCircle2, CircleDashed, Coins, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { RondaEstadistica } from "@/lib/tipos";

// Qué ha pasado con cada fuente de pago marcada en esta búsqueda: si se usó,
// si falló o por qué no encontró nada. Antes una fuente marcada que no llegaba
// a ejecutarse (p. ej. Facebook sin páginas que leer) simplemente no aparecía.

const FUENTES: { clave: string; nombre: string; herramienta: string }[] = [
  { clave: "places", nombre: "Google Places", herramienta: "descubrir_places" },
  { clave: "google_maps", nombre: "Google Maps", herramienta: "descubrir_apify_maps" },
  { clave: "google_search", nombre: "Búsqueda en Google", herramienta: "descubrir_google_search" },
  { clave: "linkedin", nombre: "LinkedIn", herramienta: "enriquecer_con_linkedin" },
  { clave: "facebook", nombre: "Facebook", herramienta: "enriquecer_con_facebook" },
  { clave: "web_crawler", nombre: "Rastreo de webs", herramienta: "enriquecer_con_apify" },
];

export interface OpcionesBusqueda {
  apify_actores?: string[];
  usar_google_places?: boolean;
}

type Estado = { tono: "ok" | "error" | "vacio" | "pendiente" | "no_usada"; texto: string };

function estadoFuente(rondas: RondaEstadistica[], herramienta: string, activa: boolean): Estado {
  const suyas = rondas.filter((r) => r.herramienta === herramienta);
  if (suyas.length === 0) {
    return activa ? { tono: "pendiente", texto: "pendiente" } : { tono: "no_usada", texto: "no se usó" };
  }
  const r = suyas[suyas.length - 1].resultado as Record<string, unknown>;
  if (typeof r.error === "string" && r.error) return { tono: "error", texto: r.error };
  if (typeof r.motivo_parada === "string") return { tono: "vacio", texto: r.motivo_parada.replaceAll("_", " ") };
  if (r.soportado === false && typeof r.motivo === "string") return { tono: "error", texto: r.motivo };
  const n = (k: string) => suyas.reduce((s, x) => s + Number((x.resultado as Record<string, unknown>)[k] ?? 0), 0);
  const nuevas = n("nueva_empresa");
  const vinculadas = n("vinculado");
  const coste = n("coste_eur");
  const partes = [];
  if (nuevas) partes.push(`${nuevas} nuevas`);
  if (vinculadas) partes.push(`${vinculadas} completadas`);
  if (!nuevas && !vinculadas) partes.push("sin resultados");
  partes.push(`${coste.toFixed(3)} €`);
  return { tono: nuevas || vinculadas ? "ok" : "vacio", texto: partes.join(" · ") };
}

const ESTILO: Record<Estado["tono"], string> = {
  ok: "border-emerald-200 bg-emerald-50/60",
  error: "border-rose-200 bg-rose-50/60",
  vacio: "border-amber-200 bg-amber-50/50",
  pendiente: "border-brand-200 bg-brand-50/50",
  no_usada: "border-slate-200 bg-slate-50",
};

function Icono({ tono }: { tono: Estado["tono"] }) {
  if (tono === "ok") return <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />;
  if (tono === "error") return <XCircle className="h-5 w-5 shrink-0 text-rose-600" />;
  if (tono === "vacio") return <MinusCircle className="h-5 w-5 shrink-0 text-amber-600" />;
  if (tono === "pendiente") return <Loader2 className="h-5 w-5 shrink-0 animate-spin text-brand-600" />;
  return <CircleDashed className="h-5 w-5 shrink-0 text-slate-400" />;
}

export function FuentesMarcadas({
  opciones,
  rondas,
  activa,
}: {
  opciones: OpcionesBusqueda | null | undefined;
  rondas: RondaEstadistica[];
  activa: boolean;
}) {
  const marcadas = new Set([...(opciones?.apify_actores ?? []), ...(opciones?.usar_google_places ? ["places"] : [])]);
  const fuentes = FUENTES.filter((f) => marcadas.has(f.clave));
  if (fuentes.length === 0) return null;
  return (
    <section className="card p-6">
      <h2 className="titulo-seccion mb-4">
        <span className="icono-seccion">
          <Coins className="h-4 w-4" />
        </span>
        Fuentes de pago marcadas
      </h2>
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {fuentes.map((f) => {
          const estado = estadoFuente(rondas, f.herramienta, activa);
          return (
            <li key={f.clave} className={`flex items-start gap-3 rounded-xl border p-3.5 ${ESTILO[estado.tono]}`}>
              <Icono tono={estado.tono} />
              <div className="min-w-0">
                <p className="font-semibold text-slate-900">{f.nombre}</p>
                <p className="text-sm leading-snug text-slate-600">{estado.texto}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
