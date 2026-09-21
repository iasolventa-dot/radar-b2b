"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowRight, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { confirmarBusqueda, estadoApify, estadoPlaces, interpretarBusqueda } from "@/lib/api";
import { describirFiltros } from "@/lib/filtros";
import type { BusquedaInterpretadaOut } from "@/lib/tipos";

type Estado = "formulario" | "interpretando" | "revision" | "confirmando";

const PRESUPUESTO_POR_DEFECTO_EUR = 20;
const MAX_RONDAS_POR_DEFECTO = 10;

export function FormularioNuevaBusqueda({
  usuarioId,
  peticionInicial,
  contextoInicial,
}: {
  usuarioId: string | null;
  peticionInicial?: string;
  contextoInicial?: string;
}) {
  const router = useRouter();

  const [estado, setEstado] = useState<Estado>("formulario");
  const [peticion, setPeticion] = useState(peticionInicial ?? "");
  const [contexto, setContexto] = useState(contextoInicial ?? "");
  const [presupuestoEur, setPresupuestoEur] = useState(PRESUPUESTO_POR_DEFECTO_EUR);
  const [maxRondas, setMaxRondas] = useState(MAX_RONDAS_POR_DEFECTO);
  const [interpretacion, setInterpretacion] = useState<BusquedaInterpretadaOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Fuentes de pago: solo se usan si se marcan aquí (y hay clave/token en Ajustes).
  const [usarPlaces, setUsarPlaces] = useState(false);
  const [usarApify, setUsarApify] = useState(false);
  const [placesConfigurado, setPlacesConfigurado] = useState<boolean | null>(null);
  const [apifyConfigurado, setApifyConfigurado] = useState<boolean | null>(null);

  useEffect(() => {
    estadoPlaces().then((e) => setPlacesConfigurado(e.configurada)).catch(() => setPlacesConfigurado(false));
    estadoApify().then((e) => setApifyConfigurado(e.configurado)).catch(() => setApifyConfigurado(false));
  }, []);

  async function interpretar(e: React.FormEvent) {
    e.preventDefault();
    if (!peticion.trim() || estado === "interpretando") return;
    setEstado("interpretando");
    setError(null);
    try {
      const resultado = await interpretarBusqueda(peticion.trim(), contexto.trim() || null, presupuestoEur, usuarioId);
      setInterpretacion(resultado);
      setEstado("revision");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setEstado("formulario");
    }
  }

  async function confirmar() {
    if (!interpretacion) return;
    setEstado("confirmando");
    setError(null);
    try {
      await confirmarBusqueda(interpretacion.id, {
        maxRondas,
        usarGooglePlaces: usarPlaces && placesConfigurado === true,
        usarApify: usarApify && apifyConfigurado === true,
      });
      router.push(`/busquedas/${interpretacion.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setEstado("revision");
    }
  }

  function empezarDeNuevo() {
    setInterpretacion(null);
    setEstado("formulario");
    setError(null);
  }

  const enRevision = estado === "revision" || estado === "confirmando";

  return (
    <div className="space-y-4">
      {!enRevision && (
        <form onSubmit={interpretar} className="card space-y-4 p-5">
          <div>
            <label htmlFor="peticion" className="label-field">
              ¿Qué empresas buscas?
            </label>
            <textarea
              id="peticion"
              required
              rows={3}
              placeholder="p. ej. constructoras de Sevilla capital de 10 a 50 empleados, activas"
              value={peticion}
              onChange={(e) => setPeticion(e.target.value)}
              className="input-field resize-none"
              disabled={estado === "interpretando"}
            />
          </div>

          <div>
            <label htmlFor="contexto" className="label-field">
              Contexto adicional (opcional)
            </label>
            <textarea
              id="contexto"
              rows={2}
              placeholder="cualquier matiz que ayude a interpretar mejor la petición"
              value={contexto}
              onChange={(e) => setContexto(e.target.value)}
              className="input-field resize-none"
              disabled={estado === "interpretando"}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="presupuesto" className="label-field">
                Presupuesto de esta búsqueda (€)
              </label>
              <input
                id="presupuesto"
                type="number"
                min={0.1}
                step={0.1}
                required
                value={presupuestoEur}
                onChange={(e) => setPresupuestoEur(Number(e.target.value))}
                className="input-field"
                disabled={estado === "interpretando"}
              />
            </div>
          </div>

          {error && (
            <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          <SelectorFuentes
            prefijo="ini"
            deshabilitado={estado === "interpretando"}
            usarPlaces={usarPlaces}
            setUsarPlaces={setUsarPlaces}
            placesConfigurado={placesConfigurado}
            usarApify={usarApify}
            setUsarApify={setUsarApify}
            apifyConfigurado={apifyConfigurado}
          />

          <button type="submit" disabled={estado === "interpretando" || !peticion.trim()} className="btn-primary">
            {estado === "interpretando" ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> Interpretando…
              </>
            ) : (
              <>
                <Sparkles className="h-4 w-4" /> Interpretar petición
              </>
            )}
          </button>
        </form>
      )}

      {enRevision && interpretacion && (
        <div className="card space-y-5 p-5">
          <div>
            <h2 className="text-sm font-semibold text-slate-700">Así ha entendido la petición</h2>
            <p className="mt-1 text-sm text-slate-500">
              &ldquo;{peticion.trim()}&rdquo;
              {contexto.trim() && <span className="text-slate-400"> — contexto: {contexto.trim()}</span>}
            </p>
          </div>

          <ul className="space-y-1.5 rounded-xl bg-slate-50 p-4 text-sm text-slate-700">
            {describirFiltros(interpretacion.filtros).map((linea, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-slate-400">•</span>
                {linea}
              </li>
            ))}
          </ul>

          {interpretacion.supuestos.length > 0 && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Supuestos que ha aplicado
              </h3>
              <ul className="space-y-1 text-sm text-slate-600">
                {interpretacion.supuestos.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="text-slate-400">•</span>
                    {s}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {interpretacion.preguntas.length > 0 && (
            <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
              <p className="mb-1 flex items-center gap-2 font-semibold">
                <AlertTriangle className="h-4 w-4 shrink-0" /> Antes de confirmar, quizá quieras aclarar
              </p>
              <ul className="space-y-1">
                {interpretacion.preguntas.map((p, i) => (
                  <li key={i}>• {p}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-amber-700">
                Puedes confirmar igualmente (el agente aplicará el supuesto más razonable) o volver atrás y
                añadir esto al contexto.
              </p>
            </div>
          )}

          <div className="max-w-[220px]">
            <label htmlFor="max_rondas" className="label-field">
              Máximo de rondas del agente
            </label>
            <input
              id="max_rondas"
              type="number"
              min={1}
              max={50}
              value={maxRondas}
              onChange={(e) => setMaxRondas(Number(e.target.value))}
              className="input-field"
              disabled={estado === "confirmando"}
            />
          </div>

          <SelectorFuentes
            prefijo="rev"
            deshabilitado={estado === "confirmando"}
            usarPlaces={usarPlaces}
            setUsarPlaces={setUsarPlaces}
            placesConfigurado={placesConfigurado}
            usarApify={usarApify}
            setUsarApify={setUsarApify}
            apifyConfigurado={apifyConfigurado}
          />

          {error && (
            <div className="flex items-start gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={confirmar} disabled={estado === "confirmando"} className="btn-primary">
              {estado === "confirmando" ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Lanzando búsqueda…
                </>
              ) : (
                <>
                  Confirmar y buscar <ArrowRight className="h-4 w-4" />
                </>
              )}
            </button>
            <button
              type="button"
              onClick={empezarDeNuevo}
              disabled={estado === "confirmando"}
              className="btn-secondary"
            >
              <RotateCcw className="h-4 w-4" /> Empezar de nuevo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FuenteDePago({
  id,
  titulo,
  descripcion,
  marcada,
  onCambio,
  configurada,
}: {
  id: string;
  titulo: string;
  descripcion: string;
  marcada: boolean;
  onCambio: (v: boolean) => void;
  configurada: boolean | null;
}) {
  const disponible = configurada === true;
  return (
    <label
      htmlFor={id}
      className={`flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm ${disponible ? "cursor-pointer" : "opacity-60"}`}
    >
      <input
        id={id}
        type="checkbox"
        className="mt-0.5 h-4 w-4"
        checked={marcada && disponible}
        disabled={!disponible}
        onChange={(e) => onCambio(e.target.checked)}
      />
      <span>
        <span className="font-medium text-slate-800">Incluir {titulo}</span>
        <span className="block text-xs text-slate-500">{descripcion}</span>
        {configurada === false && (
          <span className="block text-xs text-amber-700">
            No configurada: añade la clave en <a href="/ajustes" className="underline">Ajustes</a>.
          </span>
        )}
      </span>
    </label>
  );
}

function SelectorFuentes(props: {
  prefijo: string;
  deshabilitado: boolean;
  usarPlaces: boolean;
  setUsarPlaces: (v: boolean) => void;
  placesConfigurado: boolean | null;
  usarApify: boolean;
  setUsarApify: (v: boolean) => void;
  apifyConfigurado: boolean | null;
}) {
  return (
    <fieldset className="space-y-2" disabled={props.deshabilitado}>
      <legend className="label-field">Fuentes de pago para esta búsqueda</legend>
      <FuenteDePago
        id={`${props.prefijo}-usar-places`}
        titulo="Google Places"
        descripcion="Descubre negocios por zona y categoría (~0,035 € por página de 20)."
        marcada={props.usarPlaces}
        onCambio={props.setUsarPlaces}
        configurada={props.placesConfigurado}
      />
      <FuenteDePago
        id={`${props.prefijo}-usar-apify`}
        titulo="Apify"
        descripcion="Rastrea webs de empresa con JavaScript para enriquecerlas."
        marcada={props.usarApify}
        onCambio={props.setUsarApify}
        configurada={props.apifyConfigurado}
      />
    </fieldset>
  );
}
