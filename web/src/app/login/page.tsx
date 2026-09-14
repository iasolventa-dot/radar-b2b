"use client";

import { useState } from "react";
import { Radar, Mail, CheckCircle2 } from "lucide-react";
import { crearClienteNavegador } from "@/lib/supabase/client";

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
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-b from-slate-50 via-slate-50 to-slate-100 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-600 text-white shadow-md shadow-brand-600/20">
            <Radar className="h-6 w-6" strokeWidth={2.25} />
          </span>
          <h1 className="mt-4 text-lg font-semibold text-slate-900">Radar B2B</h1>
          <p className="mt-1 text-sm text-slate-500">
            Panel interno de búsqueda de empresas — Solventa IA
          </p>
        </div>

        <div className="card p-6">
          {estado === "enviado" ? (
            <div className="flex items-start gap-3 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
              <p>
                Te hemos enviado un enlace de acceso a <strong>{email}</strong>. Ábrelo desde el
                mismo navegador para entrar.
              </p>
            </div>
          ) : (
            <form onSubmit={enviarEnlace} className="space-y-4">
              <div>
                <label htmlFor="email" className="label-field">
                  Correo electrónico
                </label>
                <div className="relative">
                  <Mail className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <input
                    id="email"
                    type="email"
                    required
                    placeholder="tu@email.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="input-field pl-9"
                  />
                </div>
              </div>
              <button type="submit" disabled={estado === "enviando"} className="btn-primary w-full">
                {estado === "enviando" ? "Enviando…" : "Enviar enlace de acceso"}
              </button>
              {error && <p className="text-sm text-rose-600">{error}</p>}
            </form>
          )}
        </div>

        <p className="mt-6 text-center text-xs text-slate-400">
          Acceso restringido — solo usuarios invitados de Solventa IA.
        </p>
      </div>
    </div>
  );
}
