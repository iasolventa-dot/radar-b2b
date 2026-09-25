import { crearClienteServidor } from "@/lib/supabase/server";
import { Search } from "lucide-react";
import { FormularioNuevaBusqueda } from "@/components/formulario-nueva-busqueda";
import { EncabezadoPagina } from "@/components/encabezado-pagina";

export const dynamic = "force-dynamic";

export default async function PaginaNuevaBusqueda({
  searchParams,
}: {
  searchParams: Promise<{ peticion?: string; contexto?: string }>;
}) {
  const supabase = await crearClienteServidor();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  // Prellenado desde "Responder y relanzar" (progreso-busqueda.tsx) cuando
  // el agente para con una pregunta -- este primer planificador no es
  // interactivo (no hay forma de reanudar la MISMA búsqueda con la
  // respuesta), así que la vía es lanzar una búsqueda nueva con la
  // pregunta y la respuesta como contexto. Sin esto, había que retipear
  // la petición original a mano cada vez.
  const { peticion, contexto } = await searchParams;

  return (
    <div className="entrada space-y-8">
      <EncabezadoPagina icono={Search} antetitulo="Agente de búsqueda" titulo={<>¿Qué empresas <span className="texto-marca">buscamos hoy</span>?</>}>
        <p>
          Descríbelo como se lo dirías a una persona. El agente interpreta la petición, te enseña cómo la ha
          entendido y, cuando confirmas, sale a buscar, contrasta fuentes y rellena los datos de contacto.
        </p>
      </EncabezadoPagina>
      <FormularioNuevaBusqueda usuarioId={user?.id ?? null} peticionInicial={peticion} contextoInicial={contexto} />
    </div>
  );
}
