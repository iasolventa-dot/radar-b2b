"use server";

import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { crearClienteServidor } from "@/lib/supabase/server";

// Genera el siguiente id_golden correlativo (GS-0001, GS-0002, ...).
// No es una operación atómica estricta (dos personas promoviendo a la vez
// podrían chocar), aceptable para un panel de un único usuario interno;
// si se detecta una colisión, el insert falla por la clave primaria y el
// usuario simplemente reintenta.
async function siguienteIdGolden(supabase: Awaited<ReturnType<typeof crearClienteServidor>>) {
  const { data } = await supabase
    .from("golden_entidades")
    .select("id_golden")
    .like("id_golden", "GS-%")
    .order("id_golden", { ascending: false })
    .limit(1);

  const ultimo = data?.[0]?.id_golden;
  const ultimoNumero = ultimo ? parseInt(ultimo.replace("GS-", ""), 10) : 0;
  const siguiente = (Number.isFinite(ultimoNumero) ? ultimoNumero : 0) + 1;
  return `GS-${String(siguiente).padStart(4, "0")}`;
}

function valorOpcional(formData: FormData, campo: string): string | null {
  const valor = formData.get(campo);
  if (typeof valor !== "string") return null;
  const recortado = valor.trim();
  return recortado === "" ? null : recortado;
}

export async function promoverCandidato(formData: FormData) {
  const idFila = String(formData.get("id_fila"));
  const supabase = await crearClienteServidor();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  const idGolden = await siguienteIdGolden(supabase);

  const { error: errorInsert } = await supabase.from("golden_entidades").insert({
    id_golden: idGolden,
    nif: valorOpcional(formData, "nif"),
    razon_social: String(formData.get("razon_social")),
    nombre_comercial: valorOpcional(formData, "nombre_comercial"),
    forma_juridica: valorOpcional(formData, "forma_juridica"),
    es_persona_fisica: formData.get("es_persona_fisica") === "on",
    cnae_principal: valorOpcional(formData, "cnae_principal"),
    estado: valorOpcional(formData, "estado"),
    municipio: valorOpcional(formData, "municipio"),
    municipio_ine: valorOpcional(formData, "municipio_ine"),
    provincia: valorOpcional(formData, "provincia") ?? "Sevilla",
    cp: valorOpcional(formData, "cp"),
    direccion_domicilio_social: valorOpcional(formData, "direccion_domicilio_social"),
    direccion_sede_operativa: valorOpcional(formData, "direccion_sede_operativa"),
    telefono: valorOpcional(formData, "telefono"),
    telefono_verificado_llamada: valorOpcional(formData, "telefono_verificado_llamada") ?? "no_aplica",
    web: valorOpcional(formData, "web"),
    email_generico: valorOpcional(formData, "email_generico"),
    caso_dificil: valorOpcional(formData, "caso_dificil"),
    fuente_verificacion: valorOpcional(formData, "fuente_verificacion"),
    url_evidencia: valorOpcional(formData, "url_evidencia"),
    fecha_verificacion: valorOpcional(formData, "fecha_verificacion"),
    verificado_por: valorOpcional(formData, "verificado_por") ?? user?.email ?? null,
    notas: valorOpcional(formData, "notas"),
    candidato_origen_id: idFila,
  });

  if (errorInsert) {
    throw new Error(`No se pudo guardar la entidad: ${errorInsert.message}`);
  }

  const { error: errorUpdate } = await supabase
    .from("golden_candidatos")
    .update({ estado_revision: "promovido", entidad_id_real: idGolden })
    .eq("id_fila", idFila);

  if (errorUpdate) {
    throw new Error(`Entidad guardada (${idGolden}) pero no se pudo marcar el candidato: ${errorUpdate.message}`);
  }

  revalidatePath("/revision");
  revalidatePath("/entidades");
  revalidatePath("/");
  redirect("/revision?promovido=" + idGolden);
}

export async function descartarCandidato(formData: FormData) {
  const idFila = String(formData.get("id_fila"));
  const motivo = valorOpcional(formData, "motivo_descarte");
  const supabase = await crearClienteServidor();

  const { error } = await supabase
    .from("golden_candidatos")
    .update({ estado_revision: "descartado", notas: motivo })
    .eq("id_fila", idFila);

  if (error) {
    throw new Error(`No se pudo descartar el candidato: ${error.message}`);
  }

  revalidatePath("/revision");
  revalidatePath("/");
  redirect("/revision");
}
