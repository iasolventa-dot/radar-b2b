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
