"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowLeft, Ban, CheckCircle2, Clock3, Euro, HelpCircle, Loader2, RotateCw } from "lucide-react";
import { crearClienteNavegador } from "@/lib/supabase/client";
import { cancelarBusqueda, confirmarBusqueda } from "@/lib/api";
import { describirFiltros } from "@/lib/filtros";
import {
  COLOR_ESTADO_BUSQUEDA,
  ETIQUETA_CARGO,
  ETIQUETA_ESTADO_BUSQUEDA,
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
}

function resumenRonda(ronda: RondaEstadistica): string {
  const r = ronda.resultado as Record<string, unknown>;
  if (ronda.herramienta === "consultar_bd") return `${r.total ?? 0} empresas en la BD que cumplen los filtros`;
  if (ronda.herramienta === "descubrir_borme" || ronda.herramienta === "buscar_web") {
    const partes: string[] = [];
    if (typeof r.nueva_empresa === "number" && r.nueva_empresa) partes.push(`${r.nueva_empresa} nuevas`);
    if (typeof r.vinculado === "number" && r.vinculado) partes.push(`${r.vinculado} vinculadas`);
    if (typeof r.en_revision === "number" && r.en_revision) partes.push(`${r.en_revision} en revisión`);
    const errores = (typeof r.error === "number" ? r.error : 0) + (typeof r.error_procesado === "number" ? r.error_procesado : 0);
    if (errores) partes.push(`${errores} con error`);
    return partes.length ? partes.join(", ") : "sin resultados nuevos";
  }
  if (ronda.herramienta === "preguntar_usuario") return String(r.pregunta ?? "");
  if (ronda.herramienta === "finalizar_busqueda") return String(r.resumen ?? "");
  return "";
}

export function ProgresoBusqueda({ id, inicial }: { id: string; inicial: BusquedaFila }) {
  const [busqueda, setBusqueda] = useState<BusquedaFila>(inicial);
  const [resultados, setResultados] = useState<EmpresaResultado[]>([]);
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
        .select("empresa_id, motivo, empresas(razon_social, nif, estado, confianza_global, dominio_web)")
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
      if (cancelado) return;

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

      setResultados(
        filas.map((f: Record<string, unknown>) => {
          type Empresa = {
            razon_social: string; nif: string | null; estado: string | null;
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
            razon_social: empresa?.razon_social ?? "(sin nombre)",
            nif: empresa?.nif ?? null,
            estado: empresa?.estado ?? null,
            confianza_global: empresa?.confianza_global ?? null,
            dominio_web: empresa?.dominio_web ?? null,
            telefono: telefono?.valor ?? null,
            email: email?.valor ?? null,
            contacto,
          };
        })
      );
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

  return (
    <div className="space-y-6">
      <div>
        <Link href="/busquedas" className="mb-2 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
          <ArrowLeft className="h-3.5 w-3.5" /> Búsquedas
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">{busqueda.peticion}</h1>
            <p className="mt-1 text-sm text-slate-500">
              Lanzada el {new Date(busqueda.creado_en).toLocaleString("es-ES")}
              {busqueda.finalizado_en && ` · terminada el ${new Date(busqueda.finalizado_en).toLocaleString("es-ES")}`}
            </p>
          </div>
          <span className={`badge shrink-0 ${COLOR_ESTADO_BUSQUEDA[busqueda.estado] ?? "bg-slate-100 text-slate-600"}`}>
            {activa && <Loader2 className="mr-1 -ml-0.5 inline h-3 w-3 animate-spin" />}
            {ETIQUETA_ESTADO_BUSQUEDA[busqueda.estado] ?? busqueda.estado}
          </span>
        </div>
        {ESTADOS_CANCELABLES.has(busqueda.estado) && (
          <div className="mt-2 flex items-center gap-3">
            <button type="button" onClick={cancelar} disabled={cancelando} className="btn-secondary">
              {cancelando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Ban className="h-4 w-4" />}
              Cancelar búsqueda
            </button>
            {errorCancelar && <p className="text-sm text-rose-600">{errorCancelar}</p>}
          </div>
        )}
      </div>

      {busqueda.estado === "interpretada" && (
        <div className="card flex flex-wrap items-center justify-between gap-3 border-amber-200 bg-amber-50/40 p-4">
          <p className="text-sm text-amber-800">Esta búsqueda todavía no se ha confirmado.</p>
          <div className="flex items-center gap-3">
            {errorConfirmar && <p className="text-sm text-rose-600">{errorConfirmar}</p>}
            <button type="button" onClick={confirmar} disabled={confirmando} className="btn-primary">
              {confirmando ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCw className="h-4 w-4" />}
              Confirmar y buscar
            </button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="card flex items-center gap-3 px-4 py-3">
          <Clock3 className="h-4 w-4 text-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Rondas</p>
            <p className="text-sm font-semibold text-slate-800">
              {busqueda.rondas} / {busqueda.estadisticas?.max_rondas ?? "—"}
            </p>
          </div>
        </div>
        <div className="card flex items-center gap-3 px-4 py-3">
          <Euro className="h-4 w-4 text-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Coste</p>
            <p className="text-sm font-semibold text-slate-800">
              {busqueda.coste_eur.toFixed(2)} €{" "}
              {busqueda.presupuesto_eur != null && `/ ${Number(busqueda.presupuesto_eur).toFixed(2)} €`}
            </p>
          </div>
        </div>
        <div className="card flex items-center gap-3 px-4 py-3">
          <CheckCircle2 className="h-4 w-4 text-slate-400" />
          <div>
            <p className="text-xs text-slate-500">Empresas encontradas</p>
            <p className="text-sm font-semibold text-slate-800">{resultados.length}</p>
          </div>
        </div>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Filtros</h2>
        <ul className="card space-y-1.5 p-4 text-sm text-slate-600">
          {describirFiltros(busqueda.filtros).map((linea, i) => (
            <li key={i} className="flex gap-2">
              <span className="text-slate-400">•</span>
              {linea}
            </li>
          ))}
        </ul>
      </div>

      {busqueda.estadisticas?.pregunta && (
        <div className="card flex items-start gap-3 border-amber-200 bg-amber-50/40 p-4 text-sm text-amber-800">
          <HelpCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">El agente tiene una pregunta:</p>
            <p className="mt-0.5">{busqueda.estadisticas.pregunta.pregunta}</p>
            {busqueda.estadisticas.pregunta.opciones.length > 0 && (
              <p className="mt-1 text-xs text-amber-700">
                Opciones: {busqueda.estadisticas.pregunta.opciones.join(" / ")}
              </p>
            )}
            <p className="mt-2 text-xs text-amber-700">
              El planificador se ha detenido aquí — este primer agente todavía no es interactivo. Lanza una
              nueva búsqueda añadiendo la respuesta como contexto.
            </p>
          </div>
        </div>
      )}

      {busqueda.estado === "error" && (
        <div className="card flex items-start gap-3 border-rose-200 bg-rose-50/40 p-4 text-sm text-rose-800">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">La búsqueda terminó con un error</p>
            <p className="mt-0.5">{busqueda.estadisticas?.error ?? "sin detalle"}</p>
          </div>
        </div>
      )}

      {busqueda.estado === "completada" && busqueda.estadisticas?.resumen && (
        <div className="card flex items-start gap-3 border-emerald-200 bg-emerald-50/40 p-4 text-sm text-emerald-800">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Búsqueda terminada — {busqueda.estadisticas.motivo_fin}</p>
            <p className="mt-0.5">{busqueda.estadisticas.resumen}</p>
          </div>
        </div>
      )}

      {rondas.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-semibold text-slate-700">Progreso ronda a ronda</h2>
          <ol className="card divide-y divide-slate-100">
            {rondas.map((ronda) => (
              <li key={ronda.numero} className="flex items-start gap-3 px-4 py-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold text-slate-500">
                  {ronda.numero}
                </span>
                <div>
                  <p className="text-sm font-medium text-slate-800">
                    {ETIQUETA_HERRAMIENTA[ronda.herramienta] ?? ronda.herramienta}
                  </p>
                  <p className="mt-0.5 text-sm text-slate-500">{resumenRonda(ronda)}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Empresas encontradas</h2>
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="th-panel">Razón social</th>
                  <th className="th-panel">NIF</th>
                  <th className="th-panel">Contacto</th>
                  <th className="th-panel">Teléfono</th>
                  <th className="th-panel">Email</th>
                  <th className="th-panel">Web</th>
                  <th className="th-panel">Estado</th>
                  <th className="th-panel">Confianza</th>
                  <th className="th-panel">Fuente</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {resultados.map((r) => (
                  <tr key={r.empresa_id} className="transition-colors hover:bg-slate-50/70">
                    <td className="px-4 py-3 font-medium text-slate-800">{r.razon_social}</td>
                    <td className="px-4 py-3">
                      {r.nif ? (
                        <span className="font-mono text-slate-700">{r.nif}</span>
                      ) : (
                        <span className="badge bg-amber-100 text-amber-800">sin NIF</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{r.contacto ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {r.telefono ? <a href={`tel:${r.telefono}`} className="hover:text-brand-600">{r.telefono}</a> : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {r.email ? (
                        <a href={`mailto:${r.email}`} className="hover:text-brand-600">{r.email}</a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {r.dominio_web ? (
                        <a
                          href={`https://${r.dominio_web}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-brand-600"
                        >
                          {r.dominio_web}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{r.estado ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {r.confianza_global != null ? r.confianza_global.toFixed(2) : "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-400">{etiquetaFuenteResultado(r.motivo)}</td>
                  </tr>
                ))}
                {resultados.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-14 text-center text-sm text-slate-400">
                      {activa
                        ? "El agente todavía no ha encontrado empresas."
                        : "No se encontraron empresas en esta búsqueda."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
