"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  Briefcase,
  Check,
  CheckCircle2,
  Coins,
  Euro,
  Globe,
  Lightbulb,
  Loader2,
  MapPin,
  MapPinned,
  RotateCcw,
  Search,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";
import { confirmarBusqueda, estadoApify, estadoPlaces, interpretarBusqueda } from "@/lib/api";
import { describirFiltros } from "@/lib/filtros";
import type { ApifyActor, BusquedaInterpretadaOut } from "@/lib/tipos";

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
  // Apify tiene varios Actors independientes (uno por checkbox); "web_crawler",
  // "google_search", "google_maps", "linkedin", "facebook" -- ver ApifyActor en tipos.ts.
  const [usarPlaces, setUsarPlaces] = useState(false);
  const [apifyActores, setApifyActores] = useState<Set<ApifyActor>>(new Set());
  const [placesConfigurado, setPlacesConfigurado] = useState<boolean | null>(null);
  const [apifyConfigurado, setApifyConfigurado] = useState<boolean | null>(null);

  function alternarApifyActor(actor: ApifyActor, marcado: boolean) {
    setApifyActores((prev) => {
      const siguiente = new Set(prev);
      if (marcado) siguiente.add(actor);
      else siguiente.delete(actor);
      return siguiente;
    });
  }

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
        apifyActores: apifyConfigurado === true ? Array.from(apifyActores) : [],
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
    <div className="space-y-6">
      <Pasos actual={enRevision ? 2 : 1} />

      {!enRevision && (
        <form onSubmit={interpretar} className="space-y-6">
          <div className="rounded-[1.35rem] bg-gradient-to-br from-brand-400/60 via-violet-400/40 to-senal-400/50 p-px shadow-elevada">
            <div className="rounded-[1.3rem] bg-white p-6 sm:p-7">
              <label htmlFor="peticion" className="flex items-center gap-2 font-display text-lg font-bold text-slate-900">
                <Sparkles className="h-5 w-5 text-violet-500" />
                ¿Qué empresas buscas?
              </label>
              <textarea
                id="peticion"
                required
                rows={3}
                placeholder="p. ej. constructoras de Sevilla capital de 10 a 50 empleados, activas"
                value={peticion}
                onChange={(e) => setPeticion(e.target.value)}
                className="mt-3 w-full resize-none rounded-xl border-0 bg-slate-50 px-4 py-3.5 text-lg leading-relaxed text-slate-900 outline-none ring-1 ring-inset ring-slate-200 transition placeholder:text-slate-400 focus:bg-white focus:ring-2 focus:ring-brand-400"
                disabled={estado === "interpretando"}
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Ejemplos</span>
                {EJEMPLOS.map((ejemplo) => (
                  <button
                    key={ejemplo}
                    type="button"
                    onClick={() => setPeticion(ejemplo)}
                    disabled={estado === "interpretando"}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1 text-sm text-slate-600 transition hover:-translate-y-px hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
                  >
                    {ejemplo}
                  </button>
                ))}
              </div>

              <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-[1fr_240px]">
                <div>
                  <label htmlFor="contexto" className="label-field">
                    Contexto adicional <span className="font-normal text-slate-400">(opcional)</span>
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
                <div>
                  <label htmlFor="presupuesto" className="label-field">
                    Presupuesto de esta búsqueda
                  </label>
                  <div className="relative">
                    <input
                      id="presupuesto"
                      type="number"
                      min={0.1}
                      step={0.1}
                      required
                      value={presupuestoEur}
                      onChange={(e) => setPresupuestoEur(Number(e.target.value))}
                      className="input-field pr-10 font-display text-lg font-bold tabular-nums"
                      disabled={estado === "interpretando"}
                    />
                    <Euro className="pointer-events-none absolute right-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                  </div>
                  <p className="mt-1.5 text-xs text-slate-500">Tope de gasto: el agente para al llegar.</p>
                </div>
              </div>
            </div>
          </div>

          <SelectorFuentes
            prefijo="ini"
            deshabilitado={estado === "interpretando"}
            usarPlaces={usarPlaces}
            setUsarPlaces={setUsarPlaces}
            placesConfigurado={placesConfigurado}
            apifyActores={apifyActores}
            alternarApifyActor={alternarApifyActor}
            apifyConfigurado={apifyConfigurado}
          />

          {error && (
            <div className="aviso-error">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-4">
            <button
              type="submit"
              disabled={estado === "interpretando" || !peticion.trim()}
              className="btn-primary px-7 py-3.5 text-base"
            >
              {estado === "interpretando" ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin" /> Interpretando…
                  <span className="destello" />
                </>
              ) : (
                <>
                  <Sparkles className="h-5 w-5" /> Interpretar petición
                </>
              )}
            </button>
            <p className="text-sm text-slate-500">Aún no se gasta nada: primero verás cómo lo ha entendido.</p>
          </div>
        </form>
      )}

      {enRevision && interpretacion && (
        <div className="space-y-6">
          <div className="card overflow-hidden">
            <div className="border-b border-slate-100 bg-gradient-to-r from-brand-50 via-violet-50/60 to-white px-6 py-5">
              <p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-brand-600">
                <Sparkles className="h-4 w-4" /> Así ha entendido la petición
              </p>
              <blockquote className="mt-2 font-display text-xl font-bold text-slate-900">
                &ldquo;{peticion.trim()}&rdquo;
              </blockquote>
              {contexto.trim() && <p className="mt-1 text-sm text-slate-500">Contexto: {contexto.trim()}</p>}
            </div>

            <div className="space-y-6 p-6">
              <ul className="grid grid-cols-1 gap-2.5 md:grid-cols-2">
                {describirFiltros(interpretacion.filtros).map((linea, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-3 rounded-xl bg-slate-50 px-4 py-3 text-[15px] text-slate-700 ring-1 ring-inset ring-slate-100"
                  >
                    <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
                    <span>{linea}</span>
                  </li>
                ))}
              </ul>

              {interpretacion.supuestos.length > 0 && (
                <div>
                  <h3 className="mb-2 flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-slate-500">
                    <Lightbulb className="h-4 w-4 text-amber-500" /> Supuestos que ha aplicado
                  </h3>
                  <ul className="space-y-2 text-[15px] text-slate-600">
                    {interpretacion.supuestos.map((s, i) => (
                      <li key={i} className="flex gap-3">
                        <span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-400" />
                        {s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {interpretacion.preguntas.length > 0 && (
                <div className="aviso-atencion">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
                  <div>
                    <p className="mb-1 font-semibold">Antes de confirmar, quizá quieras aclarar</p>
                    <ul className="space-y-1">
                      {interpretacion.preguntas.map((p, i) => (
                        <li key={i}>• {p}</li>
                      ))}
                    </ul>
                    <p className="mt-2 text-sm text-amber-800/80">
                      Puedes confirmar igualmente (el agente aplicará el supuesto más razonable) o volver atrás y
                      añadir esto al contexto.
                    </p>
                  </div>
                </div>
              )}

              <div className="max-w-[240px]">
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
                  className="input-field font-display text-lg font-bold tabular-nums"
                  disabled={estado === "confirmando"}
                />
              </div>
            </div>
          </div>

          <SelectorFuentes
            prefijo="rev"
            deshabilitado={estado === "confirmando"}
            usarPlaces={usarPlaces}
            setUsarPlaces={setUsarPlaces}
            placesConfigurado={placesConfigurado}
            apifyActores={apifyActores}
            alternarApifyActor={alternarApifyActor}
            apifyConfigurado={apifyConfigurado}
          />

          {error && (
            <div className="aviso-error">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
              <p>{error}</p>
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={confirmar}
              disabled={estado === "confirmando"}
              className="btn-primary px-7 py-3.5 text-base"
            >
              {estado === "confirmando" ? (
                <>
                  <Loader2 className="h-5 w-5 animate-spin" /> Lanzando búsqueda…
                  <span className="destello" />
                </>
              ) : (
                <>
                  Confirmar y buscar <ArrowRight className="h-5 w-5" />
                </>
              )}
            </button>
            <button
              type="button"
              onClick={empezarDeNuevo}
              disabled={estado === "confirmando"}
              className="btn-secondary px-5 py-3.5 text-base"
            >
              <RotateCcw className="h-5 w-5" /> Empezar de nuevo
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const EJEMPLOS = [
  "constructoras de Sevilla de 10 a 50 empleados",
  "instaladores eléctricos en Getafe",
  "empresas de reformas en Alcobendas",
];

// Indicador de los tres pasos del flujo: describir → revisar → buscar.
function Pasos({ actual }: { actual: 1 | 2 }) {
  const pasos = ["Describe", "Revisa cómo lo ha entendido", "El agente busca"];
  return (
    <ol className="flex flex-wrap items-center gap-2 text-sm">
      {pasos.map((paso, i) => {
        const n = i + 1;
        const hecho = n < actual;
        const activo = n === actual;
        return (
          <li key={paso} className="flex items-center gap-2">
            <span
              className={`flex items-center gap-2 rounded-full py-1 pl-1 pr-3 font-semibold transition ${
                activo
                  ? "bg-white text-slate-900 shadow-suave ring-1 ring-brand-200"
                  : hecho
                    ? "text-emerald-700"
                    : "text-slate-400"
              }`}
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
                  activo
                    ? "bg-gradient-to-br from-brand-500 to-violet-600 text-white"
                    : hecho
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-slate-200/70 text-slate-500"
                }`}
              >
                {hecho ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : n}
              </span>
              {paso}
            </span>
            {n < pasos.length && <span className="h-px w-6 bg-slate-300" />}
          </li>
        );
      })}
    </ol>
  );
}

function FuenteDePago({
  id,
  titulo,
  descripcion,
  icono: Icono,
  marcada,
  onCambio,
  configurada,
}: {
  id: string;
  titulo: string;
  descripcion: string;
  icono: LucideIcon;
  marcada: boolean;
  onCambio: (v: boolean) => void;
  configurada: boolean | null;
}) {
  const disponible = configurada === true;
  const activa = marcada && disponible;
  return (
    <label
      htmlFor={id}
      className={`group relative flex items-start gap-3.5 rounded-2xl border p-4 transition duration-200 ${
        activa
          ? "border-brand-300 bg-gradient-to-br from-brand-50 via-white to-violet-50 shadow-elevada ring-1 ring-brand-200"
          : "border-slate-200 bg-white shadow-sm"
      } ${disponible ? "cursor-pointer hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-suave" : "cursor-not-allowed opacity-60"}`}
    >
      <input
        id={id}
        type="checkbox"
        className="peer sr-only"
        checked={activa}
        disabled={!disponible}
        onChange={(e) => onCambio(e.target.checked)}
      />
      <span
        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition ${
          activa
            ? "bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-brillo"
            : "bg-slate-100 text-slate-500 group-hover:text-brand-600"
        }`}
      >
        <Icono className="h-5 w-5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-slate-900">{titulo}</span>
        <span className="mt-0.5 block text-sm leading-snug text-slate-500">{descripcion}</span>
        {configurada === false && (
          <span className="mt-1 block text-sm font-medium text-amber-700">
            No configurada: añade la clave en{" "}
            <a href="/ajustes" className="underline">
              Ajustes
            </a>
            .
          </span>
        )}
      </span>
      {/* Casilla visual: la real está oculta (sr-only) pero sigue siendo accesible con teclado */}
      <span
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-lg border-2 transition peer-focus-visible:ring-4 peer-focus-visible:ring-brand-200 ${
          activa
            ? "border-transparent bg-gradient-to-br from-brand-500 to-violet-600 text-white"
            : "border-slate-300 bg-white text-transparent"
        }`}
      >
        <Check className="h-4 w-4" strokeWidth={3} />
      </span>
    </label>
  );
}

const ACTORS_APIFY: { actor: ApifyActor; titulo: string; descripcion: string; icono: LucideIcon }[] = [
  {
    actor: "google_maps",
    titulo: "Apify · Google Maps",
    descripcion: "Descubre negocios por zona y categoría (scraping, no la API oficial de Google).",
    icono: MapPinned,
  },
  {
    actor: "google_search",
    titulo: "Apify · búsqueda en Google",
    descripcion: "Alternativa a la búsqueda web con más control (paginación, país).",
    icono: Search,
  },
  {
    actor: "web_crawler",
    titulo: "Apify · rastreo de webs",
    descripcion: "Rastrea webs de empresa con JavaScript, para las que buscar_web no lee bien.",
    icono: Globe,
  },
  {
    actor: "linkedin",
    titulo: "Apify · LinkedIn",
    descripcion: "Busca la página de empresa en LinkedIn por nombre y extrae sus datos públicos.",
    icono: Briefcase,
  },
  {
    actor: "facebook",
    titulo: "Apify · Facebook",
    descripcion: "Lee páginas de empresa de Facebook (dirección, teléfono, email, web).",
    icono: Users,
  },
];

function SelectorFuentes(props: {
  prefijo: string;
  deshabilitado: boolean;
  usarPlaces: boolean;
  setUsarPlaces: (v: boolean) => void;
  placesConfigurado: boolean | null;
  apifyActores: Set<ApifyActor>;
  alternarApifyActor: (actor: ApifyActor, marcado: boolean) => void;
  apifyConfigurado: boolean | null;
}) {
  const marcadas =
    (props.usarPlaces && props.placesConfigurado ? 1 : 0) + (props.apifyConfigurado ? props.apifyActores.size : 0);
  return (
    <fieldset className="card space-y-4 p-6" disabled={props.deshabilitado}>
      <legend className="sr-only">Fuentes de pago para esta búsqueda</legend>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="titulo-seccion">
            <span className="icono-seccion">
              <Coins className="h-4 w-4" />
            </span>
            Fuentes de pago
          </h3>
          <p className="mt-1 text-sm text-slate-500">
            Opcionales. Las fuentes gratuitas (BORME, webs, OpenStreetMap) se usan siempre.
          </p>
        </div>
        <span className={`badge ${marcadas ? "bg-brand-50 text-brand-700" : "bg-slate-100 text-slate-500"}`}>
          {marcadas ? `${marcadas} activada${marcadas > 1 ? "s" : ""}` : "ninguna activada"}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <FuenteDePago
          id={`${props.prefijo}-usar-places`}
          titulo="Google Places"
          descripcion="Descubre negocios por zona y categoría (~0,035 € por página de 20)."
          icono={MapPin}
          marcada={props.usarPlaces}
          onCambio={props.setUsarPlaces}
          configurada={props.placesConfigurado}
        />
        {ACTORS_APIFY.map(({ actor, titulo, descripcion, icono }) => (
          <FuenteDePago
            key={actor}
            id={`${props.prefijo}-apify-${actor}`}
            titulo={titulo}
            descripcion={descripcion}
            icono={icono}
            marcada={props.apifyActores.has(actor)}
            onCambio={(v) => props.alternarApifyActor(actor, v)}
            configurada={props.apifyConfigurado}
          />
        ))}
      </div>
    </fieldset>
  );
}
