"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Copy, History, ListChecks, Search, Settings, ShieldCheck, type LucideIcon } from "lucide-react";

const ENLACES: { href: string; etiqueta: string; icono: LucideIcon }[] = [
  { href: "/", etiqueta: "Nueva búsqueda", icono: Search },
  { href: "/busquedas", etiqueta: "Búsquedas", icono: History },
  { href: "/duplicados", etiqueta: "Posibles duplicados", icono: Copy },
  { href: "/revision", etiqueta: "Cola de revisión", icono: ListChecks },
  { href: "/entidades", etiqueta: "Golden set", icono: ShieldCheck },
  { href: "/ajustes", etiqueta: "Ajustes", icono: Settings },
];

export function EnlacesNavegacion() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-wrap items-center gap-1">
      {ENLACES.map(({ href, etiqueta, icono: Icono }) => {
        const activo = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={activo ? "page" : undefined}
            className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              activo
                ? "bg-brand-50 text-brand-700"
                : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
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
