#!/usr/bin/env python3
"""
procesar_empresas.py — Normaliza, deduplica y audita listados de empresas españolas (CSV/XLSX).

Uso:
  python procesar_empresas.py todo       entrada.csv -d salida/        # normalizar + deduplicar + auditar
  python procesar_empresas.py normalizar entrada.xlsx -o normalizado.csv
  python procesar_empresas.py deduplicar entrada.csv -d salida/
  python procesar_empresas.py auditar    entrada.csv -o informe.md
  python procesar_empresas.py comparar   --a '{"razon_social":"X SL","telefono":"955..."}' --b '{...}'

Mapeo de columnas: se detecta automáticamente por nombre (nif, cif, razón social, teléfono…).
Se puede forzar con --map campo=columna (p. ej. --map razon_social="Nombre empresa").

Salidas de 'todo' / 'deduplicar':
  normalizado.csv       registros con columnas normalizadas y avisos
  clusters.csv          cada registro con su cluster_id (mismo id = misma empresa según las reglas)
  pares_revision.csv    pares en zona gris para revisar (LLM o humano)
  informe_calidad.md    auditoría de calidad
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from itertools import combinations

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_empresas as L  # noqa: E402

SINONIMOS = {
    "nif": ["nif", "cif", "nif_cif", "cif_nif", "nif/cif", "cif/nif", "vat", "identificador_fiscal", "nifcif", "tax_id"],
    "razon_social": ["razon_social", "denominacion", "denominacion_social", "empresa", "nombre_empresa", "nombre", "name", "company", "company_name", "title", "titulo"],
    "nombre_comercial": ["nombre_comercial", "marca", "comercial", "trade_name", "rotulo"],
    "forma_juridica": ["forma_juridica", "tipo_sociedad", "forma"],
    "telefono": ["telefono", "telefonos", "tel", "phone", "phone_number", "telefono_1", "movil", "tlf", "telf"],
    "email": ["email", "emails", "correo", "e_mail", "mail", "correo_electronico"],
    "web": ["web", "website", "url", "sitio_web", "pagina_web", "web_site", "dominio"],
    "direccion": ["direccion", "domicilio", "address", "calle", "direccion_completa", "full_address"],
    "cp": ["cp", "codigo_postal", "postal_code", "zip", "c_p", "postcode"],
    "municipio": ["municipio", "localidad", "ciudad", "poblacion", "city", "town"],
    "provincia": ["provincia", "province", "state", "region"],
    "lat": ["lat", "latitud", "latitude"],
    "lon": ["lon", "lng", "longitud", "longitude"],
    "place_id": ["place_id", "google_place_id", "placeid"],
}


def _clave(col: str) -> str:
    return L.normalizar_texto(col).replace(" ", "_")


def detectar_columnas(df: pd.DataFrame, forzadas: dict) -> dict:
    mapa = {}
    claves = {_clave(c): c for c in df.columns}
    for campo, sinonimos in SINONIMOS.items():
        if campo in forzadas:
            mapa[campo] = forzadas[campo]
            continue
        for s in sinonimos:
            if s in claves and claves[s] not in mapa.values():
                mapa[campo] = claves[s]
                break
    return mapa


def leer(ruta: str) -> pd.DataFrame:
    if ruta.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(ruta, dtype=str)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(ruta, dtype=str, sep=None, engine="python", encoding=enc)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"No se pudo leer {ruta}")


def normalizar_df(df: pd.DataFrame, mapa: dict) -> tuple[pd.DataFrame, list[dict]]:
    regs = []
    for _, fila in df.iterrows():
        entrada = {campo: (None if pd.isna(fila[col]) else fila[col]) for campo, col in mapa.items()}
        regs.append(L.normalizar_registro(entrada))
    salida = df.copy()
    salida.insert(0, "id_fila", range(1, len(df) + 1))
    for k in ["nif", "nif_valido", "nif_tipo", "nif_aviso", "persona_fisica", "forma_juridica", "forma_coherente_nif",
              "nombre_norm", "comercial_norm", "dominio", "cp", "cp_aviso", "cod_provincia"]:
        salida[f"n_{k}"] = [r[k] for r in regs]
    for k in ["telefonos", "telefonos_invalidos", "emails", "emails_personales"]:
        salida[f"n_{k}"] = ["; ".join(r[k]) for r in regs]
    return salida, regs


def telefonos_compartidos(regs: list[dict], limite: int = 3) -> set:
    """Teléfonos presentes en más de `limite` registros con NIF distinto (gestorías, centralitas)."""
    por_tel = defaultdict(set)
    for i, r in enumerate(regs):
        for t in r["telefonos"]:
            por_tel[t].add(r["nif"] or f"sin_nif_{i}")
    return {t for t, nifs in por_tel.items() if len(nifs) > limite}


def bloques(regs: list[dict]) -> dict:
    """Claves de bloqueo (doc 05 §2.1)."""
    b = defaultdict(list)
    for i, r in enumerate(regs):
        if r["nif"] and r["nif_valido"]:
            b["nif:" + r["nif"]].append(i)
        if r["dominio"]:
            b["dom:" + r["dominio"]].append(i)
        for t in r["telefonos"]:
            b["tel:" + t].append(i)
        if r["place_id"]:
            b["pid:" + r["place_id"]].append(i)
        for nombre in (r["nombre_norm"], r["comercial_norm"]):
            dist = sorted(L.tokens_distintivos(nombre or ""))
            if dist:
                b[f"nom:{dist[0]}|{r['cod_provincia'] or ''}"].append(i)
            elif nombre:
                b[f"nomg:{nombre}|{r['cod_provincia'] or ''}"].append(i)
    return b


class UnionFind:
    def __init__(self, n, regs):
        self.p = list(range(n))
        self.nifs = [{r["nif"]} if r["nif"] and r["nif_valido"] else set() for r in regs]

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        # Nunca unir clusters con NIF válidos distintos (regla dura 1), ni siquiera por transitividad
        if self.nifs[ra] and self.nifs[rb] and self.nifs[ra] != self.nifs[rb]:
            return False
        self.p[rb] = ra
        self.nifs[ra] |= self.nifs[rb]
        return True


def deduplicar(regs: list[dict], max_bloque: int = 200) -> tuple[list[int], list[dict], dict]:
    compartidos = telefonos_compartidos(regs)
    pares_vistos, resultados = set(), []
    for clave, idx in bloques(regs).items():
        if len(idx) < 2:
            continue
        if len(idx) > max_bloque:  # bloque demasiado grande (clave poco discriminante): se omite
            continue
        for i, j in combinations(sorted(set(idx)), 2):
            if (i, j) in pares_vistos:
                continue
            pares_vistos.add((i, j))
            c = L.comparar(regs[i], regs[j], compartidos)
            if c["decision"] != "distinta" or c["regla"].startswith("R1"):
                resultados.append({"i": i, "j": j, **c})
    uf = UnionFind(len(regs), regs)
    bloqueadas = 0
    for r in sorted(resultados, key=lambda x: -x["puntuacion"]):
        if r["decision"] == "misma" and not uf.union(r["i"], r["j"]):
            bloqueadas += 1
            r["decision"] = "revision"
            r["senales"] = r["senales"] + ["fusión bloqueada: el cluster ya contiene otro NIF"]
    raices, cluster = {}, []
    for i in range(len(regs)):
        cluster.append(raices.setdefault(uf.find(i), len(raices) + 1))
    stats = {"pares_comparados": len(pares_vistos), "telefonos_compartidos": sorted(compartidos),
             "fusiones_bloqueadas_por_nif": bloqueadas}
    return cluster, resultados, stats


def informe_calidad(df_norm: pd.DataFrame, regs: list[dict], cluster: list[int] | None, pares: list[dict] | None,
                    mapa: dict, stats: dict | None) -> str:
    n = len(regs)
    pct = lambda x: f"{(100 * x / n):.1f} %" if n else "—"  # noqa: E731
    con_nif = sum(1 for r in regs if r["nif"])
    nif_ok = sum(1 for r in regs if r["nif_valido"])
    pf = sum(1 for r in regs if r["persona_fisica"])
    con_tel = sum(1 for r in regs if r["telefonos"])
    tel_inv = sum(1 for r in regs if r["telefonos_invalidos"])
    con_email = sum(1 for r in regs if r["emails"])
    email_pers = sum(1 for r in regs if r["emails_personales"])
    con_dom = sum(1 for r in regs if r["dominio"])
    cp_mal = sum(1 for r in regs if r["cp_aviso"] and "no válido" in r["cp_aviso"])
    cp_incoh = sum(1 for r in regs if r["cp_aviso"] and "pero provincia" in r["cp_aviso"])
    forma_incoh = sum(1 for r in regs if r["forma_coherente_nif"] is False)
    nif_dup = sum(c - 1 for c in Counter(r["nif"] for r in regs if r["nif_valido"]).values() if c > 1)
    L_ = [
        "# Informe de calidad del listado", "",
        f"Registros analizados: **{n}**", "",
        "## Columnas detectadas", "",
        "| Campo | Columna del fichero |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in mapa.items()],
        "", "## Completitud y validez", "",
        "| Indicador | Valor |", "|---|---|",
        f"| Con NIF | {con_nif} ({pct(con_nif)}) |",
        f"| NIF con control válido | {nif_ok} ({pct(nif_ok)}) |",
        f"| NIF inválidos | {con_nif - nif_ok} |",
        f"| Personas físicas (DNI/NIE: autónomos → dato personal) | {pf} |",
        f"| Letra del NIF incoherente con forma jurídica | {forma_incoh} |",
        f"| Con teléfono válido | {con_tel} ({pct(con_tel)}) |",
        f"| Con algún teléfono inválido | {tel_inv} |",
        f"| Con email válido | {con_email} ({pct(con_email)}) |",
        f"| Con email posiblemente personal (dato personal) | {email_pers} |",
        f"| Con dominio web propio | {con_dom} ({pct(con_dom)}) |",
        f"| CP no válido | {cp_mal} |",
        f"| CP incoherente con provincia | {cp_incoh} |",
        f"| NIF repetidos (filas sobrantes) | {nif_dup} |",
    ]
    if cluster is not None:
        n_ent = len(set(cluster))
        auto = sum(1 for p in pares if p["decision"] == "misma")
        rev = sum(1 for p in pares if p["decision"] == "revision")
        L_ += ["", "## Deduplicación", "",
               f"- Entidades distintas estimadas: **{n_ent}** (de {n} filas → {n - n_ent} duplicados, {pct(n - n_ent)})",
               f"- Pares fusionados automáticamente (≥ {L.UMBRAL_FUSION_AUTO}): {auto}",
               f"- Pares en zona gris para revisión ({L.UMBRAL_REVISION}–{L.UMBRAL_FUSION_AUTO}): {rev}",
               f"- Fusiones bloqueadas por conflicto de NIF: {stats.get('fusiones_bloqueadas_por_nif', 0)}",
               f"- Teléfonos compartidos por muchas empresas (excluidos del matching): {len(stats.get('telefonos_compartidos', []))}"]
    avisos = Counter()
    for r in regs:
        for k in ("nif_aviso", "cp_aviso"):
            if r[k]:
                avisos[f"{k}: {r[k] if 'pero provincia' not in r[k] else 'CP incoherente con provincia'}"] += 1
    if avisos:
        L_ += ["", "## Avisos más frecuentes", "", "| Aviso | Nº |", "|---|---|",
               *[f"| {k} | {v} |" for k, v in avisos.most_common(12)]]
    L_ += ["", "## Recordatorios", "",
           "- Formato válido ≠ dato correcto: un teléfono bien formado puede no ser de la empresa.",
           "- Los registros de personas físicas y emails personales son datos personales (ver doc 06 del proyecto).",
           "- Los umbrales de matching son iniciales; calibrar con el golden set."]
    return "\n".join(L_) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("accion", choices=["todo", "normalizar", "deduplicar", "auditar", "comparar"])
    ap.add_argument("entrada", nargs="?")
    ap.add_argument("-o", "--salida")
    ap.add_argument("-d", "--dir", default="salida")
    ap.add_argument("--map", action="append", default=[], help="campo=columna")
    ap.add_argument("--a")
    ap.add_argument("--b")
    args = ap.parse_args()

    if args.accion == "comparar":
        a = L.normalizar_registro(json.loads(args.a))
        b = L.normalizar_registro(json.loads(args.b))
        print(json.dumps(L.comparar(a, b), ensure_ascii=False, indent=2))
        return

    if not args.entrada:
        ap.error("falta el fichero de entrada")
    forzadas = dict(m.split("=", 1) for m in args.map)
    df = leer(args.entrada)
    mapa = detectar_columnas(df, forzadas)
    if "razon_social" not in mapa and "nombre_comercial" not in mapa:
        print("AVISO: no se detectó columna de nombre. Usa --map razon_social=<columna>", file=sys.stderr)
    print("Columnas detectadas:", json.dumps(mapa, ensure_ascii=False), file=sys.stderr)
    df_norm, regs = normalizar_df(df, mapa)

    if args.accion == "normalizar":
        ruta = args.salida or "normalizado.csv"
        df_norm.to_csv(ruta, index=False, encoding="utf-8-sig")
        print(f"→ {ruta}")
        return

    cluster = pares = stats = None
    if args.accion in ("todo", "deduplicar"):
        cluster, pares, stats = deduplicar(regs)
        os.makedirs(args.dir, exist_ok=True)
        df_norm.insert(1, "cluster_id", cluster)
        df_norm.sort_values(["cluster_id", "id_fila"]).to_csv(os.path.join(args.dir, "clusters.csv"), index=False, encoding="utf-8-sig")
        nombre = mapa.get("razon_social") or mapa.get("nombre_comercial")
        filas = []
        for p in sorted(pares, key=lambda x: -x["puntuacion"]):
            if p["decision"] != "revision":
                continue
            filas.append({
                "fila_a": p["i"] + 1, "fila_b": p["j"] + 1,
                "nombre_a": df.iloc[p["i"]][nombre] if nombre else "", "nombre_b": df.iloc[p["j"]][nombre] if nombre else "",
                "puntuacion": p["puntuacion"], "regla": p["regla"], "senales": " | ".join(p["senales"]),
            })
        pd.DataFrame(filas, columns=["fila_a", "fila_b", "nombre_a", "nombre_b", "puntuacion", "regla", "senales"]).to_csv(
            os.path.join(args.dir, "pares_revision.csv"), index=False, encoding="utf-8-sig")
        df_norm.to_csv(os.path.join(args.dir, "normalizado.csv"), index=False, encoding="utf-8-sig")

    informe = informe_calidad(df_norm, regs, cluster, pares, mapa, stats)
    if args.accion == "auditar":
        ruta = args.salida or "informe_calidad.md"
    else:
        ruta = os.path.join(args.dir, "informe_calidad.md")
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(informe)
    print(f"→ resultados en {args.dir if args.accion != 'auditar' else ruta}")


if __name__ == "__main__":
    main()
