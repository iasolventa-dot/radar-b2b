import { crearClienteServidor } from "@/lib/supabase/server";
import { FormularioNuevaBusqueda } from "@/components/formulario-nueva-busqueda";

export const dynamic = "force-dynamic";

export default async function PaginaNuevaBusqueda() {
  const supabase = await crearClienteServidor();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Nueva búsqueda</h1>
        <p className="mt-1 text-sm text-slate-500">
          Describe qué empresas buscas en lenguaje natural. El agente interpreta la petición,
          te enseña cómo la ha entendido y, si confirmas, sale a buscar (doc 02 §2).
        </p>
      </div>
      <FormularioNuevaBusqueda usuarioId={user?.id ?? null} />
    </div>
  );
}
