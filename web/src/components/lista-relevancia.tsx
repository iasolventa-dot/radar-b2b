import Link from "next/link";
import { Check, CheckCircle2, Search, X } from "lucide-react";
import { EstadoVacio } from "@/components/encabezado-pagina";
import { crearClienteServidor } from "@/lib/supabase/server";
import { marcarRelevancia } from "@/lib/acciones-conflictos";

// Resultados de búsqueda que el filtro de relevancia con IA (radar/agente/relevancia.py)
// marcó como dudosos o descartó por no ser del sector/zona pedidos. Una
// persona confirma («No lo es») o recupera («Sí es del sector») cada uno.

interface Fila {
  busqueda_id: string;
  empresa_id: string;
  clasificacion: string;
  motivo_relevancia: string | null;
  motivo: string | null;
}

export async function ListaRelevancia() {
  const supabase = await crearClienteServidor();
  const { data } = await supabase
    .from("busqueda_resultados")
    .select("busqueda_id, empresa_id, clasificacion, motivo_relevancia, motivo")
    .in("clasificacion", ["dudoso", "descartado"])
    .eq("relevancia_revisada", false)
    .limit(300);
  const filas = (data ?? []) as Fila[];

  if (filas.length === 0) {
    return (
      <div className="card">
        <EstadoVacio icono={CheckCircle2}>No hay resultados dudosos ni descartados pendientes de revisar.</EstadoVacio>
      </div>
    );
  }

  const idsEmpresa = Array.from(new Set(filas.map((f) => f.empresa_id)));
  const idsBusqueda = Array.from(new Set(filas.map((f) => f.busqueda_id)));
  const [{ data: empresas }, { data: busquedas }] = await Promise.all([
    supabase.from("empresas").select("id, razon_social, nombre_comercial, dominio_web").in("id", idsEmpresa),
    supabase.from("busquedas").select("id, peticion, creado_en").in("id", idsBusqueda),
  ]);
  const empresaPorId = new Map((empresas ?? []).map((e) => [e.id, e]));
  const busquedasOrdenadas = (busquedas ?? []).sort((a, b) => b.creado_en.localeCompare(a.creado_en));

  return (
    <div className="space-y-5">
      {busquedasOrdenadas.map((b) => {
        const deEsta = filas
          .filter((f) => f.busqueda_id === b.id)
          .sort((x, y) => (x.clasificacion === y.clasificacion ? 0 : x.clasificacion === "dudoso" ? -1 : 1));
        return (
          <div key={b.id} className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-gradient-to-r from-slate-50 to-white px-6 py-4">
              <Link
                href={`/busquedas/${b.id}`}
                className="flex items-center gap-2 font-display text-base font-bold text-slate-900 hover:text-brand-700"
              >
                <Search className="h-4 w-4 text-brand-500" />
                {b.peticion}
              </Link>
              <span className="text-sm text-slate-400">{new Date(b.creado_en).toLocaleString("es-ES")}</span>
            </div>
            <ul className="divide-y divide-slate-100 px-2">
              {deEsta.map((f) => {
                const e = empresaPorId.get(f.empresa_id);
                return (
                  <li
                    key={f.empresa_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl px-4 py-3.5 transition hover:bg-slate-50"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`badge ${f.clasificacion === "dudoso" ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-700"}`}
                        >
                          <span className="punto" />
                          {f.clasificacion === "dudoso" ? "dudosa" : "descartada"}
                        </span>
                        <Link href={`/empresas/${f.empresa_id}`} className="font-semibold text-slate-900 hover:text-brand-700">
                          {e?.razon_social ?? e?.nombre_comercial ?? "(sin nombre)"}
                        </Link>
                        {e?.dominio_web && <span className="text-sm text-slate-400">{e.dominio_web}</span>}
                      </div>
                      {f.motivo_relevancia && <p className="mt-1 text-sm text-slate-600">{f.motivo_relevancia}</p>}
                    </div>
                    <div className="flex gap-2">
                      <FormularioRelevancia
                        busquedaId={f.busqueda_id}
                        empresaId={f.empresa_id}
                        decision="aceptado"
                        clase="btn-secondary hover:!border-emerald-300 hover:!bg-emerald-50 hover:!text-emerald-700"
                      >
                        <Check className="h-4 w-4" /> Sí es del sector
                      </FormularioRelevancia>
                      <FormularioRelevancia busquedaId={f.busqueda_id} empresaId={f.empresa_id} decision="rechazado" clase="btn-danger">
                        <X className="h-4 w-4" /> No lo es
                      </FormularioRelevancia>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function FormularioRelevancia({
  busquedaId,
  empresaId,
  decision,
  clase,
  children,
}: {
  busquedaId: string;
  empresaId: string;
  decision: "aceptado" | "rechazado";
  clase: string;
  children: React.ReactNode;
}) {
  return (
    <form action={marcarRelevancia}>
      <input type="hidden" name="busqueda_id" value={busquedaId} />
      <input type="hidden" name="empresa_id" value={empresaId} />
      <input type="hidden" name="decision" value={decision} />
      <button type="submit" className={clase}>
        {children}
      </button>
    </form>
  );
}
