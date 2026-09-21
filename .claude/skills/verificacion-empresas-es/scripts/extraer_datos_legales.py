#!/usr/bin/env python3
"""
extraer_datos_legales.py — Extrae con reglas (sin LLM) NIF, razón social, datos registrales, teléfonos,
emails y códigos postales del texto de un aviso legal / página de contacto de una web española.

La LSSI (art. 10) obliga a publicar denominación social, NIF, domicilio y datos registrales, así que el
aviso legal es el "puente de identidad" entre dominio/nombre comercial y NIF/razón social (doc 04 §3).

Uso:
  python extraer_datos_legales.py pagina.html            # HTML o texto
  cat aviso.txt | python extraer_datos_legales.py -
  python extraer_datos_legales.py pagina.html --dominio perezobras.es

Salida JSON. Los campos con varios candidatos se devuelven como lista ordenada por probabilidad.
Si hay más de un NIF válido (p. ej. el de la agencia que hizo la web), se marca en "avisos":
el LLM o una persona debe decidir cuál es el titular. Úsalo ANTES de llamar a un LLM: solo si faltan
campos merece la pena la extracción con modelo.
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_empresas as L  # noqa: E402

RX_NIF = re.compile(
    r"(?<![A-Z0-9])(?:ES[\s\-]?)?("
    r"[ABCDEFGHJNPQRSUVW][\s.\-]?\d{2}[\s.\-]?\d{3}[\s.\-]?\d{2}[\s.\-]?[0-9A-J]"
    r"|\d{2}[\s.]?\d{3}[\s.]?\d{3}[\s\-]?[A-Z]"
    r"|[XYZKLM][\s\-]?\d{7}[\s\-]?[A-Z])(?![A-Z0-9])", re.I)
RX_TEL = re.compile(r"(?<!\d)(?:\+34|0034)?[\s.\-]?\(?[6789]\d{2}\)?(?:[\s.\-]?\d){6}(?!\d)")
RX_EMAIL = re.compile(r"[a-z0-9._%+\-]+\s*(?:@|\[at\]|\(at\)|\(arroba\)|\sarroba\s)\s*[a-z0-9.\-]+\.[a-z]{2,}", re.I)
RX_CP = re.compile(r"(?<!\d)((?:0[1-9]|[1-4]\d|5[0-2])\d{3})(?!\d)")
RX_REGISTRO = re.compile(
    r"Registro\s+Mercantil\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]*(?:[\s\-](?:de\s+|del\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)"
    r"[\s,.;:]*.{0,40}?Tomo\s*:?\s*([\d.]*\d).{0,40}?Folio\s*:?\s*(\d+).{0,60}?Hoja\s*(?:n[º°o.]*\s*)?:?\s*([A-Z]{1,2}[\s\-]?\d[\d.]*\d|[A-Z]{1,2}[\s\-]?\d)",
    re.I | re.S)
FORMAS = r"(?:S\.?\s?L\.?\s?U\.?|S\.?\s?L\.?\s?L\.?|S\.?\s?L\.?|S\.?\s?A\.?\s?U\.?|S\.?\s?A\.?|S\.?\s?Coop\.?(?:\s?And\.?)?|Sociedad\s+Limitada|Sociedad\s+An[oó]nima)"
RX_RAZON = re.compile(r"([A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ&'.\- ]{2,80}?,?\s" + FORMAS + r")(?=[\s,.;:)]|$)")
RX_ETIQUETA_RAZON = re.compile(
    r"(?:denominaci[oó]n\s+social|raz[oó]n\s+social|titular(?:\s+de\s+(?:la|este|esta)\s+(?:web|sitio(?:\s+web)?|p[aá]gina(?:\s+web)?))?"
    r"|(?:web|sitio|p[aá]gina)\s+(?:es\s+)?propiedad\s+de)"
    r"\s*(?:[:\-]|\ses\b|\ssiendo\b)\s*([^\n;|(]{3,100})", re.I)
RX_AGENCIA = re.compile(r"(dise[ñn]o(?:\s+y\s+desarrollo)?\s+web|desarrollado\s+por|dise[ñn]ado\s+por|web\s+creada\s+por|powered\s+by)", re.I)


def html_a_texto(contenido: str) -> str:
    if "<" in contenido and ">" in contenido:
        contenido = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", contenido)
        contenido = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", contenido)
        contenido = re.sub(r"(?s)<[^>]+>", " ", contenido)
    texto = html_lib.unescape(contenido)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


def _cerca(texto: str, pos: int, radio: int = 250) -> str:
    return texto[max(0, pos - radio): pos + radio]


def extraer(texto: str, dominio: str | None = None) -> dict:
    res = {"nifs": [], "nifs_invalidos_etiquetados": [], "razones_sociales": [], "registro_mercantil": None, "telefonos": [], "emails": [],
           "codigos_postales": [], "avisos": []}
    # --- NIF (solo los que pasan el dígito de control) ---
    vistos = set()
    for m in RX_NIF.finditer(texto):
        v = L.validar_nif(m.group(1))
        if not v["valido"]:
            # NIF con formato correcto pero control erróneo, junto a la etiqueta NIF/CIF: posible errata en la web
            if re.search(r"(?:C\.?\s?I\.?\s?F|N\.?\s?I\.?\s?F)\.?\s*:?\s*$", texto[max(0, m.start() - 12): m.start()], re.I):
                res["nifs_invalidos_etiquetados"].append(v["nif"])
            continue
        if v["nif"] not in vistos:
            vistos.add(v["nif"])
            contexto = _cerca(texto, m.start(), 120)
            etiquetado = bool(re.search(r"C\.?\s?I\.?\s?F|N\.?\s?I\.?\s?F|identificaci[oó]n\s+fiscal", contexto, re.I))
            cerca_agencia = bool(RX_AGENCIA.search(_cerca(texto, m.start(), 150)))
            res["nifs"].append({"nif": v["nif"], "tipo": v["tipo"], "etiquetado_como_nif": etiquetado,
                                "cerca_de_mencion_agencia": cerca_agencia, "posicion": m.start()})
    res["nifs"].sort(key=lambda x: (x["cerca_de_mencion_agencia"], not x["etiquetado_como_nif"], x["posicion"]))
    if res["nifs_invalidos_etiquetados"]:
        res["avisos"].append("NIF con dígito de control incorrecto publicado en la web (posible errata): no usar sin confirmar")
    if len(res["nifs"]) > 1:
        res["avisos"].append("varios NIF válidos: puede haber datos de la agencia web, de un grupo o de un cliente; decidir el titular")
    if any(n["cerca_de_mencion_agencia"] for n in res["nifs"]):
        res["avisos"].append("hay un NIF junto a una mención de diseño/desarrollo web: probablemente es de la agencia")
    # --- Razón social: etiquetas explícitas y nombres con forma jurídica cerca del NIF principal ---
    candidatas = []
    for m in RX_ETIQUETA_RAZON.finditer(texto):
        c = m.group(1)
        mf = RX_RAZON.search(c)  # si la etiqueta va seguida de un nombre con forma jurídica, recortar ahí
        candidatas.append((0, (mf.group(1) if mf else c.split(",")[0]).strip(" .,:")))
    ref = next((n["posicion"] for n in res["nifs"] if not n["cerca_de_mencion_agencia"]), None)
    for m in RX_RAZON.finditer(texto):
        if RX_AGENCIA.search(texto[max(0, m.start() - 80): m.start()]):
            continue  # nombre que sigue a "Diseño web:", "Desarrollado por"… → agencia
        distancia = abs(m.start() - ref) if ref is not None else m.start()
        candidatas.append((1 + distancia / 10000, m.group(1).strip(" .,:")))
    candidatas = [c for _, c in sorted(candidatas, key=lambda x: x[0])]
    limpias = []
    for c in candidatas:
        c = re.sub(r"^(?:la\s+empresa|la\s+sociedad|el\s+titular|esta\s+web\s+es\s+propiedad\s+de|propiedad\s+de)\s+", "", c, flags=re.I)
        c = re.sub(r"\s+", " ", c).strip()
        if 3 <= len(c) <= 100 and c.lower() not in [x.lower() for x in limpias]:
            limpias.append(c)
    res["razones_sociales"] = limpias[:5]
    # --- Registro mercantil ---
    m = RX_REGISTRO.search(texto)
    if m:
        res["registro_mercantil"] = {"registro": m.group(1).strip(), "tomo": m.group(2), "folio": m.group(3),
                                     "hoja": re.sub(r"\s", "", m.group(4)).rstrip(".")}
    # --- Teléfonos, emails, CP ---
    tels = []
    for m in RX_TEL.finditer(texto):
        t = L.normalizar_telefono(m.group(0))
        if t["valido"] and t["e164"] not in tels:
            tels.append(t["e164"])
    res["telefonos"] = tels
    ems = []
    for m in RX_EMAIL.finditer(texto):
        e = L.normalizar_email(m.group(0))
        if e["valido"] and e["email"] not in [x["email"] for x in ems]:
            ems.append({"email": e["email"], "es_generico": e["es_generico"],
                        "del_dominio": bool(dominio and e["dominio"] and e["dominio"].endswith(dominio))})
    res["emails"] = ems
    res["codigos_postales"] = sorted(set(RX_CP.findall(texto)))[:5]
    if dominio and ems and not any(x["del_dominio"] for x in ems):
        res["avisos"].append(f"ningún email pertenece al dominio {dominio}")
    for n in res["nifs"]:
        n.pop("posicion", None)
    return res


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fichero", help="ruta a HTML/texto o '-' para stdin")
    ap.add_argument("--dominio")
    a = ap.parse_args()
    contenido = sys.stdin.read() if a.fichero == "-" else open(a.fichero, encoding="utf-8", errors="replace").read()
    print(json.dumps(extraer(html_a_texto(contenido), a.dominio), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
