"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Ban,
  Brain,
  Building2,
  CalendarClock,
  CheckCircle2,
  Clock3,
  Database,
  Download,
  Euro,
  Filter,
  Flag,
  Globe,
  HelpCircle,
  Landmark,
  Loader2,
  Mail,
  MapPinned,
  Phone,
  PieChart,
  Radar,
  RotateCw,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { EstadoVacio, TarjetaCifra } from "@/components/encabezado-pagina";
import { EstadoBusqueda } from "@/components/estado-busqueda";
import { crearClienteNavegador } from "@/lib/supabase/client";
import { cancelarBusqueda, confirmarBusqueda } from "@/lib/api";
import { describirFiltros } from "@/lib/filtros";
import { exportarResultadosCsv } from "@/lib/exportar-csv";
import {
  ETIQUETA_CARGO,
  ETIQUETA_HERRAMIENTA,
  etiquetaFuenteResultado,
  PRIORIDAD_CARGO,
  type BusquedaFila,
  type RondaEstadistica,
} from "@/lib/tipos";

// Solo 'en_curso' cambia por sí sola con el tiempo (el planificador va
// escribiendo progreso ronda a ronda, `on_ronda` en radar.agente.planificador)
// — el resto son estados de reposo (esperando confirmación) o terminales
// (completada/error/esperando_respuesta/cancelada: el bucle ya paró, ver
// docstring de radar.api.main). Sondear esos no aporta nada, solo gasta
// peticiones.
const INTERVALO_SONDEO_MS = 4000;
const ESTADOS_QUE_CAMBIAN_SOLOS = new Set(["en_curso"]);
// Estados desde los que se puede pedir cancelar (radar.api.main::cancelar).
const ESTADOS_CANCELABLES = new Set(["en_curso", "esperando_respuesta"]);

interface EmpresaResultado {
  empresa_id: string;
  motivo: string | null;
  razon_social: string;
  nif: string | null;
  estado: string | null;
  confianza_global: number | null;
  dominio_web: string | null;
  telefono: string | null;
  email: string | null;
  contacto: string | null;
  // conflictos_datos pendientes de la empresa (migración 202609241000)
  sin_contrastar: number;
  en_revision: number;
  // busqueda_resultados.relevancia (migración 202609251000, radar/agente/relevancia.py)
  relevancia: string | null;
  motivo_relevancia: string | null;
}

const HERRAMIENTAS_DESCUBRIMIENTO = new Set([
  "descubrir_borme", "buscar_web", "descubrir_osm", "descubrir_places", "descubrir_apify_maps",
  "descubrir_google_search", "enriquecer_con_apify", "enriquecer_con_linkedin", "enriquecer_con_facebook",
]);

function resumenRonda(ronda: RondaEstadistica): string {
  const r = ronda.resultado as Record<string, unknown>;
  if (ronda.herramienta === "consultar_bd") return `${r.total ?? 0} empresas en la BD que cumplen los filtros`;
  if (ronda.herramienta === "estimar_cobertura") {
    if (r.soportado === false) return String(r.motivo ?? "sin datos suficientes para estimar cobertura");
    const pct = r.pct_cobertura != null ? `${r.pct_cobertura}%` : "sin estimación";
    return `${r.empresas_propias ?? 0} de ~${r.estimado_dirce ?? "?"} según el INE (${pct} de cobertura, ${r.anyo_dirce ?? "?"})`;
  }
  if (ronda.herramienta === "completar_contacto") {
    const antes = (r.antes ?? {}) as Record<string, number>;
    const despues = (r.despues ?? {}) as Record<string, number>;
    const d = (k: string) => `${antes[k] ?? 0}→${despues[k] ?? 0}`;
    const coste = typeof r.coste_eur === "number" ? ` · ${r.coste_eur.toFixed(3)} €` : "";
    return `${despues.empresas ?? 0} empresas · web ${d("con_web")} · teléfono ${d("con_telefono")} · email ${d("con_email")} (${r.webs_leidas ?? 0} webs leídas)${coste}`;
  }
  if (ronda.herramienta === "enriquecer_borme") {
    return `${r.empresas_revisadas ?? 0} sociedades buscadas en el BORME: ${r.encontradas_en_borme ?? 0} encontradas, ${r.unidas ?? 0} actos añadidos (administradores, hoja registral)`;
  }
  if (ronda.herramienta === "evaluar_relevancia") {
    if (typeof r.error === "string" && r.error) return `error: ${r.error}`;
    return `${r.evaluadas ?? 0} revisadas: ${r.relevante ?? 0} del sector, ${r.dudoso ?? 0} dudosas, ${r.descartado ?? 0} descartadas`;
  }
  if (ronda.herramienta === "resolver_dudas") {
    return `${r.revisadas ?? 0} dudas: ${r.resueltas_con_evidencia_web ?? 0} resueltas con su web, ${r.resueltas_por_ia ?? 0} por IA, ${r.con_sugerencia ?? 0} con sugerencia`;
  }
  if (HERRAMIENTAS_DESCUBRIMIENTO.has(ronda.herramienta)) {
    const partes: string[] = [];
    if (typeof r.error === "string" && r.error) partes.push(`error: ${r.error}`);
    if (typeof r.motivo === "string" && r.soportado === false) partes.push(r.motivo);
    if (typeof r.motivo_parada === "string") partes.push(`parada: ${r.motivo_parada.replaceAll("_", " ")}`);
    if (typeof r.lugares_encontrados === "number") partes.push(`${r.lugares_encontrados} negocios en Maps`);
    if (typeof r.con_telefono === "number" && r.con_telefono) partes.push(`${r.con_telefono} con teléfono`);
    if (typeof r.con_web === "number" && r.con_web) partes.push(`${r.con_web} con web`);
    if (typeof r.webs_leidas === "number" && r.webs_leidas) partes.push(`${r.webs_leidas} webs leídas`);
    if (typeof r.urls_encontradas === "number" && r.urls_encontradas) partes.push(`${r.urls_encontradas} resultados`);
    if (typeof r.descartados_municipio_desconocido === "number" && r.descartados_municipio_desconocido)
      partes.push(`${r.descartados_municipio_desconocido} sin municipio conocido`);
    if (typeof r.descartados_por_zona === "number" && r.descartados_por_zona)
      partes.push(`${r.descartados_por_zona} fuera de la zona`);
    if (typeof r.nueva_empresa === "number" && r.nueva_empresa) partes.push(`${r.nueva_empresa} nuevas`);
    if (typeof r.vinculado === "number" && r.vinculado) partes.push(`${r.vinculado} vinculadas`);
    if (typeof r.en_revision === "number" && r.en_revision) partes.push(`${r.en_revision} en revisión`);
    // Estos dos faltaban y son justo los que explican una ronda "vacía":
    // sin ellos, una ronda que miró 200 actos y descartó 195 por sector se
    // resumía igual que una que no encontró nada en absoluto.
    if (typeof r.ya_procesado === "number" && r.ya_procesado) partes.push(`${r.ya_procesado} ya conocidas`);
    if (typeof r.descartados_por_sector === "number" && r.descartados_por_sector)
      partes.push(`${r.descartados_por_sector} descartadas por sector`);
    if (typeof r.urls_no_legibles === "number" && r.urls_no_legibles)
      partes.push(`${r.urls_no_legibles} webs no legibles`);
    const errores =
      (typeof r.error === "number" ? r.error : 0) +
      (typeof r.error_procesado === "number" ? r.error_procesado : 0) +
      (typeof r.error_busqueda === "number" ? r.error_busqueda : 0);
    if (errores) partes.push(`${errores} con error`);
    return partes.length ? partes.join(", ") : "sin resultados nuevos";
  }
  if (ronda.herramienta === "preguntar_usuario") return String(r.pregunta ?? "");
  if (ronda.herramienta === "finalizar_busqueda") return String(r.resumen ?? "");
  if (ronda.herramienta === "planificador_llm") {
    const entrada = typeof r.tokens_entrada === "number" ? r.tokens_entrada : 0;
    const salida = typeof r.tokens_salida === "number" ? r.tokens_salida : 0;
    const coste = typeof r.coste_eur === "number" ? r.coste_eur.toFixed(4) : "0.0000";
    return `${entrada + salida} tokens (${entrada} entrada, ${salida} salida) · ${coste} €`;
  }
  return "";
}

export function ProgresoBusqueda({ id, inicial }: { id: string; inicial: BusquedaFila }) {
  const [busqueda, setBusqueda] = useState<BusquedaFila>(inicial);
  const [resultados, setResultados] = useState<EmpresaResultado[]>([]);
  // Descartadas por el filtro de relevancia (IA) o por una persona: no se
  // muestran ni se exportan; se pueden recuperar en la Cola de revisión.
  const [descartadas, setDescartadas] = useState(0);
  const [confirmando, setConfirmando] = useState(false);
  const [errorConfirmar, setErrorConfirmar] = useState<string | null>(null);
  const [cancelando, setCancelando] = useState(false);
  const [errorCancelar, setErrorCancelar] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    const supabase = crearClienteNavegador();

    async function sondear() {
      const { data: fila } = await supabase
        .from("busquedas")
        .select("id, peticion, filtros, presupuesto_eur, estado, rondas, estadisticas, coste_eur, creado_en, finalizado_en")
        .eq("id", id)
        .maybeSingle();
      if (cancelado || !fila) return;
      setBusqueda(fila as unknown as BusquedaFila);

      const { data: filas } = await supabase
        .from("busqueda_resultados")
        .select("empresa_id, motivo, clasificacion, motivo_relevancia, empresas(razon_social, nombre_comercial, nif, estado, confianza_global, dominio_web)")
        .eq("busqueda_id", id)
        .limit(200);
      if (cancelado || !filas) return;

      const empresaIds = filas.map((f: Record<string, unknown>) => f.empresa_id as string);
      // Dos consultas planas aparte (no anidadas dentro de la de arriba):
      // el cliente de Supabase no tiene tipos generados (createBrowserClient
      // sin <Database>), y su inferencia de tipos por plantillas de texto
      // no soporta un embed de dos niveles -- rompía la compilación con
      // GenericStringError. Con consultas de un solo nivel cada una, no
      // hay ese problema (mismo motivo que separó teléfono/email).
      const { data: canales } = empresaIds.length
        ? await supabase.from("canales_contacto").select("empresa_id, tipo, valor, estado").in("empresa_id", empresaIds)
        : { data: [] as { empresa_id: string; tipo: string; valor: string; estado: string }[] };
      const { data: cargos } = empresaIds.length
        ? await supabase
            .from("cargos")
            .select("empresa_id, cargo, personas(nombre)")
            .in("empresa_id", empresaIds)
        : { data: [] as { empresa_id: string; cargo: string; personas: { nombre: string } | { nombre: string }[] | null }[] };
      const { data: conflictos } = empresaIds.length
        ? await supabase.from("conflictos_datos").select("empresa_id, tipo").eq("estado", "pendiente").in("empresa_id", empresaIds)
        : { data: [] as { empresa_id: string; tipo: string }[] };
      if (cancelado) return;

      const conflictosPorEmpresa = new Map<string, { sin_contrastar: number; en_revision: number }>();
      for (const c of conflictos ?? []) {
        const actual = conflictosPorEmpresa.get(c.empresa_id) ?? { sin_contrastar: 0, en_revision: 0 };
        if (c.tipo === "sin_contrastar") actual.sin_contrastar += 1;
        else actual.en_revision += 1;
        conflictosPorEmpresa.set(c.empresa_id, actual);
      }

      const canalesPorEmpresa = new Map<string, { tipo: string; valor: string; estado: string }[]>();
      for (const c of canales ?? []) {
        const lista = canalesPorEmpresa.get(c.empresa_id) ?? [];
        lista.push(c);
        canalesPorEmpresa.set(c.empresa_id, lista);
      }

      const cargosPorEmpresa = new Map<string, { nombre: string; cargo: string }[]>();
      for (const c of cargos ?? []) {
        const personaRaw = c.personas as { nombre: string } | { nombre: string }[] | null;
        const persona = Array.isArray(personaRaw) ? personaRaw[0] : personaRaw;
        if (!persona) continue;
        const lista = cargosPorEmpresa.get(c.empresa_id) ?? [];
        lista.push({ nombre: persona.nombre, cargo: c.cargo });
        cargosPorEmpresa.set(c.empresa_id, lista);
      }

      const filasTodas: EmpresaResultado[] = (
        filas.map((f: Record<string, unknown>) => {
          type Empresa = {
            razon_social: string | null; nombre_comercial: string | null; nif: string | null; estado: string | null;
            confianza_global: number | null; dominio_web: string | null;
          };
          const empresaRaw = f.empresas as Empresa | Empresa[] | null;
          const empresa = Array.isArray(empresaRaw) ? empresaRaw[0] : empresaRaw;
          const empresaId = f.empresa_id as string;
          const canalesEmpresa = canalesPorEmpresa.get(empresaId) ?? [];
          // Si hay varios, el primero no marcado como inválido -- para una
          // tabla compacta de leads basta con uno; el resto sigue estando
          // en canales_contacto para quien necesite verlos todos.
          const telefono = canalesEmpresa.find((c) => c.tipo === "telefono" && c.estado !== "invalido");
          const email = canalesEmpresa.find((c) => c.tipo === "email" && c.estado !== "invalido");
          // Igual con los cargos: si la misma empresa tiene varios (p. ej.
          // presidente Y consejero delegado, o son personas distintas),
          // se muestra el de mayor prioridad -- el resto sigue estando en
          // `cargos`/`personas` para quien necesite verlos todos.
          const cargosEmpresa = cargosPorEmpresa.get(empresaId) ?? [];
          cargosEmpresa.sort((a, b) => PRIORIDAD_CARGO.indexOf(a.cargo) - PRIORIDAD_CARGO.indexOf(b.cargo));
          const principal = cargosEmpresa[0];
          const contacto = principal ? `${principal.nombre} (${ETIQUETA_CARGO[principal.cargo] ?? principal.cargo})` : null;
          return {
            empresa_id: empresaId,
            motivo: f.motivo as string | null,
            razon_social: empresa?.razon_social ?? empresa?.nombre_comercial ?? "(sin nombre)",
            nif: empresa?.nif ?? null,
            estado: empresa?.estado ?? null,
            confianza_global: empresa?.confianza_global ?? null,
            dominio_web: empresa?.dominio_web ?? null,
            telefono: telefono?.valor ?? null,
            email: email?.valor ?? null,
            contacto,
            sin_contrastar: conflictosPorEmpresa.get(empresaId)?.sin_contrastar ?? 0,
            en_revision: conflictosPorEmpresa.get(empresaId)?.en_revision ?? 0,
            relevancia: (f.clasificacion as string | null) ?? null,
            motivo_relevancia: (f.motivo_relevancia as string | null) ?? null,
          };
        })
      );
      const ocultas = new Set(["descartado", "rechazado"]);
      setResultados(filasTodas.filter((r) => !ocultas.has(r.relevancia ?? "")));
      setDescartadas(filasTodas.filter((r) => ocultas.has(r.relevancia ?? "")).length);
    }

    sondear();
    if (!ESTADOS_QUE_CAMBIAN_SOLOS.has(busqueda.estado)) return;
    const intervalo = setInterval(sondear, INTERVALO_SONDEO_MS);
    return () => {
      cancelado = true;
      clearInterval(intervalo);
    };
  }, [id, busqueda.estado]);

  async function confirmar() {
    setConfirmando(true);
    setErrorConfirmar(null);
    try {
      await confirmarBusqueda(id, { maxRondas: busqueda.estadisticas?.max_rondas ?? 10 });
      setBusqueda((b) => ({ ...b, estado: "en_curso" }));
    } catch (err) {
      setErrorConfirmar(err instanceof Error ? err.message : String(err));
    } finally {
      setConfirmando(false);
    }
  }

  async function cancelar() {
    setCancelando(true);
    setErrorCancelar(null);
    try {
      const resultado = await cancelarBusqueda(id);
      // Si venía de 'esperando_respuesta' el worker ya cierra el estado al
      // momento; si venía de 'en_curso' solo queda pedido -- el propio
      // sondeo (sigue activo mientras estado siga siendo 'en_curso') verá
      // el cambio a 'cancelada' en cuanto el planificador lo recoja entre
      // rondas, sin que haga falta hacer nada más aquí.
      setBusqueda((b) => ({ ...b, estado: resultado.estado }));
    } catch (err) {
      setErrorCancelar(err instanceof Error ? err.message : String(err));
    } finally {
      setCancelando(false);
    }
  }

  const activa = busqueda.estado === "en_curso";
  const rondas = busqueda.estadisticas?.rondas ?? [];
  const maxRondas = busqueda.estadisticas?.max_rondas ?? null;
  const presupuesto = busqueda.presupuesto_eur != null ? Number(busqueda.presupuesto_eur) : null;
  const pctGasto = presupuesto ? Math.min(100, (busqueda.coste_eur / presupuesto) * 100) : 0;
  const conTelefono = resultados.filter((r) => r.telefono).length;
  const conEmail = resultados.filter((r) => r.email).length;

  return (
    <div className="entrada space-y-7">
      <Link
        href="/busquedas"
        className="inline-flex items-center gap-1.5 rounded-full bg-white/70 px-3 py-1.5 text-sm font-semibold text-slate-600 shadow-sm ring-1 ring-slate-200 transition hover:-translate-x-0.5 hover:text-brand-700"
      >
        <ArrowLeft className="h-4 w-4" /> Búsquedas
      </Link>

      {/* Cabecera */}
      <div className="card relative overflow-hidden p-6 sm:p-7">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-gradient-to-br from-brand-200/50 via-violet-200/40 to-transparent blur-3xl" />
        <div className="relative flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-3xl">
            <p className="mb-1.5 text-xs font-bold uppercase tracking-[0.16em] text-brand-600">Búsqueda</p>
            <h1 className="font-display text-3xl font-extrabold tracking-tight text-slate-900">{busqueda.peticion}</h1>
            <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500">
              <span className="inline-flex items-center gap-1.5">
                <CalendarClock className="h-4 w-4" /> Lanzada el {new Date(busqueda.creado_en).toLocaleString("es-ES")}
              </span>
              {busqueda.finalizado_en && (
                <span className="inline-flex items-center gap-1.5">
                  <Flag className="h-4 w-4" /> Terminada el {new Date(busqueda.finalizado_en).toLocaleString("es-ES")}
                </span>
              )}
            </p>
          </div>
          <div className="flex flex-col items-end gap-3">
            <EstadoBusqueda estado={busqueda.estado} />
            {ESTADOS_CANCELABLES.has(busqueda.estado) && (
              <button type="button" onClick={cancelar} disabled={cancelando} className="btn-danger">
                {cancelando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />}
                Cancelar búsqueda
              </button>
            )}
            {errorCancelar && <p className="text-sm text-rose-600">{errorCancelar}</p>}
          </div>
        </div>

        {activa && (
          <div className="relative mt-6">
            <div className="mb-2 flex items-center justify-between text-sm font-semibold text-slate-600">
              <span className="inline-flex items-center gap-2 text-brand-700">
                <Loader2 className="h-4 w-4 animate-spin" /> El agente está trabajando…
              </span>
              <span className="tabular-nums">
                Ronda {busqueda.rondas}
                {maxRondas ? ` de ${maxRondas}` : ""}
              </span>
            </div>
            <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div
                className="h-full rounded-full bg-gradient-to-r from-brand-500 via-violet-500 to-senal-400 transition-all duration-700"
                style={{ width: `${Math.max(6, maxRondas ? Math.min(100, (busqueda.rondas / maxRondas) * 100) : 30)}%` }}
              />
              <span className="destello" />
            </div>
          </div>
        )}
      </div>

      {busqueda.estado === "interpretada" && (
        <div className="aviso-atencion flex-wrap items-center justify-between">
          <p className="flex items-center gap-2 font-semibold">
            <HelpCircle className="h-5 w-5 text-amber-600" /> Esta búsqueda todavía no se ha confirmado.
          </p>
          <div className="flex items-center gap-3">
            {errorConfirmar && <p className="text-sm text-rose-600">{errorConfirmar}</p>}
            <button type="button" onClick={confirmar} disabled={confirmando} className="btn-primary">
              {confirmando ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
              Confirmar y buscar
            </button>
          </div>
        </div>
      )}

      {/* Cifras clave */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <TarjetaCifra icono={Building2} etiqueta="Empresas encontradas" valor={resultados.length} tono="marca"
          detalle={descartadas > 0 ? `${descartadas} descartadas por no ser del sector` : undefined} />
        <TarjetaCifra icono={Phone} etiqueta="Con teléfono" valor={conTelefono} tono="verde"
          detalle={resultados.length ? `${Math.round((conTelefono / resultados.length) * 100)} % · ${conEmail} con email` : undefined} />
        <TarjetaCifra icono={Euro} etiqueta="Coste" valor={`${busqueda.coste_eur.toFixed(2)} €`} tono="cian"
          detalle={presupuesto != null ? `de ${presupuesto.toFixed(2)} € de presupuesto` : undefined}>
          {presupuesto != null && (
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-gradient-to-r from-senal-400 to-brand-500" style={{ width: `${pctGasto}%` }} />
            </div>
          )}
        </TarjetaCifra>
        <TarjetaCifra icono={Clock3} etiqueta="Rondas" valor={`${busqueda.rondas} / ${maxRondas ?? "—"}`} tono="ambar" />
      </div>

      {busqueda.estadisticas?.pregunta && (
        <div className="aviso-atencion">
          <HelpCircle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div>
            <p className="font-semibold">El agente tiene una pregunta:</p>
            <p className="mt-0.5 text-base">{busqueda.estadisticas.pregunta.pregunta}</p>
            {busqueda.estadisticas.pregunta.opciones.length > 0 && (
              <p className="mt-1 text-sm text-amber-800/80">
                Opciones: {busqueda.estadisticas.pregunta.opciones.join(" / ")}
              </p>
            )}
            <p className="mt-2 text-sm text-amber-800/80">
              Este primer agente todavía no es interactivo: no puede continuar ESTA búsqueda con tu
              respuesta. Lánzala de nuevo con la respuesta como contexto.
            </p>
            <Link
              href={{
                pathname: "/",
                query: {
                  peticion: busqueda.peticion,
                  contexto: `El agente preguntó: "${busqueda.estadisticas.pregunta.pregunta}". Mi respuesta: `,
                },
              }}
              className="btn-secondary mt-3 inline-flex"
            >
              <RotateCw className="h-4 w-4" />
              Responder y relanzar
            </Link>
          </div>
        </div>
      )}

      {busqueda.estado === "error" && (
        <div className="aviso-error">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <div>
            <p className="font-semibold">La búsqueda terminó con un error</p>
            <p className="mt-0.5">{busqueda.estadisticas?.error ?? "sin detalle"}</p>
          </div>
        </div>
      )}

      {busqueda.estado === "completada" && busqueda.estadisticas?.resumen && (
        <div className="aviso-ok">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div>
            <p className="font-semibold">
              Búsqueda terminada
              {busqueda.estadisticas.motivo_fin && (
                <span className="ml-2 badge bg-emerald-100 text-emerald-800">
                  {busqueda.estadisticas.motivo_fin.replaceAll("_", " ")}
                </span>
              )}
            </p>
            <p className="mt-1">{busqueda.estadisticas.resumen}</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* Progreso ronda a ronda */}
        <section className="card p-6">
          <h2 className="titulo-seccion mb-5">
            <span className="icono-seccion">
              <Activity className="h-4 w-4" />
            </span>
            Progreso ronda a ronda
          </h2>
          {rondas.length > 0 ? (
            <ol className="relative space-y-1">
              <span className="absolute bottom-4 left-[19px] top-4 w-px bg-gradient-to-b from-brand-200 via-violet-200 to-transparent" />
              {rondas.map((ronda, i) => {
                const Icono = iconoHerramienta(ronda.herramienta);
                const ultima = i === rondas.length - 1;
                return (
                  <li key={ronda.numero} className="relative flex items-start gap-4 rounded-xl px-1 py-2.5 transition hover:bg-slate-50">
                    <span
                      className={`relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ring-4 ring-white ${
                        ultima && activa
                          ? "bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-brillo"
                          : "bg-gradient-to-br from-slate-50 to-slate-100 text-slate-600 ring-1"
                      }`}
                    >
                      {ultima && activa ? <Loader2 className="h-[18px] w-[18px] animate-spin" /> : <Icono className="h-[18px] w-[18px]" />}
                    </span>
                    <div className="min-w-0 pt-0.5">
                      <p className="flex flex-wrap items-center gap-2 font-semibold text-slate-900">
                        {ETIQUETA_HERRAMIENTA[ronda.herramienta] ?? ronda.herramienta}
                        <span className="text-xs font-medium text-slate-400">#{ronda.numero}</span>
                      </p>
                      <p className="mt-0.5 text-sm leading-relaxed text-slate-600">{resumenRonda(ronda)}</p>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <EstadoVacio icono={Activity}>{activa ? "Preparando la primera ronda…" : "Esta búsqueda no tiene rondas."}</EstadoVacio>
          )}
        </section>

        {/* Filtros */}
        <aside className="card h-fit p-6">
          <h2 className="titulo-seccion mb-4">
            <span className="icono-seccion">
              <SlidersHorizontal className="h-4 w-4" />
            </span>
            Filtros
          </h2>
          <ul className="space-y-2.5 text-[15px] text-slate-700">
            {describirFiltros(busqueda.filtros).map((linea, i) => (
              <li key={i} className="flex gap-2.5">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-500" />
                <span>{linea}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>

      {/* Resultados */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="titulo-seccion">
              <span className="icono-seccion">
                <Building2 className="h-4 w-4" />
              </span>
              Empresas encontradas
              <span className="badge bg-brand-50 text-brand-700">{resultados.length}</span>
            </h2>
            {descartadas > 0 && (
              <Link href="/cola-revision" className="mt-1 inline-block text-sm text-slate-500 hover:text-brand-600 hover:underline">
                {descartadas} descartadas por no ser del sector — ver en la Cola de revisión
              </Link>
            )}
          </div>
          {resultados.length > 0 && (
            <button
              type="button"
              onClick={() => exportarResultadosCsv(resultados, busqueda.peticion)}
              className="btn-secondary"
            >
              <Download className="h-4 w-4" />
              Exportar CSV
            </button>
          )}
        </div>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="tabla-panel">
              <thead>
                <tr>
                  <th className="th-panel">Empresa</th>
                  <th className="th-panel">Contacto</th>
                  <th className="th-panel">Teléfono y email</th>
                  <th className="th-panel">Web</th>
                  <th className="th-panel">Confianza y fuente</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {resultados.map((r) => (
                  <tr key={r.empresa_id} className="group">
                    <td className="td-panel min-w-[220px]">
                      <Link
                        href={`/empresas/${r.empresa_id}?desde=${id}`}
                        className="font-semibold text-slate-900 transition group-hover:text-brand-700 hover:underline"
                      >
                        {r.razon_social}
                      </Link>
                      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                        {r.nif ? (
                          <span className="rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs font-semibold text-slate-700">
                            {r.nif}
                          </span>
                        ) : (
                          <span className="badge bg-amber-50 text-amber-700">sin NIF</span>
                        )}
                        {r.relevancia === "dudoso" && (
                          <span className="badge bg-slate-100 text-slate-600" title={r.motivo_relevancia ?? ""}>
                            ¿del sector?
                          </span>
                        )}
                        {r.sin_contrastar > 0 && (
                          <Link href="/duplicados" className="badge bg-amber-50 text-amber-700 hover:underline">
                            {r.sin_contrastar} sin contrastar
                          </Link>
                        )}
                        {r.en_revision > 0 && (
                          <Link href="/cola-revision" className="badge bg-sky-50 text-sky-700 hover:underline">
                            {r.en_revision} en revisión
                          </Link>
                        )}
                        {r.estado && r.estado !== "desconocida" && r.estado !== "desconocido" && (
                          <span className="badge bg-emerald-50 text-emerald-700">{r.estado}</span>
                        )}
                      </div>
                    </td>
                    <td className="td-panel min-w-[150px] max-w-[220px]">
                      {r.contacto ? (
                        <span className="flex items-start gap-2 text-slate-700">
                          <UserRound className="mt-0.5 h-4 w-4 shrink-0 text-violet-500" />
                          {r.contacto}
                        </span>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="td-panel">
                      <div className="space-y-1">
                        {r.telefono ? (
                          <a href={`tel:${r.telefono}`} className="flex items-center gap-2 whitespace-nowrap font-medium text-slate-800 hover:text-brand-700">
                            <Phone className="h-4 w-4 text-emerald-500" />
                            {r.telefono}
                          </a>
                        ) : null}
                        {r.email ? (
                          <a href={`mailto:${r.email}`} className="flex items-center gap-2 text-slate-600 hover:text-brand-700">
                            <Mail className="h-4 w-4 text-brand-400" />
                            <span className="max-w-[200px] truncate">{r.email}</span>
                          </a>
                        ) : null}
                        {!r.telefono && !r.email && <span className="text-slate-300">—</span>}
                      </div>
                    </td>
                    <td className="td-panel">
                      {r.dominio_web ? (
                        <a
                          href={`https://${r.dominio_web}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg bg-slate-50 px-2.5 py-1 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-200 transition hover:bg-brand-50 hover:text-brand-700 hover:ring-brand-200"
                        >
                          <Globe className="h-3.5 w-3.5" />
                          {r.dominio_web}
                        </a>
                      ) : (
                        <span className="text-slate-300">—</span>
                      )}
                    </td>
                    <td className="td-panel">
                      <BarraConfianza valor={r.confianza_global} />
                      <p className="mt-1 max-w-[180px] text-xs leading-snug text-slate-500">{etiquetaFuenteResultado(r.motivo)}</p>
                    </td>
                  </tr>
                ))}
                {resultados.length === 0 && (
                  <tr>
                    <td colSpan={5}>
                      <EstadoVacio icono={activa ? Radar : Building2}>
                        {activa
                          ? "El agente todavía no ha encontrado empresas. Irán apareciendo aquí en cuanto las encuentre."
                          : "No se encontraron empresas en esta búsqueda."}
                      </EstadoVacio>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}

// Barra corta de confianza (0–1) con color según el nivel.
function BarraConfianza({ valor }: { valor: number | null }) {
  if (valor == null) return <span className="text-slate-300">—</span>;
  const color = valor >= 0.8 ? "from-emerald-400 to-emerald-500" : valor >= 0.5 ? "from-brand-400 to-violet-500" : "from-amber-400 to-orange-500";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
        <div className={`h-full rounded-full bg-gradient-to-r ${color}`} style={{ width: `${Math.round(valor * 100)}%` }} />
      </div>
      <span className="text-sm font-semibold tabular-nums text-slate-700">{valor.toFixed(2)}</span>
    </div>
  );
}

// Icono de cada tipo de ronda en la línea de tiempo.
function iconoHerramienta(herramienta: string): LucideIcon {
  if (herramienta === "planificador_llm") return Brain;
  if (herramienta === "consultar_bd") return Database;
  if (herramienta === "estimar_cobertura") return PieChart;
  if (herramienta === "completar_contacto") return Phone;
  if (herramienta === "enriquecer_borme" || herramienta === "descubrir_borme") return Landmark;
  if (herramienta === "evaluar_relevancia") return Filter;
  if (herramienta === "resolver_dudas") return Sparkles;
  if (herramienta === "finalizar_busqueda") return Flag;
  if (herramienta === "preguntar_usuario") return HelpCircle;
  if (herramienta === "descubrir_apify_maps" || herramienta === "descubrir_places") return MapPinned;
  if (HERRAMIENTAS_DESCUBRIMIENTO.has(herramienta)) return Radar;
  return Activity;
}
