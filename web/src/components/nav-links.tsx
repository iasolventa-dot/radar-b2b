"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Copy, History, ListChecks, Search, Settings, ShieldCheck, type LucideIcon } from "lucide-react";

const ENLACES: { href: string; etiqueta: string; icono: LucideIcon; ayuda: string }[] = [
  { href: "/", etiqueta: "Nueva búsqueda", icono: Search, ayuda: "Describe lo que buscas" },
  { href: "/busquedas", etiqueta: "Búsquedas", icono: History, ayuda: "Historial y resultados" },
  { href: "/duplicados", etiqueta: "Datos sin contrastar", icono: Copy, ayuda: "Dudas que decides tú" },
  { href: "/cola-revision", etiqueta: "Cola de revisión", icono: ListChecks, ayuda: "Decisiones automáticas" },
  { href: "/entidades", etiqueta: "Golden set", icono: ShieldCheck, ayuda: "Entidades de referencia" },
  { href: "/ajustes", etiqueta: "Ajustes", icono: Settings, ayuda: "Claves y fuentes de pago" },
];

function esActivo(href: string, pathname: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

/** Navegación vertical de la barra lateral (escritorio). */
export function EnlacesNavegacion() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-1">
      {ENLACES.map(({ href, etiqueta, icono: Icono, ayuda }) => {
        const activo = esActivo(href, pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={activo ? "page" : undefined}
            className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 transition duration-200 ${
              activo
                ? "bg-gradient-to-r from-brand-500/25 via-violet-500/15 to-transparent text-white ring-1 ring-inset ring-white/10"
                : "text-slate-400 hover:bg-white/[0.06] hover:text-white"
            }`}
          >
            {activo && (
              <span className="absolute -left-4 top-1/2 h-7 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-senal-400 to-violet-500 shadow-[0_0_12px_2px_rgb(34_211_238/0.5)]" />
            )}
            <span
              className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition duration-200 ${
                activo
                  ? "bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-brillo"
                  : "bg-white/[0.04] text-slate-400 ring-1 ring-inset ring-white/[0.06] group-hover:text-white"
              }`}
            >
              <Icono className="h-[18px] w-[18px]" strokeWidth={2} />
            </span>
            <span className="min-w-0">
              <span className="block text-[15px] font-semibold leading-tight">{etiqueta}</span>
              <span className={`block truncate text-xs ${activo ? "text-brand-200" : "text-slate-500 group-hover:text-slate-400"}`}>
                {ayuda}
              </span>
            </span>
          </Link>
        );
      })}
    </nav>
  );
}

/** Navegación horizontal desplazable (móvil y tablet). */
export function EnlacesNavegacionMovil() {
  const pathname = usePathname();

  return (
    <nav className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
      {ENLACES.map(({ href, etiqueta, icono: Icono }) => {
        const activo = esActivo(href, pathname);
        return (
          <Link
            key={href}
            href={href}
            aria-current={activo ? "page" : undefined}
            className={`flex shrink-0 items-center gap-2 rounded-full px-3.5 py-2 text-sm font-semibold transition ${
              activo
                ? "bg-gradient-to-r from-brand-500 to-violet-600 text-white shadow-brillo"
                : "bg-white/[0.06] text-slate-300 hover:bg-white/10 hover:text-white"
            }`}
          >
            <Icono className="h-4 w-4" strokeWidth={2} />
            {etiqueta}
          </Link>
        );
      })}
    </nav>
  );
}
