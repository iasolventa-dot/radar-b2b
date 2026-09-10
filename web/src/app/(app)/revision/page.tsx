import Link from "next/link";
import { ExternalLink, Inbox, MapPin } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { ETIQUETA_CATEGORIA_CANDIDATO } from "@/lib/tipos";

export const dynamic = "force-dynamic";

const POR_PAGINA = 30;

export default async function PaginaCola({
  searchParams,
}: {
  searchParams: Promise<{ categoria?: string; pagina?: string }>;
}) {
  const parametros = await searchParams;
  const categoria = parametros.categoria ?? "";
  const pagina = Number(parametros.pagina ?? "1");

  const supabase = await crearClienteServidor();

  let consulta = supabase
    .from("golden_candidatos")
    .select(
      "id_fila, categoria_candidato, confianza_sector, razon_social, municipio, es_municipio_principal, url_evidencia",
      { count: "exact" }
    )
    .eq("estado_revision", "pendiente")
    .order("es_municipio_principal", { ascending: false })
    .order("confianza_sector", { ascending: false })
    .range((pagina - 1) * POR_PAGINA, pagina * POR_PAGINA - 1);

  if (categoria) consulta = consulta.eq("categoria_candidato", categoria);

  const { data: candidatos, count } = await consulta;

  const { data: categorias } = await supabase
    .from("golden_candidatos")
    .select("categoria_candidato")
    .eq("estado_revision", "pendiente");
  const categoriasDisponibles = Array.from(
    new Set((categorias ?? []).map((c) => c.categoria_candidato))
  ).sort();

  const totalPaginas = Math.max(1, Math.ceil((count ?? 0) / POR_PAGINA));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Cola de revisión</h1>
        <p className="mt-1 text-sm text-slate-500">{count ?? 0} candidatos pendientes</p>
      </div>

      <div className="flex flex-wrap gap-2 text-sm">
        <FiltroCategoria activo={categoria === ""} href="/revision" etiqueta="Todas" />
        {categoriasDisponibles.map((c) => (
          <FiltroCategoria
            key={c}
            activo={categoria === c}
            href={`/revision?categoria=${encodeURIComponent(c)}`}
            etiqueta={ETIQUETA_CATEGORIA_CANDIDATO[c] ?? c}
          />
        ))}
      </div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                <th className="th-panel">Razón social</th>
                <th className="th-panel">Categoría</th>
                <th className="th-panel">Confianza</th>
                <th className="th-panel">Municipio</th>
                <th className="th-panel">Evidencia</th>
                <th className="th-panel" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {(candidatos ?? []).map((c) => (
                <tr key={c.id_fila} className="transition-colors hover:bg-slate-50/70">
                  <td className="px-4 py-3 font-medium text-slate-800">{c.razon_social}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {ETIQUETA_CATEGORIA_CANDIDATO[c.categoria_candidato] ?? c.categoria_candidato}
                  </td>
                  <td className="px-4 py-3">
                    <BadgeConfianza confianza={c.confianza_sector} />
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    <div className="flex items-center gap-1.5">
                      <MapPin className="h-3.5 w-3.5 shrink-0 text-slate-400" />
                      {c.municipio}
                      {c.es_municipio_principal && (
                        <span className="badge bg-amber-100 text-amber-800">
                          Alcalá de Guadaíra
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    {c.url_evidencia && (
                      <a
                        href={c.url_evidencia}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-slate-500 hover:text-brand-700 hover:underline"
                      >
                        BORME <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/revision/${encodeURIComponent(c.id_fila)}`} className="btn-primary px-3 py-1.5 text-xs">
                      Revisar
                    </Link>
                  </td>
                </tr>
              ))}
              {(candidatos ?? []).length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-14">
                    <div className="flex flex-col items-center gap-2 text-center text-slate-400">
                      <Inbox className="h-8 w-8" strokeWidth={1.5} />
                      <p className="text-sm">No hay candidatos pendientes en esta categoría.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {totalPaginas > 1 && (
        <div className="flex items-center justify-center gap-4 text-sm">
          {pagina > 1 ? (
            <Link
              href={`/revision?${categoria ? `categoria=${categoria}&` : ""}pagina=${pagina - 1}`}
              className="font-medium text-slate-600 hover:text-brand-700"
            >
              ← Anterior
            </Link>
          ) : (
            <span className="text-slate-300">← Anterior</span>
          )}
          <span className="text-slate-400">
            Página {pagina} de {totalPaginas}
          </span>
          {pagina < totalPaginas ? (
            <Link
              href={`/revision?${categoria ? `categoria=${categoria}&` : ""}pagina=${pagina + 1}`}
              className="font-medium text-slate-600 hover:text-brand-700"
            >
              Siguiente →
            </Link>
          ) : (
            <span className="text-slate-300">Siguiente →</span>
          )}
        </div>
      )}
    </div>
  );
}

function FiltroCategoria({
  activo,
  href,
  etiqueta,
}: {
  activo: boolean;
  href: string;
  etiqueta: string;
}) {
  return (
    <Link
      href={href}
      className={`rounded-full px-3 py-1.5 font-medium transition-colors ${
        activo
          ? "bg-brand-600 text-white shadow-sm"
          : "border border-slate-200 bg-white text-slate-600 hover:bg-slate-100"
      }`}
    >
      {etiqueta}
    </Link>
  );
}

function BadgeConfianza({ confianza }: { confianza: string | null }) {
  if (!confianza) return <span className="text-slate-300">—</span>;
  const colores: Record<string, string> = {
    alta: "bg-emerald-100 text-emerald-800",
    media: "bg-amber-100 text-amber-800",
    baja: "bg-slate-100 text-slate-600",
  };
  return <span className={`badge ${colores[confianza] ?? colores.baja}`}>{confianza}</span>;
}
