// Logo animado: una pantalla de radar con un haz que barre en círculo.
// Solo CSS (sin estado), así que sirve en componentes de servidor.

export function LogoRadar({ tamano = "md" }: { tamano?: "md" | "lg" }) {
  const caja = tamano === "lg" ? "h-14 w-14 rounded-2xl" : "h-10 w-10 rounded-xl";
  return (
    <span
      className={`relative flex shrink-0 items-center justify-center overflow-hidden bg-gradient-to-br from-brand-600 via-brand-500 to-violet-600 shadow-brillo ring-1 ring-white/20 ${caja}`}
    >
      {/* Anillos */}
      <span className="absolute inset-[18%] rounded-full border border-white/35" />
      <span className="absolute inset-[34%] rounded-full border border-white/25" />
      {/* Haz de barrido */}
      <span
        className="absolute inset-[10%] animate-barrido rounded-full"
        style={{ background: "conic-gradient(from 0deg, rgb(255 255 255 / 0.55), rgb(255 255 255 / 0) 28%)" }}
      />
      {/* Eco detectado */}
      <span className="absolute left-[64%] top-[30%] h-1.5 w-1.5 animate-latido rounded-full bg-cyan-200 text-cyan-200" />
      {/* Centro */}
      <span className="relative h-1.5 w-1.5 rounded-full bg-white" />
    </span>
  );
}
