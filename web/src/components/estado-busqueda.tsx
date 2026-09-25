import { COLOR_ESTADO_BUSQUEDA, ETIQUETA_ESTADO_BUSQUEDA } from "@/lib/tipos";

// Insignia de estado de una búsqueda; el punto late mientras está en curso.
export function EstadoBusqueda({ estado }: { estado: string }) {
  return (
    <span className={`badge whitespace-nowrap ${COLOR_ESTADO_BUSQUEDA[estado] ?? "bg-slate-100 text-slate-600"}`}>
      <span className={estado === "en_curso" ? "punto-vivo" : "punto"} />
      {ETIQUETA_ESTADO_BUSQUEDA[estado] ?? estado}
    </span>
  );
}
