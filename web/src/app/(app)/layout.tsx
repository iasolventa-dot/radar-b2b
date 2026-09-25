import Link from "next/link";
import { LogOut } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { EnlacesNavegacion, EnlacesNavegacionMovil } from "@/components/nav-links";
import { LogoRadar } from "@/components/logo-radar";

export default async function LayoutApp({ children }: { children: React.ReactNode }) {
  const supabase = await crearClienteServidor();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const inicial = user?.email?.[0]?.toUpperCase() ?? "?";

  const marca = (
    <Link href="/" className="flex items-center gap-3">
      <LogoRadar />
      <span className="leading-tight">
        <span className="block font-display text-lg font-extrabold tracking-tight text-white">Radar B2B</span>
        <span className="block text-[11px] font-semibold uppercase tracking-[0.18em] text-senal-400/90">
          Solventa IA · interno
        </span>
      </span>
    </Link>
  );

  const sesion = (
    <div className="flex items-center gap-2">
      <div className="flex min-w-0 flex-1 items-center gap-2.5 rounded-xl bg-white/[0.05] py-1.5 pl-1.5 pr-3 ring-1 ring-inset ring-white/[0.08]">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-senal-400 to-brand-500 text-sm font-bold text-white">
          {inicial}
        </span>
        <span className="truncate text-sm text-slate-300">{user?.email}</span>
      </div>
      <form action="/logout" method="post">
        <button
          type="submit"
          title="Cerrar sesión"
          className="flex h-11 w-11 items-center justify-center rounded-xl text-slate-400 ring-1 ring-inset ring-white/[0.08] transition hover:bg-rose-500/15 hover:text-rose-300"
        >
          <LogOut className="h-[18px] w-[18px]" />
          <span className="sr-only">Salir</span>
        </button>
      </form>
    </div>
  );

  return (
    <div className="fondo-panel flex min-h-screen">
      {/* Barra lateral (escritorio) */}
      <aside className="sticky top-0 hidden h-screen w-72 shrink-0 flex-col overflow-hidden bg-[var(--noche-900)] lg:flex">
        {/* Brillos de fondo de la barra */}
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(22rem_18rem_at_0%_0%,rgb(36_73_235/0.35),transparent_70%),radial-gradient(20rem_20rem_at_100%_100%,rgb(124_58_237/0.25),transparent_70%)]" />
        <div className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(rgb(255_255_255)_1px,transparent_1px)] [background-size:18px_18px]" />
        <div className="relative flex h-full flex-col gap-8 px-5 py-6">
          {marca}
          <div className="flex-1 overflow-y-auto pl-4 -ml-4">
            <p className="mb-3 px-3 text-[11px] font-bold uppercase tracking-[0.18em] text-slate-500">Panel</p>
            <EnlacesNavegacion />
          </div>
          {sesion}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Cabecera (móvil y tablet) */}
        <header className="sticky top-0 z-20 space-y-3 bg-[var(--noche-900)]/95 px-4 pb-3 pt-4 backdrop-blur-xl lg:hidden">
          <div className="flex items-center justify-between gap-3">
            {marca}
            <form action="/logout" method="post">
              <button
                type="submit"
                title="Cerrar sesión"
                className="flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 ring-1 ring-inset ring-white/10 hover:text-white"
              >
                <LogOut className="h-[18px] w-[18px]" />
                <span className="sr-only">Salir</span>
              </button>
            </form>
          </div>
          <EnlacesNavegacionMovil />
        </header>

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-8 lg:px-10 lg:py-10">{children}</main>
      </div>
    </div>
  );
}
