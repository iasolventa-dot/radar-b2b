import Link from "next/link";
import { Radar, LogOut } from "lucide-react";
import { crearClienteServidor } from "@/lib/supabase/server";
import { EnlacesNavegacion } from "@/components/nav-links";

export default async function LayoutApp({ children }: { children: React.ReactNode }) {
  const supabase = await crearClienteServidor();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const inicial = user?.email?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/85 backdrop-blur supports-backdrop-blur:bg-white/70">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <Link href="/" className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white shadow-sm">
                <Radar className="h-5 w-5" strokeWidth={2.25} />
              </span>
              <span className="leading-tight">
                <span className="block text-sm font-semibold text-slate-900">Radar B2B</span>
                <span className="block text-[11px] font-medium uppercase tracking-wide text-slate-400">
                  Solventa IA · uso interno
                </span>
              </span>
            </Link>
            <EnlacesNavegacion />
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 py-1 pl-1 pr-3 text-sm text-slate-600">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">
                {inicial}
              </span>
              <span className="max-w-[160px] truncate">{user?.email}</span>
            </div>
            <form action="/logout" method="post">
              <button
                type="submit"
                title="Cerrar sesión"
                className="flex items-center gap-1.5 rounded-lg px-2.5 py-2 text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
              >
                <LogOut className="h-4 w-4" />
                <span className="hidden sm:inline">Salir</span>
              </button>
            </form>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">{children}</main>
    </div>
  );
}
