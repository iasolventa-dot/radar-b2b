"use client";

import { useState } from "react";
import { Mail, CheckCircle2, Loader2, ArrowRight } from "lucide-react";
import { crearClienteNavegador } from "@/lib/supabase/client";
import { LogoRadar } from "@/components/logo-radar";

export default function PaginaLogin() {
  const [email, setEmail] = useState("");
  const [estado, setEstado] = useState<"reposo" | "enviando" | "enviado" | "error">("reposo");
  const [error, setError] = useState<string | null>(null);

  async function enviarEnlace(e: React.FormEvent) {
    e.preventDefault();
    setEstado("enviando");
    setError(null);

    const supabase = crearClienteNavegador();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setEstado("error");
      setError(error.message);
      return;
    }
    setEstado("enviado");
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[var(--noche-900)] px-4">
      {/* Fondo: brillos de color, retícula de puntos y anillos de radar */}
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(40rem_30rem_at_20%_10%,rgb(36_73_235/0.35),transparent_70%),radial-gradient(36rem_28rem_at_90%_90%,rgb(124_58_237/0.30),transparent_70%)]" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.07] [background-image:radial-gradient(rgb(255_255_255)_1px,transparent_1px)] [background-size:22px_22px]" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[46rem] w-[46rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/[0.05]" />
      <div className="pointer-events-none absolute left-1/2 top-1/2 h-[32rem] w-[32rem] -translate-x-1/2 -translate-y-1/2 rounded-full border border-white/[0.06]" />
      <div
        className="pointer-events-none absolute left-1/2 top-1/2 h-[46rem] w-[46rem] -translate-x-1/2 -translate-y-1/2 animate-barrido rounded-full opacity-60"
        style={{ background: "conic-gradient(from 0deg, rgb(34 211 238 / 0.14), transparent 18%)", animationDuration: "7s" }}
      />

      <div className="entrada relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <LogoRadar tamano="lg" />
          <h1 className="mt-5 font-display text-3xl font-extrabold tracking-tight text-white">Radar B2B</h1>
          <p className="mt-2 text-base text-slate-400">Panel interno de búsqueda de empresas · Solventa IA</p>
        </div>

        <div className="rounded-3xl bg-white/[0.06] p-px shadow-2xl ring-1 ring-white/10 backdrop-blur-xl">
          <div className="rounded-[1.45rem] bg-white p-7">
            {estado === "enviado" ? (
              <div className="aviso-ok">
                <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
                <p>
                  Te hemos enviado un enlace de acceso a <strong>{email}</strong>. Ábrelo desde el mismo navegador
                  para entrar.
                </p>
              </div>
            ) : (
              <form onSubmit={enviarEnlace} className="space-y-5">
                <div>
                  <label htmlFor="email" className="label-field">
                    Correo electrónico
                  </label>
                  <div className="relative">
                    <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
                    <input
                      id="email"
                      type="email"
                      required
                      placeholder="tu@email.com"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="input-field pl-11"
                    />
                  </div>
                </div>
                <button type="submit" disabled={estado === "enviando"} className="btn-primary w-full py-3 text-base">
                  {estado === "enviando" ? (
                    <>
                      <Loader2 className="h-5 w-5 animate-spin" /> Enviando…
                    </>
                  ) : (
                    <>
                      Enviar enlace de acceso <ArrowRight className="h-5 w-5" />
                    </>
                  )}
                </button>
                {error && <p className="text-sm text-rose-600">{error}</p>}
              </form>
            )}
          </div>
        </div>

        <p className="mt-6 text-center text-sm text-slate-500">Acceso restringido — solo usuarios invitados de Solventa IA.</p>
      </div>
    </div>
  );
}
