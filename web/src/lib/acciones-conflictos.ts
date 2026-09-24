"use server";

import { revalidatePath } from "next/cache";
import { crearClienteServidor } from "@/lib/supabase/server";

// Decisiones sobre `conflictos_datos` (worker: POST /conflictos/{id}/resolver).
// Van por el worker, no directas a Supabase, porque cada decisión se guarda
// como una observación "manual" y hay que reconsolidar la empresa (o, al
// separar, reprocesar el registro como empresa nueva) -- lógica que vive en
// radar/orquestador/conflictos_acciones.py.
export async function resolverConflicto(formData: FormData) {
  const id = Number(formData.get("id"));
  const accion = String(formData.get("accion"));
  const valor = formData.get("valor");
  const supabase = await crearClienteServidor();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const base = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
  if (!base) throw new Error("NEXT_PUBLIC_API_URL no está configurada");
  const respuesta = await fetch(`${base}/conflictos/${id}/resolver`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ accion, valor: valor ? String(valor) : null, usuario: user?.email ?? null }),
  });
  if (!respuesta.ok) {
    let detalle = respuesta.statusText;
    try {
      detalle = (await respuesta.json()).detail ?? detalle;
    } catch {
      // cuerpo no JSON
    }
    throw new Error(`No se pudo aplicar la decisión: ${detalle}`);
  }
  revalidatePath("/duplicados");
  revalidatePath("/cola-revision");
}

// Botón «Intentar resolver automáticamente» de Datos sin contrastar
// (worker: POST /conflictos/resolver-automaticamente).
export async function resolverAutomaticamente() {
  const base = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
  if (!base) throw new Error("NEXT_PUBLIC_API_URL no está configurada");
  const respuesta = await fetch(`${base}/conflictos/resolver-automaticamente?max_coste_eur=0.1`, { method: "POST" });
  if (!respuesta.ok) throw new Error(`No se pudo lanzar la resolución automática: ${respuesta.statusText}`);
  revalidatePath("/duplicados");
  revalidatePath("/cola-revision");
}

// Cola de revisión: una persona confirma o corrige lo que decidió el filtro
// de relevancia. `relevancia_revisada` impide que la IA lo vuelva a tocar.
export async function marcarRelevancia(formData: FormData) {
  const busquedaId = String(formData.get("busqueda_id"));
  const empresaId = String(formData.get("empresa_id"));
  const decision = String(formData.get("decision"));
  if (decision !== "aceptado" && decision !== "rechazado") throw new Error("decisión no válida");
  const supabase = await crearClienteServidor();
  const { error } = await supabase
    .from("busqueda_resultados")
    .update({ clasificacion: decision, relevancia_revisada: true })
    .eq("busqueda_id", busquedaId)
    .eq("empresa_id", empresaId);
  if (error) throw new Error(`No se pudo guardar: ${error.message}`);
  revalidatePath("/cola-revision");
}
