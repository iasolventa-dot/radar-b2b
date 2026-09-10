import { notFound } from "next/navigation";
import { AlertTriangle, ExternalLink, FileSearch, ShieldCheck, XCircle } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { ETIQUETA_CATEGORIA_CANDIDATO, type CasoDificil } from "@/lib/tipos";
import { promoverCandidato, descartarCandidato } from "./acciones";

export const dynamic = "force-dynamic";

// Sugerencia de caso_dificil a partir de la categoría automática — el
// humano puede cambiarla, es solo un punto de partida.
const CASO_SUGERIDO: Record<string, CasoDificil | ""> = {
  pool_normal_construccion: "",
  candidato_grupo: "grupo",
  candidato_homonimo: "homonimo",
  candidato_disuelta: "disuelta",
  candidato_traslado: "traslado",
  revisar_objeto_generico: "",
};

const ESTADOS = [
  "activa",
  "probablemente_activa",
  "dudosa",
  "inactiva",
  "en_liquidacion",
  "en_concurso",
  "disuelta",
  "extinguida",
  "desconocida",
];

export default async function PaginaDetalleCandidato({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const supabase = await crearClienteServidor();

  const { data: candidato } = await supabase
    .from("golden_candidatos")
    .select("*")
    .eq("id_fila", decodeURIComponent(id))
    .maybeSingle();

  if (!candidato) notFound();

  const hoy = new Date().toISOString().slice(0, 10);
  const estadoSugerido = candidato.categoria_candidato === "candidato_disuelta" ? "disuelta" : "";
  const casoSugerido = CASO_SUGERIDO[candidato.categoria_candidato] ?? "";

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-medium text-slate-400">{candidato.id_fila}</p>
        <h1 className="mt-0.5 text-2xl font-semibold tracking-tight text-slate-900">
          {candidato.razon_social}
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          {ETIQUETA_CATEGORIA_CANDIDATO[candidato.categoria_candidato] ?? candidato.categoria_candidato}
          {candidato.confianza_sector && ` · confianza de sector: ${candidato.confianza_sector}`}
        </p>
      </div>

      {candidato.categoria_candidato === "revisar_objeto_generico" && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Este candidato solo coincidió por una palabra suelta en un objeto social genérico —
            confirma con especial cuidado que de verdad es del sector construcción antes de
            promoverlo (ver worker/tests/golden/README.md §0).
          </p>
        </div>
      )}

      <section className="card p-5">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-700">
          <FileSearch className="h-4 w-4 text-slate-400" />
          Evidencia del BORME
        </h2>
        <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
          <Campo etiqueta="Municipio">
            {candidato.municipio}
            {candidato.es_municipio_principal && " (municipio piloto)"}
          </Campo>
          <Campo etiqueta="Código postal">{candidato.codigo_postal}</Campo>
          <Campo etiqueta="Hoja registral">{candidato.hoja_registral}</Campo>
          <Campo etiqueta="Capital">{candidato.capital_eur ? `${candidato.capital_eur} €` : null}</Campo>
          <Campo etiqueta="Tipos de acto">{candidato.tipos_acto?.join(", ")}</Campo>
          <Campo etiqueta="Administradores">{candidato.administradores?.join(", ")}</Campo>
          {candidato.objeto_social && (
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-slate-500">Objeto social</dt>
              <dd className="mt-1 text-slate-800">{candidato.objeto_social}</dd>
            </div>
          )}
          {candidato.posible_homonimo_de?.length > 0 && (
            <Campo etiqueta="Posible homónimo de">{candidato.posible_homonimo_de.join(", ")}</Campo>
          )}
          {candidato.posible_grupo_con?.length > 0 && (
            <Campo etiqueta="Posible grupo con">{candidato.posible_grupo_con.join(", ")}</Campo>
          )}
        </dl>
        {candidato.url_evidencia && (
          <a
            href={candidato.url_evidencia}
            target="_blank"
            rel="noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline"
          >
            Ver anuncio original del BORME <ExternalLink className="h-3.5 w-3.5" />
          </a>
        )}
      </section>

      <section className="card p-5">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-slate-700">
          <ShieldCheck className="h-4 w-4 text-emerald-500" />
          Promover a entidad verificada
        </h2>
        <form action={promoverCandidato} className="space-y-5">
          <input type="hidden" name="id_fila" value={candidato.id_fila} />
          <input type="hidden" name="razon_social" value={candidato.razon_social} />
          <input type="hidden" name="municipio" value={candidato.municipio ?? ""} />
          <input type="hidden" name="cp" value={candidato.codigo_postal ?? ""} />
          <input type="hidden" name="url_evidencia" value={candidato.url_evidencia ?? ""} />

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <CampoTexto etiqueta="NIF" name="nif" placeholder="B12345678" />
            <CampoTexto etiqueta="Nombre comercial" name="nombre_comercial" />
            <CampoTexto etiqueta="Forma jurídica" name="forma_juridica" placeholder="SL" />
            <CampoTexto etiqueta="CNAE principal" name="cnae_principal" placeholder="4120" />

            <div>
              <label className="label-field">Estado</label>
              <select name="estado" defaultValue={estadoSugerido} className="input-field">
                <option value="">— sin determinar —</option>
                {ESTADOS.map((e) => (
                  <option key={e} value={e}>
                    {e}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="label-field">Caso difícil</label>
              <select name="caso_dificil" defaultValue={casoSugerido} className="input-field">
                <option value="">— normal —</option>
                <option value="homonimo">Homónimo</option>
                <option value="franquicia">Franquicia</option>
                <option value="grupo">Grupo empresarial</option>
                <option value="disuelta">Disuelta</option>
                <option value="traslado">Traslado</option>
                <option value="autonomo">Autónomo</option>
                <option value="web_agencia">Web con aviso legal de agencia</option>
                <option value="nombre_generico">Nombre genérico</option>
              </select>
            </div>

            <CampoTexto etiqueta="Municipio INE" name="municipio_ine" placeholder="41004" />
            <CampoTexto etiqueta="Provincia" name="provincia" placeholder="Sevilla" defaultValue="Sevilla" />
            <CampoTexto etiqueta="Dirección domicilio social" name="direccion_domicilio_social" />
            <CampoTexto etiqueta="Dirección sede operativa" name="direccion_sede_operativa" />
            <CampoTexto etiqueta="Teléfono" name="telefono" placeholder="+34955123456" />

            <div>
              <label className="label-field">Teléfono verificado por llamada</label>
              <select
                name="telefono_verificado_llamada"
                defaultValue="no_aplica"
                className="input-field"
              >
                <option value="no_aplica">No aplica</option>
                <option value="si">Sí</option>
                <option value="no">No</option>
              </select>
            </div>

            <CampoTexto etiqueta="Web" name="web" placeholder="https://..." />
            <CampoTexto etiqueta="Email genérico" name="email_generico" placeholder="info@empresa.es" />
            <CampoTexto
              etiqueta="Fuentes de verificación"
              name="fuente_verificacion"
              placeholder="BORME;REA;web_corporativa"
            />
            <CampoTexto etiqueta="Verificado por" name="verificado_por" />
            <CampoTexto
              etiqueta="Fecha de verificación"
              name="fecha_verificacion"
              type="date"
              defaultValue={hoy}
            />
          </div>

          <div>
            <label className="label-field">Notas</label>
            <textarea name="notas" rows={2} className="input-field" />
          </div>

          <label
            htmlFor="es_persona_fisica"
            className="flex w-fit items-center gap-2 text-sm text-slate-600"
          >
            <input
              type="checkbox"
              name="es_persona_fisica"
              id="es_persona_fisica"
              className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
            />
            Es persona física (autónomo)
          </label>

          <button type="submit" className="btn-primary">
            <ShieldCheck className="h-4 w-4" />
            Promover a entidad verificada
          </button>
        </form>
      </section>

      <section className="card border-rose-200 bg-rose-50/40 p-5">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-rose-800">
          <XCircle className="h-4 w-4" />
          Descartar candidato
        </h2>
        <form action={descartarCandidato} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <input type="hidden" name="id_fila" value={candidato.id_fila} />
          <div className="flex-1">
            <label className="label-field text-rose-700">Motivo</label>
            <input
              name="motivo_descarte"
              placeholder="p.ej. no es del sector construcción"
              className="input-field border-rose-200 focus:border-rose-400 focus:ring-rose-100"
            />
          </div>
          <button type="submit" className="btn-danger">
            Descartar
          </button>
        </form>
      </section>
    </div>
  );
}

function Campo({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  if (!children) return null;
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500">{etiqueta}</dt>
      <dd className="mt-1 text-slate-800">{children}</dd>
    </div>
  );
}

function CampoTexto({
  etiqueta,
  name,
  placeholder,
  type = "text",
  defaultValue,
}: {
  etiqueta: string;
  name: string;
  placeholder?: string;
  type?: string;
  defaultValue?: string;
}) {
  return (
    <div>
      <label className="label-field">{etiqueta}</label>
      <input
        type={type}
        name={name}
        placeholder={placeholder}
        defaultValue={defaultValue}
        className="input-field"
      />
    </div>
  );
}
