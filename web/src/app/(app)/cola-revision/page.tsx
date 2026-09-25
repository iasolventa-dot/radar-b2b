import { Bot, Filter, ListChecks } from "lucide-react";
import { ListaConflictos } from "@/components/lista-conflictos";
import { ListaRelevancia } from "@/components/lista-relevancia";
import { EncabezadoPagina } from "@/components/encabezado-pagina";

export const dynamic = "force-dynamic";

// Todo lo que el sistema ha decidido SOLO y conviene que una persona valide:
// (1) resultados de búsqueda que la IA consideró dudosos o descartó por no ser
// del sector/zona; (2) contradicciones entre fuentes que se resolvieron solas
// (con evidencia fuerte, evidencia encontrada en la web de la empresa o IA con
// confianza alta). Nada de esto bloquea: ya está aplicado, aquí se confirma o
// se deshace.
export default function PaginaColaRevision() {
  return (
    <div className="entrada space-y-9">
      <EncabezadoPagina icono={ListChecks} antetitulo="Validar" titulo="Cola de revisión">
        <p>
          Decisiones que el sistema ha tomado por su cuenta y que puedes validar o deshacer. Ya están aplicadas: no
          hace falta revisarlas para usar los resultados.
        </p>
      </EncabezadoPagina>

      <section className="space-y-4">
        <div>
          <h2 className="titulo-seccion">
            <span className="icono-seccion">
              <Filter className="h-4 w-4" />
            </span>
            Resultados dudosos o descartados por no ser del sector
          </h2>
          <p className="mt-1.5 max-w-3xl text-sm text-slate-500">
            La IA revisa cada empresa encontrada (categoría de Google Maps, descripción de su web, objeto social). Las
            descartadas no salen en los resultados ni en el CSV; las dudosas salen marcadas.
          </p>
        </div>
        <ListaRelevancia />
      </section>

      <section className="space-y-4">
        <div>
          <h2 className="titulo-seccion">
            <span className="icono-seccion">
              <Bot className="h-4 w-4" />
            </span>
            Datos resueltos automáticamente
          </h2>
          <p className="mt-1.5 max-w-3xl text-sm text-slate-500">
            Fuentes que se contradecían y que el sistema resolvió solo: con evidencia fuerte (varias fuentes contra una,
            dato más reciente, registro oficial), porque el dato aparece en la web de la empresa, o por la IA con
            confianza alta.
          </p>
        </div>
        <ListaConflictos tipo="resuelto_con_evidencia" vacio="No hay datos resueltos automáticamente pendientes de revisar." />
      </section>
    </div>
  );
}
