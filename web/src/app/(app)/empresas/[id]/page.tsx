import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Clock3,
  FileText,
  Globe,
  Mail,
  MapPin,
  Phone,
  ShieldCheck,
  Users,
} from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

// Antes de esta página, la única forma de ver los datos de una empresa era
// la fila aplastada de la tabla de resultados de una búsqueda: un teléfono,
// un email, un cargo -- nunca todos, y sin ninguna referencia a de dónde
// salió cada dato. Esta página no resume nada: muestra cada sede, cada
// canal de contacto, cada cargo y cada observación (con su fuente y fecha)
// tal cual están en la base de datos.

const ETIQUETA_CARGO: Record<string, string> = {
  administrador_unico: "Administrador único",
  administrador_solidario: "Administrador solidario",
  administrador_mancomunado: "Administrador mancomunado",
  consejero_delegado: "Consejero delegado",
  consejero: "Consejero",
  presidente: "Presidente",
};

const ETIQUETA_CAMPO: Record<string, string> = {
  nif: "NIF",
  razon_social: "Razón social",
  nombre_comercial: "Nombre comercial",
  telefono: "Teléfono",
  email: "Email",
  web: "Web",
  direccion: "Dirección",
  municipio: "Municipio",
  provincia: "Provincia",
  codigo_postal: "Código postal",
  forma_juridica: "Forma jurídica",
  estado_declarado: "Estado (declarado por la fuente)",
  empleados: "Empleados",
  cnae: "CNAE",
  objeto_social: "Objeto social",
  hoja_registral: "Hoja registral",
};

const ETIQUETA_EVENTO: Record<string, string> = {
  cambio_estado: "Cambio de estado",
  cambio_domicilio: "Cambio de domicilio",
  borme_acto: "Nuevo acto en el BORME",
  telefono_invalido: "Teléfono dejó de responder",
  web_caida: "Web dejó de responder",
};

export default async function PaginaDetalleEmpresa({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ desde?: string }>;
}) {
  const { id } = await params;
  const { desde } = await searchParams;
  const supabase = await crearClienteServidor();

  const { data: empresa } = await supabase
    .from("empresas")
    .select(
      "id, nif, nif_valido, razon_social, nombre_comercial, forma_juridica, es_persona_fisica, objeto_social, cnae_principal, cnae_version, estado, estado_confianza, confianza_global, empleados_min, empleados_max, sector_id, dominio_web, creado_en, actualizado_en"
    )
    .eq("id", id)
    .maybeSingle();
  if (!empresa) notFound();

  // Varias consultas planas en vez de una sola anidada a varios niveles: el
  // cliente de Supabase no tiene tipos generados (createBrowserClient sin
  // <Database>), y su inferencia de tipos por plantillas de texto no
  // soporta embeds de dos niveles -- ver progreso-busqueda.tsx, mismo
  // motivo. Aquí en un server component es sync, pero el problema de tipos
  // es el mismo en build.
  const [
    { data: cnae },
    { data: sedes },
    { data: canales },
    { data: identificadores },
    { data: cargos },
    { data: observaciones },
    { data: eventos },
    { data: fuentesFilas },
  ] = await Promise.all([
    empresa.cnae_principal
      ? supabase
          .from("cnae")
          .select("descripcion")
          .eq("codigo", empresa.cnae_principal)
          .eq("version", empresa.cnae_version)
          .maybeSingle()
      : Promise.resolve({ data: null }),
    supabase
      .from("sedes")
      .select("tipo, direccion_original, codigo_postal, municipio_nombre, provincia, activa, confianza, ultima_verificacion")
      .eq("empresa_id", id)
      .order("activa", { ascending: false }),
    supabase
      .from("canales_contacto")
      .select("tipo, valor, estado, confianza, es_generico, ultima_verificacion")
      .eq("empresa_id", id)
      .order("tipo")
      .order("confianza", { ascending: false }),
    supabase.from("identificadores").select("tipo, valor, fuente_id").eq("empresa_id", id),
    supabase.from("cargos").select("cargo, fuente_id, url_evidencia, observado_en, personas(nombre)").eq("empresa_id", id),
    supabase
      .from("observaciones")
      .select("campo, valor_original, valor_norm, fuente_id, url_evidencia, observado_en, confianza")
      .eq("empresa_id", id)
      .order("campo")
      .order("observado_en", { ascending: false }),
    supabase
      .from("eventos_empresa")
      .select("tipo, detalle, fuente_id, creado_en")
      .eq("empresa_id", id)
      .order("creado_en", { ascending: false }),
    supabase.from("fuentes").select("id, codigo, nombre"),
  ]);

  const fuentePorId = new Map((fuentesFilas ?? []).map((f) => [f.id, f]));
  const nombreFuente = (fuenteId: number | null) => {
    if (fuenteId == null) return "—";
    return fuentePorId.get(fuenteId)?.nombre ?? `fuente #${fuenteId}`;
  };

  const observacionesPorCampo = new Map<string, typeof observaciones>();
  for (const o of observaciones ?? []) {
    const lista = observacionesPorCampo.get(o.campo) ?? [];
    lista.push(o);
    observacionesPorCampo.set(o.campo, lista);
  }

  return (
    <div className="space-y-6">
      {desde && (
        <Link href={`/busquedas/${desde}`} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft className="h-4 w-4" /> Volver a los resultados de la búsqueda
        </Link>
      )}

      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{empresa.razon_social}</h1>
          {empresa.nif ? (
            <span className="badge bg-slate-100 font-mono text-slate-700">{empresa.nif}</span>
          ) : (
            <span className="badge bg-amber-100 text-amber-800">sin NIF</span>
          )}
        </div>
        <p className="mt-1 text-sm text-slate-500">
          {empresa.nombre_comercial && <>{empresa.nombre_comercial} · </>}
          {empresa.forma_juridica ?? "forma jurídica desconocida"} · {empresa.estado ?? "estado desconocido"} · confianza{" "}
          {empresa.confianza_global != null ? empresa.confianza_global.toFixed(2) : "—"}
        </p>
      </div>

      {/* Objeto social + CNAE + tamaño */}
      <Seccion icono={FileText} titulo="Actividad">
        <div className="space-y-2 text-sm text-slate-700">
          {empresa.objeto_social && <p>{empresa.objeto_social}</p>}
          <p className="text-slate-500">
            CNAE: {empresa.cnae_principal ? `${empresa.cnae_principal} (${empresa.cnae_version})` : "sin clasificar"}
            {cnae?.descripcion && ` — ${cnae.descripcion}`}
          </p>
          {(empresa.empleados_min != null || empresa.empleados_max != null) && (
            <p className="text-slate-500">
              Empleados: {empresa.empleados_min ?? "?"}–{empresa.empleados_max ?? "?"}
            </p>
          )}
          {empresa.dominio_web && (
            <p className="flex items-center gap-1.5 text-slate-500">
              <Globe className="h-3.5 w-3.5" />
              <a href={`https://${empresa.dominio_web}`} target="_blank" rel="noopener noreferrer" className="hover:text-brand-600">
                {empresa.dominio_web}
              </a>
            </p>
          )}
        </div>
      </Seccion>

      {/* Sedes */}
      <Seccion icono={MapPin} titulo={`Sedes (${sedes?.length ?? 0})`}>
        {sedes && sedes.length > 0 ? (
          <ul className="space-y-2 text-sm">
            {sedes.map((s, i) => (
              <li key={i} className="flex items-start justify-between gap-3 rounded-lg border border-slate-100 p-3">
                <div>
                  <p className="text-slate-800">
                    {s.direccion_original ?? "(sin dirección)"}
                    {s.codigo_postal && `, ${s.codigo_postal}`}
                  </p>
                  <p className="text-slate-500">
                    {s.municipio_nombre}, {s.provincia}
                  </p>
                </div>
                <span className={`badge shrink-0 ${s.activa ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                  {s.tipo} {!s.activa && "· inactiva"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">Sin sedes registradas.</p>
        )}
      </Seccion>

      {/* Canales de contacto -- TODOS, no solo el mejor */}
      <Seccion icono={Phone} titulo={`Contacto (${canales?.length ?? 0})`}>
        {canales && canales.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {canales.map((c, i) => (
              <li key={i} className="flex items-center gap-2">
                {c.tipo === "email" ? <Mail className="h-3.5 w-3.5 text-slate-400" /> : <Phone className="h-3.5 w-3.5 text-slate-400" />}
                <span className="text-slate-700">{c.valor}</span>
                {c.es_generico && <span className="badge bg-slate-100 text-slate-500">genérico</span>}
                {c.estado === "invalido" && <span className="badge bg-rose-100 text-rose-700">inválido</span>}
                <span className="text-xs text-slate-400">confianza {c.confianza?.toFixed(2) ?? "—"}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">Sin teléfono ni email registrados.</p>
        )}
      </Seccion>

      {/* Personas con cargo -- TODAS, no solo la de mayor prioridad */}
      <Seccion icono={Users} titulo={`Empresarios / personas con cargo (${cargos?.length ?? 0})`}>
        {cargos && cargos.length > 0 ? (
          <ul className="space-y-1.5 text-sm">
            {cargos.map((c, i) => {
              const personaRaw = c.personas as { nombre: string } | { nombre: string }[] | null;
              const persona = Array.isArray(personaRaw) ? personaRaw[0] : personaRaw;
              return (
                <li key={i} className="flex items-center justify-between gap-3 rounded-lg border border-slate-100 p-2.5">
                  <span className="text-slate-800">{persona?.nombre ?? "(sin nombre)"}</span>
                  <span className="flex items-center gap-2 text-xs text-slate-500">
                    <span className="badge bg-brand-50 text-brand-700">{ETIQUETA_CARGO[c.cargo] ?? c.cargo}</span>
                    {nombreFuente(c.fuente_id)}
                  </span>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-slate-400">Sin administradores o cargos registrados todavía.</p>
        )}
      </Seccion>

      {/* Identificadores */}
      {identificadores && identificadores.length > 0 && (
        <Seccion icono={ShieldCheck} titulo={`Identificadores (${identificadores.length})`}>
          <ul className="space-y-1 text-sm text-slate-600">
            {identificadores.map((idf, i) => (
              <li key={i}>
                <span className="text-slate-400">{idf.tipo}:</span> <span className="font-mono">{idf.valor}</span>{" "}
                <span className="text-xs text-slate-400">({nombreFuente(idf.fuente_id)})</span>
              </li>
            ))}
          </ul>
        </Seccion>
      )}

      {/* Trazabilidad completa: cada dato, de dónde salió y cuándo -- el detalle
          que la tabla de resultados de una búsqueda nunca puede mostrar */}
      <Seccion icono={Building2} titulo={`Historial de observaciones (${observaciones?.length ?? 0})`}>
        {observacionesPorCampo.size > 0 ? (
          <div className="space-y-4">
            {Array.from(observacionesPorCampo.entries()).map(([campo, filas]) => (
              <div key={campo}>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {ETIQUETA_CAMPO[campo] ?? campo}
                </p>
                <ul className="space-y-1 text-sm">
                  {(filas ?? []).map((o, i) => (
                    <li key={i} className="flex items-center justify-between gap-3 text-slate-600">
                      <span>{o.valor_original ?? o.valor_norm}</span>
                      <span className="shrink-0 text-xs text-slate-400">
                        {nombreFuente(o.fuente_id)} · {new Date(o.observado_en).toLocaleDateString("es-ES")} · confianza{" "}
                        {o.confianza?.toFixed(2) ?? "—"}
                        {o.url_evidencia && (
                          <>
                            {" · "}
                            <a href={o.url_evidencia} target="_blank" rel="noopener noreferrer" className="hover:text-brand-600">
                              evidencia
                            </a>
                          </>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-slate-400">
            Sin observaciones registradas todavía (o la migración 202609141800 no se ha aplicado — sin esa
            política de lectura, esta sección siempre saldría vacía aunque haya datos).
          </p>
        )}
      </Seccion>

      {/* Hechos notables detectados automáticamente -- distinto de las
          observaciones: esto no es "un dato más", es "algo le pasó a esta
          empresa en este momento" (cambió de estado, cambió de domicilio,
          llegó un acto nuevo del BORME). */}
      {eventos && eventos.length > 0 && (
        <Seccion icono={Clock3} titulo={`Historial de la empresa (${eventos.length})`}>
          <ul className="space-y-1.5 text-sm text-slate-600">
            {eventos.map((e, i) => (
              <li key={i} className="flex items-start justify-between gap-3">
                <span>
                  <span className="font-medium text-slate-700">{ETIQUETA_EVENTO[e.tipo] ?? e.tipo}</span>
                  {e.detalle && Object.keys(e.detalle as Record<string, unknown>).length > 0 && (
                    <span className="text-slate-500">
                      {" — "}
                      {Object.entries(e.detalle as Record<string, unknown>)
                        .filter(([, v]) => v != null)
                        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
                        .join(" · ")}
                    </span>
                  )}
                </span>
                <span className="shrink-0 text-xs text-slate-400">
                  {nombreFuente(e.fuente_id)} · {new Date(e.creado_en).toLocaleDateString("es-ES")}
                </span>
              </li>
            ))}
          </ul>
        </Seccion>
      )}
    </div>
  );
}

function Seccion({
  icono: Icono,
  titulo,
  children,
}: {
  icono: React.ComponentType<{ className?: string }>;
  titulo: string;
  children: React.ReactNode;
}) {
  return (
    <div className="card p-5">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-slate-700">
        <Icono className="h-4 w-4 text-slate-400" />
        {titulo}
      </h2>
      {children}
    </div>
  );
}
