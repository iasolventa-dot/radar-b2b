// Cliente de Supabase para componentes de navegador ("use client").
// Usa la clave "publishable" (segura de exponer) — nunca la "secret".
import { createBrowserClient } from "@supabase/ssr";

export function crearClienteNavegador() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}
