import type { LucideIcon } from "lucide-react";

// Cabecera común de todas las pantallas: icono en degradado, título grande
// con tipografía de titulares, descripción y acciones a la derecha.
export function EncabezadoPagina({
  icono: Icono,
  antetitulo,
  titulo,
  children,
  acciones,
}: {
  icono: LucideIcon;
  antetitulo?: string;
  titulo: React.ReactNode;
  children?: React.ReactNode;
  acciones?: React.ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-5">
      <div className="flex min-w-0 max-w-3xl items-start gap-4">
        <span className="relative mt-1 flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-600 via-brand-500 to-violet-600 text-white shadow-brillo ring-1 ring-white/20">
          <Icono className="h-6 w-6" strokeWidth={2} />
        </span>
        <div className="min-w-0">
          {antetitulo && (
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.16em] text-brand-600">{antetitulo}</p>
          )}
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-slate-900">{titulo}</h1>
          {children && <div className="mt-2 space-y-1.5 text-base leading-relaxed text-slate-600">{children}</div>}
        </div>
      </div>
      {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
    </header>
  );
}

const TONOS = {
  marca: "from-brand-500 to-violet-600 shadow-brillo",
  verde: "from-emerald-400 to-teal-600 shadow-[0_8px_24px_-6px_rgb(16_185_129/0.5)]",
  ambar: "from-amber-400 to-orange-500 shadow-[0_8px_24px_-6px_rgb(245_158_11/0.5)]",
  cian: "from-senal-400 to-sky-600 shadow-[0_8px_24px_-6px_rgb(6_182_212/0.5)]",
} as const;

// Tarjeta de cifra clave (estilo "bento"): icono de color, etiqueta y valor grande.
export function TarjetaCifra({
  icono: Icono,
  etiqueta,
  valor,
  detalle,
  tono = "marca",
  children,
}: {
  icono: LucideIcon;
  etiqueta: string;
  valor: React.ReactNode;
  detalle?: React.ReactNode;
  tono?: keyof typeof TONOS;
  children?: React.ReactNode;
}) {
  return (
    <div className="card group relative overflow-hidden p-5 transition duration-300 hover:-translate-y-0.5 hover:shadow-elevada">
      <div className="pointer-events-none absolute -right-10 -top-10 h-32 w-32 rounded-full bg-gradient-to-br from-brand-100/60 to-violet-100/40 blur-2xl transition-opacity duration-300 group-hover:opacity-100 opacity-60" />
      <div className="relative flex items-start gap-4">
        <span className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br text-white ${TONOS[tono]}`}>
          <Icono className="h-5 w-5" strokeWidth={2.2} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-500">{etiqueta}</p>
          <p className="mt-0.5 font-display text-2xl font-extrabold tracking-tight text-slate-900 tabular-nums">{valor}</p>
          {detalle && <p className="mt-0.5 text-xs text-slate-500">{detalle}</p>}
          {children}
        </div>
      </div>
    </div>
  );
}

// Estado vacío con icono en círculo y texto.
export function EstadoVacio({ icono: Icono, children }: { icono: LucideIcon; children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-14 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-50 to-violet-50 text-brand-500 ring-1 ring-brand-100">
        <Icono className="h-7 w-7" strokeWidth={1.75} />
      </span>
      <p className="max-w-md text-base text-slate-500">{children}</p>
    </div>
  );
}
