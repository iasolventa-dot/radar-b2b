"use server";

import { revalidatePath } from "next/cache";
import { crearClienteServidor } from "@/lib/supabase/server";

// fusionar_empresas (migración 202609142000) hace toda la reasignación
// en una sola transacción atómica en Postgres -- ver esa migración para
// el porqué de una función security definer en vez de varios pasos
// sueltos aquí (como sí hace revision/[id]/acciones.ts para el golden
// set): aquí hacen falta comprobaciones "not exists" contra 3
// restricciones unique distintas para no romper nada, mucho más simples
// en SQL que reconstruidas a mano en TypeScript sin garantía de
// atomicidad entre pasos.

export async function confirmarFusion(formData: FormData) {
  const candidatoId = Number(formData.get("candidato_id"));
  const origen = String(formData.get("origen"));
  const destino = String(formData.get("destino"));
  const supabase = await crearClienteServidor();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { error } = await supabase.rpc("fusionar_empresas", {
    p_origen: origen,
    p_destino: destino,
    p_motivo: "confirmado como duplicado desde el panel",
    p_decidido_por: user?.email ? `usuario:${user.email}` : "usuario:desconocido",
    p_puntuacion: Number(formData.get("puntuacion")) || null,
    p_candidato_id: candidatoId,
  });

  if (error) {
    throw new Error(`No se pudo fusionar: ${error.message}`);
  }

  revalidatePath("/duplicados");
}

export async function descartarDuplicado(formData: FormData) {
  const candidatoId = Number(formData.get("candidato_id"));
  const supabase = await crearClienteServidor();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { error } = await supabase
    .from("candidatos_duplicado")
    .update({
      estado: "rechazado",
      revisado_por: user?.email ? `usuario:${user.email}` : "usuario:desconocido",
      revisado_en: new Date().toISOString(),
    })
    .eq("id", candidatoId);

  if (error) {
    throw new Error(`No se pudo descartar: ${error.message}`);
  }

  revalidatePath("/duplicados");
}
