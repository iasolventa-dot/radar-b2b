import { AlertTriangle, Ban, Bot, Building2, Copy, GitMerge, Sparkles } from "lucide-react";
import { EncabezadoPagina } from "@/components/encabezado-pagina";
import { ListaConflictos } from "@/components/lista-conflictos";
import { resolverAutomaticamente } from "@/lib/acciones-conflictos";
import { crearClienteServidor } from "@/lib/supabase/server";
import { confirmarFusion, descartarDuplicado } from "./acciones";

export const dynamic = "force-dynamic";

// candidatos_duplicado se rellena desde que existe radar.resolucion
// (tarea #21) -- radar.orquestador.procesar crea una empresa nueva Y deja
// aquí un candidato pendiente cuando no está seguro de si es la misma que
// una ya existente o una empresa distinta con nombre parecido. Hasta esta
// sesión, nada leía esta tabla ni resolvía nunca esos candidatos: se
// acumulaban para siempre y las dos empresas quedaban separadas en
// cualquier búsqueda, aunque fueran la misma en realidad.

interface EmpresaResumen {
  id: string;
  razon_social: string | null;
  nombre_comercial: string | null;
  nif: string | null;
  forma_juridica: string | null;
  objeto_social: string | null;
  estado: string | null;
  confianza_global: number | null;
}

export default async function PaginaDuplicados() {
  const supabase = await crearClienteServidor();

  const { data: candidatos, count } = await supabase
    .from("candidatos_duplicado")
    .select("id, empresa_a, empresa_b, puntuacion, senales, creado_en", { count: "exact" })
    .eq("estado", "pendiente")
    .order("puntuacion", { ascending: false })
    .limit(100);

  const idsEmpresas = Array.from(
    new Set((candidatos ?? []).flatMap((c) => [c.empresa_a, c.empresa_b]))
  );

  // Consulta plana aparte (no anidada en la de candidatos_duplicado): el
  // cliente de Supabase no tiene tipos generados y su inferencia de tipos
  // por plantillas de texto no soporta bien selects complejos -- mismo
  // motivo que ya obligó a separar consultas en progreso-busqueda.tsx y
  // en /empresas/[id].
  const { data: empresasFilas } = idsEmpresas.length
    ? await supabase
        .from("empresas")
        .select("id, razon_social, nombre_comercial, nif, forma_juridica, objeto_social, estado, confianza_global")
        .in("id", idsEmpresas)
    : { data: [] as EmpresaResumen[] };

  const empresaPorId = new Map((empresasFilas ?? []).map((e) => [e.id, e as EmpresaResumen]));

  return (
    <div className="entrada space-y-7">
      <EncabezadoPagina
        icono={Copy}
        antetitulo="Tu decisión"
        titulo="Datos sin contrastar"
        acciones={
          <form action={resolverAutomaticamente}>
            <button type="submit" className="btn-primary">
              <Sparkles className="h-4 w-4" /> Intentar resolver automáticamente
            </button>
          </form>
        }
      >
        <p>
          Fuentes que dan valores distintos para el mismo campo sin evidencia suficiente, o datos unidos a una
          empresa por una coincidencia parcial. En la ficha ya se muestra el valor más probable; aquí decides.
        </p>
      </EncabezadoPagina>

      <div className="aviso-ia">
        <Bot className="mt-0.5 h-5 w-5 shrink-0 text-violet-600" />
        <p>
          Al terminar cada búsqueda el sistema ya intenta resolverlos solo: busca el dato en la web de la empresa y,
          si no lo encuentra, pide una sugerencia a la IA. Lo que resuelve pasa a la <strong>Cola de revisión</strong>;
          aquí queda lo que no pudo decidir (con la sugerencia de la IA si la hay).
        </p>
      </div>

      <ListaConflictos tipo="sin_contrastar" vacio="No hay datos pendientes de contrastar." />

      {(candidatos ?? []).length > 0 && (
        <div className="pt-4">
          <h2 className="titulo-seccion">
            <span className="icono-seccion">
              <GitMerge className="h-4 w-4" />
            </span>
            Posibles duplicados anteriores
            <span className="badge bg-amber-50 text-amber-700">{count ?? 0}</span>
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            Parejas de empresas creadas antes del 24/09/2026, cuando una duda de identidad creaba una fila nueva.
          </p>
        </div>
      )}

      <div className="space-y-4">
        {(candidatos ?? []).map((c) => {
          const a = empresaPorId.get(c.empresa_a);
          const b = empresaPorId.get(c.empresa_b);
          if (!a || !b) return null;
          return (
            <div key={c.id} className="card-interactiva p-6">
              <div className="mb-3 flex items-center justify-between">
                <span className="badge bg-amber-50 text-amber-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  puntuación {c.puntuacion.toFixed(2)}
                </span>
                <span className="text-sm text-slate-400">{new Date(c.creado_en).toLocaleDateString("es-ES")}</span>
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <TarjetaEmpresa empresa={a} />
                <TarjetaEmpresa empresa={b} />
              </div>

              {c.senales && Object.keys(c.senales).length > 0 && (
                <p className="mt-3 text-sm text-slate-500">
                  Señales: {Object.entries(c.senales as Record<string, unknown>).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(" · ")}
                </p>
              )}

              <div className="mt-4 flex flex-wrap items-center gap-2">
                <form action={confirmarFusion}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <input type="hidden" name="origen" value={b.id} />
                  <input type="hidden" name="destino" value={a.id} />
                  <input type="hidden" name="puntuacion" value={c.puntuacion} />
                  <button type="submit" className="btn-primary">
                    <GitMerge className="h-4 w-4" />
                    Son la misma — conservar &quot;{a.razon_social ?? a.nombre_comercial}&quot;
                  </button>
                </form>
                <form action={confirmarFusion}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <input type="hidden" name="origen" value={a.id} />
                  <input type="hidden" name="destino" value={b.id} />
                  <input type="hidden" name="puntuacion" value={c.puntuacion} />
                  <button type="submit" className="btn-secondary">
                    <GitMerge className="h-4 w-4" />
                    Son la misma — conservar &quot;{b.razon_social ?? b.nombre_comercial}&quot;
                  </button>
                </form>
                <form action={descartarDuplicado}>
                  <input type="hidden" name="candidato_id" value={c.id} />
                  <button type="submit" className="btn-danger">
                    <Ban className="h-4 w-4" />
                    No son la misma empresa
                  </button>
                </form>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TarjetaEmpresa({ empresa }: { empresa: EmpresaResumen }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4">
      <p className="flex items-center gap-2 font-semibold text-slate-900">
        <Building2 className="h-4 w-4 shrink-0 text-brand-500" />{empresa.razon_social ?? empresa.nombre_comercial ?? "(sin nombre)"}</p>
      <p className="mt-1.5 text-sm text-slate-500">
        {empresa.nif ?? "sin NIF"} · {empresa.forma_juridica ?? "forma jurídica desconocida"} · {empresa.estado ?? "estado desconocido"}
        {empresa.confianza_global != null && ` · confianza ${empresa.confianza_global.toFixed(2)}`}
      </p>
      {empresa.objeto_social && <p className="mt-2 text-sm leading-relaxed text-slate-600">{empresa.objeto_social}</p>}
    </div>
  );
}
