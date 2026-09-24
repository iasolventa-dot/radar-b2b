import { Bot, Filter } from "lucide-react";
import { ListaConflictos } from "@/components/lista-conflictos";
import { ListaRelevancia } from "@/components/lista-relevancia";

export const dynamic = "force-dynamic";

// Todo lo que el sistema ha decidido SOLO y conviene que una persona valide:
// (1) resultados de búsqueda que la IA consideró dudosos o descartó por no ser
// del sector/zona; (2) contradicciones entre fuentes que se resolvieron solas
// (con evidencia fuerte, evidencia encontrada en la web de la empresa o IA con
// confianza alta). Nada de esto bloquea: ya está aplicado, aquí se confirma o
// se deshace.
export default function PaginaColaRevision() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Cola de revisión</h1>
        <p className="mt-1 text-sm text-slate-500">
          Decisiones que el sistema ha tomado por su cuenta y que puedes validar o deshacer. Ya están aplicadas: no
          hace falta revisarlas para usar los resultados.
        </p>
      </div>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <Filter className="h-4 w-4 text-slate-400" /> Resultados dudosos o descartados por no ser del sector
        </h2>
        <p className="text-xs text-slate-500">
          La IA revisa cada empresa encontrada (categoría de Google Maps, descripción de su web, objeto social). Las
          descartadas no salen en los resultados ni en el CSV; las dudosas salen marcadas.
        </p>
        <ListaRelevancia />
      </section>

      <section className="space-y-3">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
          <Bot className="h-4 w-4 text-slate-400" /> Datos resueltos automáticamente
        </h2>
        <p className="text-xs text-slate-500">
          Fuentes que se contradecían y que el sistema resolvió solo: con evidencia fuerte (varias fuentes contra una,
          dato más reciente, registro oficial), porque el dato aparece en la web de la empresa, o por la IA con
          confianza alta.
        </p>
        <ListaConflictos tipo="resuelto_con_evidencia" vacio="No hay datos resueltos automáticamente pendientes de revisar." />
      </section>
    </div>
  );
}
