import { NextResponse } from "next/server";
import { crearClienteServidor } from "@/lib/supabase/server";

// Supabase redirige aquí tras pulsar el enlace mágico del email, con un
// parámetro ?code=... que se intercambia por una sesión.
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");

  if (code) {
    const supabase = await crearClienteServidor();
    await supabase.auth.exchangeCodeForSession(code);
  }

  return NextResponse.redirect(`${origin}/`);
}
