import { ListaConflictos } from "@/components/lista-conflictos";

export const dynamic = "force-dynamic";

export default function PaginaColaRevision() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Cola de revisión</h1>
        <p className="mt-1 text-sm text-slate-500">
          Contradicciones entre fuentes que el sistema ya ha resuelto solo porque había evidencia fuerte (un dato
          más reciente de una fuente igual o más fiable, varias fuentes independientes contra una, un registro
          oficial...). El valor elegido ya está aplicado: confírmalo o cámbialo.
        </p>
      </div>
      <ListaConflictos tipo="resuelto_con_evidencia" vacio="No hay nada pendiente de revisar." />
    </div>
  );
}
