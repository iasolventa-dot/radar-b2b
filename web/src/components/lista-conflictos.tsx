import Link from "next/link";
import { Check, CheckCircle2, ExternalLink, Scissors, ShieldAlert, Sparkles } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { resolverConflicto } from "@/lib/acciones-conflictos";
import { EstadoVacio } from "@/components/encabezado-pagina";

// Filas de `conflictos_datos` (migración 202609241000) pendientes de un tipo:
//  - "sin_contrastar": fuentes que se contradicen sin evidencia suficiente
//    (o un registro unido a una empresa por coincidencia parcial, campo
//    "_identidad"). El sistema ya muestra el valor más probable.
//  - "resuelto_con_evidencia": el sistema lo resolvió solo con evidencia
//    fuerte; aquí solo se confirma o se cambia.

interface Alternativa {
  valor: string;
  valor_norm?: string;
  confianza?: number;
  n_fuentes_independientes?: number;
  dias_desde_ultima?: number;
  registro_oficial?: boolean;
  fuentes?: string[];
  evidencias?: string[];
}

interface Conflicto {
  id: number;
  empresa_id: string;
  campo: string;
  valor_elegido: string | null;
  alternativas: Alternativa[];
  motivo: string;
  puntuacion: number | null;
  creado_en: string;
  actualizado_en: string;
  // radar/agente/resolver_dudas.py: sugerencia de la IA cuando no pudo resolverlo sola
  sugerencia: { valor?: string | null; decision?: string; confianza?: number; motivo?: string } | null;
}

const ETIQUETA_CAMPO: Record<string, string> = {
  nif: "NIF",
  razon_social: "Razón social",
  web: "Web",
  _identidad: "¿Es la misma empresa?",
};

function antiguedad(dias?: number): string {
  if (dias == null) return "";
  if (dias === 0) return "hoy";
  if (dias === 1) return "hace 1 día";
  return `hace ${dias} días`;
}

export async function ListaConflictos({ tipo, vacio }: { tipo: "sin_contrastar" | "resuelto_con_evidencia"; vacio: string }) {
  const supabase = await crearClienteServidor();
  const { data } = await supabase
    .from("conflictos_datos")
    .select("id, empresa_id, campo, valor_elegido, alternativas, motivo, puntuacion, creado_en, actualizado_en, sugerencia")
    .eq("tipo", tipo)
    .eq("estado", "pendiente")
    .order("actualizado_en", { ascending: false })
    .limit(200);
  const conflictos = (data ?? []) as Conflicto[];

  const ids = Array.from(new Set(conflictos.map((c) => c.empresa_id)));
  const { data: empresas } = ids.length
    ? await supabase.from("empresas").select("id, razon_social, nombre_comercial, nif, dominio_web").in("id", ids)
    : { data: [] as { id: string; razon_social: string | null; nombre_comercial: string | null; nif: string | null; dominio_web: string | null }[] };
  const empresaPorId = new Map((empresas ?? []).map((e) => [e.id, e]));

  if (conflictos.length === 0) {
    return (
      <div className="card">
        <EstadoVacio icono={CheckCircle2}>{vacio}</EstadoVacio>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {conflictos.map((c) => {
        const empresa = empresaPorId.get(c.empresa_id);
        const nombreEmpresa = empresa?.razon_social ?? empresa?.nombre_comercial ?? "(sin nombre)";
        const esIdentidad = c.campo === "_identidad";
        return (
          <div key={c.id} className="card overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 bg-gradient-to-r from-amber-50/70 via-white to-white px-6 py-4">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="badge bg-amber-50 text-amber-700">
                  <ShieldAlert className="h-3.5 w-3.5" />
                  {ETIQUETA_CAMPO[c.campo] ?? c.campo}
                </span>
                <Link
                  href={`/empresas/${c.empresa_id}`}
                  className="font-display text-base font-bold text-slate-900 hover:text-brand-700"
                >
                  {nombreEmpresa}
                </Link>
                {empresa?.nif && (
                  <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-slate-600">
                    {empresa.nif}
                  </span>
                )}
              </div>
              <span className="text-sm text-slate-400">{new Date(c.actualizado_en).toLocaleString("es-ES")}</span>
            </div>
            <div className="p-6">
            <p className="mb-4 text-[15px] leading-relaxed text-slate-700">{c.motivo}</p>

            {c.sugerencia && (
              <p className="mb-4 rounded-xl border border-violet-200 bg-gradient-to-br from-violet-50 via-white to-brand-50 p-4 text-sm leading-relaxed text-violet-950">
                <Sparkles className="mr-1.5 inline h-4 w-4 text-violet-600" />
                <strong>Sugerencia de la IA</strong>
                {c.sugerencia.decision && (
                  <> ({c.sugerencia.decision === "misma" ? "es la misma empresa" : c.sugerencia.decision === "distinta" ? "son empresas distintas: sepáralo" : "no lo tiene claro"})</>
                )}
                {c.sugerencia.valor && <>: usar «{c.sugerencia.valor}»</>}
                {c.sugerencia.confianza != null && <span className="text-violet-700"> · confianza {c.sugerencia.confianza.toFixed(2)}</span>}
                {c.sugerencia.motivo && <span className="block text-violet-800">{c.sugerencia.motivo}</span>}
              </p>
            )}

            {esIdentidad ? (
              <>
                <p className="text-sm text-slate-700">
                  Se unió a esta empresa el registro de{" "}
                  <strong>{c.alternativas[0]?.fuentes?.join(", ") ?? "otra fuente"}</strong>
                  {c.alternativas[0]?.valor && (
                    <>
                      {" "}
                      llamado <strong>&ldquo;{c.alternativas[0].valor}&rdquo;</strong>
                    </>
                  )}
                  {c.puntuacion != null && <span className="text-slate-400"> (coincidencia {Number(c.puntuacion).toFixed(2)})</span>}
                  . Sus datos ya están rellenando la ficha.
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <FormularioAccion id={c.id} accion="confirmar" clase="btn-primary">
                    <Check className="h-4 w-4" /> Sí, es la misma empresa
                  </FormularioAccion>
                  <FormularioAccion id={c.id} accion="separar" clase="btn-danger">
                    <Scissors className="h-4 w-4" /> No lo es: separar en otra empresa
                  </FormularioAccion>
                </div>
              </>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs font-bold uppercase tracking-wider text-slate-400">
                      <th className="pb-2 pl-2 pr-4">Valor</th>
                      <th className="pb-2 pr-4">Fuentes</th>
                      <th className="pb-2 pr-4">Confianza</th>
                      <th className="pb-2 pr-4">Último dato</th>
                      <th className="pb-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {c.alternativas.map((a) => {
                      const elegido = a.valor === c.valor_elegido;
                      return (
                        <tr key={a.valor_norm ?? a.valor} className={`border-t border-slate-100 ${elegido ? "bg-emerald-50/50" : ""}`}>
                          <td className={`py-3 pl-2 pr-4 ${elegido ? "font-semibold text-slate-900" : "text-slate-700"}`}>
                            {a.valor}
                            {elegido && (
                              <span className="ml-2 badge bg-emerald-50 text-emerald-700">
                                <span className="punto" />
                                en uso
                              </span>
                            )}
                            {c.sugerencia?.valor && c.sugerencia.valor === a.valor && !elegido && (
                              <span className="ml-2 badge bg-violet-50 text-violet-700">
                                <Sparkles className="h-3 w-3" />
                                sugerido por IA
                              </span>
                            )}
                            {a.evidencias?.[0] && (
                              <a href={a.evidencias[0]} target="_blank" rel="noreferrer" className="ml-2 inline-flex text-slate-400 hover:text-brand-600">
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                          </td>
                          <td className="py-3 pr-4 text-slate-600">
                            {(a.fuentes ?? []).join(", ")}
                            {a.registro_oficial && <span className="ml-1 text-xs text-emerald-700">(registro oficial)</span>}
                          </td>
                          <td className="py-3 pr-4 font-semibold tabular-nums text-slate-700">{a.confianza?.toFixed(2) ?? "—"}</td>
                          <td className="py-3 pr-4 text-slate-500">{antiguedad(a.dias_desde_ultima)}</td>
                          <td className="py-3 pr-2 text-right">
                            {elegido ? (
                              <FormularioAccion id={c.id} accion="confirmar" clase="btn-primary">
                                <Check className="h-4 w-4" /> Confirmar
                              </FormularioAccion>
                            ) : (
                              <FormularioAccion id={c.id} accion="elegir" valor={a.valor} clase="btn-secondary">
                                Usar este valor
                              </FormularioAccion>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function FormularioAccion({
  id,
  accion,
  valor,
  clase,
  children,
}: {
  id: number;
  accion: "confirmar" | "elegir" | "separar";
  valor?: string;
  clase: string;
  children: React.ReactNode;
}) {
  return (
    <form action={resolverConflicto} className="inline">
      <input type="hidden" name="id" value={id} />
      <input type="hidden" name="accion" value={accion} />
      {valor != null && <input type="hidden" name="valor" value={valor} />}
      <button type="submit" className={clase}>
        {children}
      </button>
    </form>
  );
}
