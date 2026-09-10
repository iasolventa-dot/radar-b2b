// Cliente de Supabase para Server Components, Server Actions y Route Handlers.
// Lee/escribe la sesión desde las cookies de la petición. Sigue usando solo la
// clave "publishable" — la autorización real la hace RLS en Postgres (ver
// supabase/migrations/202609102000_golden_set_revision.sql), no esta clave.
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function crearClienteServidor() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // se llama desde un Server Component sin permiso de escritura;
            // el middleware ya se encarga de refrescar la sesión en ese caso.
          }
        },
      },
    }
  );
}
