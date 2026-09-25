import Link from "next/link";
import { ArrowRight, CheckCircle2, Euro, History, Loader2, Search } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { BusquedaFila } from "@/lib/tipos";
import { EstadoBusqueda } from "@/components/estado-busqueda";
import { EncabezadoPagina, EstadoVacio, TarjetaCifra } from "@/components/encabezado-pagina";

// Lectura directa contra Supabase (RLS, `busquedas` tiene política de
// lectura para `authenticated`) — igual que el resto del panel, así el
// histórico se ve aunque el worker local esté parado. Solo crear/
// confirmar una búsqueda pasa por `radar.api` (lib/api.ts).
export const dynamic = "force-dynamic";

const POR_PAGINA = 30;

export default async function PaginaBusquedas() {
  const supabase = await crearClienteServidor();
  const { data: busquedas, count } = await supabase
    .from("busquedas")
    .select("id, peticion, filtros, presupuesto_eur, estado, rondas, estadisticas, coste_eur, creado_en, finalizado_en", {
      count: "exact",
    })
    .order("creado_en", { ascending: false })
    .limit(POR_PAGINA);

  const filas = (busquedas ?? []) as unknown as BusquedaFila[];
  const gastoTotal = filas.reduce((suma, b) => suma + (b.coste_eur ?? 0), 0);
  const completadas = filas.filter((b) => b.estado === "completada").length;
  const enCurso = filas.filter((b) => b.estado === "en_curso").length;

  return (
    <div className="entrada space-y-8">
      <EncabezadoPagina
        icono={History}
        antetitulo="Historial"
        titulo="Búsquedas"
        acciones={
          <Link href="/" className="btn-primary">
            <Search className="h-4 w-4" /> Nueva búsqueda
          </Link>
        }
      >
        <p>Cada búsqueda lanzada, con su estado, coste y resultados.</p>
      </EncabezadoPagina>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <TarjetaCifra icono={History} etiqueta="Búsquedas lanzadas" valor={count ?? 0} tono="marca" />
        <TarjetaCifra
          icono={enCurso ? Loader2 : CheckCircle2}
          etiqueta={enCurso ? "En curso ahora" : "Completadas"}
          valor={enCurso || completadas}
          detalle={enCurso ? `${completadas} completadas` : undefined}
          tono="verde"
        />
        <TarjetaCifra
          icono={Euro}
          etiqueta="Gasto total"
          valor={`${gastoTotal.toFixed(2)} €`}
          detalle={filas.length < (count ?? 0) ? `últimas ${filas.length}` : undefined}
          tono="cian"
        />
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="tabla-panel">
            <thead>
              <tr>
                <th className="th-panel">Petición</th>
                <th className="th-panel">Estado</th>
                <th className="th-panel">Rondas</th>
                <th className="th-panel">Coste</th>
                <th className="th-panel">Lanzada</th>
                <th className="th-panel" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filas.map((b) => (
                <tr key={b.id} className="group">
                  <td className="td-panel max-w-md">
                    <Link
                      href={`/busquedas/${b.id}`}
                      className="block truncate text-base font-semibold text-slate-900 group-hover:text-brand-700"
                      title={b.peticion}
                    >
                      {b.peticion}
                    </Link>
                  </td>
                  <td className="td-panel">
                    <EstadoBusqueda estado={b.estado} />
                  </td>
                  <td className="td-panel tabular-nums text-slate-600">
                    {b.rondas} / {b.estadisticas?.max_rondas ?? "—"}
                  </td>
                  <td className="td-panel whitespace-nowrap tabular-nums">
                    <span className="font-semibold text-slate-800">{b.coste_eur.toFixed(2)} €</span>
                    {b.presupuesto_eur != null && (
                      <span className="text-slate-400"> / {Number(b.presupuesto_eur).toFixed(2)} €</span>
                    )}
                  </td>
                  <td className="td-panel whitespace-nowrap text-slate-500">
                    {new Date(b.creado_en).toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" })}
                  </td>
                  <td className="td-panel text-right">
                    <Link
                      href={`/busquedas/${b.id}`}
                      className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold text-brand-600 transition group-hover:bg-brand-50 hover:text-brand-700"
                    >
                      Ver <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                    </Link>
                  </td>
                </tr>
              ))}
              {filas.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <EstadoVacio icono={History}>Todavía no se ha lanzado ninguna búsqueda.</EstadoVacio>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
