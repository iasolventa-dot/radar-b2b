import { notFound } from "next/navigation";
import { crearClienteServidor } from "@/lib/supabase/server";
import type { BusquedaFila } from "@/lib/tipos";
import { ProgresoBusqueda } from "@/components/progreso-busqueda";

export const dynamic = "force-dynamic";

export default async function PaginaDetalleBusqueda({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const supabase = await crearClienteServidor();

  const { data: busqueda } = await supabase
    .from("busquedas")
    .select("id, peticion, filtros, presupuesto_eur, estado, rondas, estadisticas, coste_eur, creado_en, finalizado_en")
    .eq("id", decodeURIComponent(id))
    .maybeSingle();

  if (!busqueda) notFound();

  return <ProgresoBusqueda id={busqueda.id} inicial={busqueda as unknown as BusquedaFila} />;
}
