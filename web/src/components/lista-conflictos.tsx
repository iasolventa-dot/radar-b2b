import Link from "next/link";
import { Check, CheckCircle2, ExternalLink, Scissors, ShieldAlert } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { resolverConflicto } from "@/lib/acciones-conflictos";

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
    .select("id, empresa_id, campo, valor_elegido, alternativas, motivo, puntuacion, creado_en, actualizado_en")
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
      <div className="card flex flex-col items-center gap-2 p-14 text-center text-slate-400">
        <CheckCircle2 className="h-8 w-8" strokeWidth={1.5} />
        <p className="text-sm">{vacio}</p>
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
          <div key={c.id} className="card p-5">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="badge bg-amber-100 text-amber-800">
                  <ShieldAlert className="mr-1 h-3 w-3" />
                  {ETIQUETA_CAMPO[c.campo] ?? c.campo}
                </span>
                <Link href={`/empresas/${c.empresa_id}`} className="font-medium text-slate-800 hover:text-brand-600">
                  {nombreEmpresa}
                </Link>
                {empresa?.nif && <span className="text-xs text-slate-400">{empresa.nif}</span>}
              </div>
              <span className="text-xs text-slate-400">{new Date(c.actualizado_en).toLocaleString("es-ES")}</span>
            </div>

            <p className="mb-3 text-sm text-slate-600">{c.motivo}</p>

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
                    <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                      <th className="py-1 pr-4">Valor</th>
                      <th className="py-1 pr-4">Fuentes</th>
                      <th className="py-1 pr-4">Confianza</th>
                      <th className="py-1 pr-4">Último dato</th>
                      <th className="py-1" />
                    </tr>
                  </thead>
                  <tbody>
                    {c.alternativas.map((a) => {
                      const elegido = a.valor === c.valor_elegido;
                      return (
                        <tr key={a.valor_norm ?? a.valor} className="border-t border-slate-100">
                          <td className={`py-2 pr-4 ${elegido ? "font-semibold text-slate-900" : "text-slate-600"}`}>
                            {a.valor}
                            {elegido && <span className="ml-2 badge bg-emerald-100 text-emerald-700">en uso</span>}
                            {a.evidencias?.[0] && (
                              <a href={a.evidencias[0]} target="_blank" rel="noreferrer" className="ml-2 inline-flex text-slate-400 hover:text-brand-600">
                                <ExternalLink className="h-3 w-3" />
                              </a>
                            )}
                          </td>
                          <td className="py-2 pr-4 text-slate-500">
                            {(a.fuentes ?? []).join(", ")}
                            {a.registro_oficial && <span className="ml-1 text-xs text-emerald-700">(registro oficial)</span>}
                          </td>
                          <td className="py-2 pr-4 text-slate-500">{a.confianza?.toFixed(2) ?? "—"}</td>
                          <td className="py-2 pr-4 text-slate-500">{antiguedad(a.dias_desde_ultima)}</td>
                          <td className="py-2 text-right">
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
