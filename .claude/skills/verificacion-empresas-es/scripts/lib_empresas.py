"""
lib_empresas.py — Normalización, validación y comparación de registros de empresas españolas.

Implementa las reglas del documento "05 — Verificación, resolución de entidades y confianza"
del proyecto Radar B2B. Si cambias umbrales o pesos aquí, actualiza también ese documento.

Solo usa la biblioteca estándar de Python (difflib, re, math, unicodedata).
"""
from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher

# =============================================================================
# Constantes de decisión (doc 05 §2.4) — calibrar con el golden set
# =============================================================================
UMBRAL_FUSION_AUTO = 0.80
UMBRAL_REVISION = 0.55

PESOS = {
    "nombre_095": 0.45,
    "nombre_088": 0.30,
    "nombre_080": 0.15,
    "nombre_bajo": -0.15,         # similitud < 0,50 con ambos nombres presentes
    "nombre_solo_genericas": 0.15,  # tope si no hay palabras distintivas en común
    "dominio": 0.45,
    "dominio_minimo": 0.60,        # un dominio común garantiza al menos revisión
    "telefono": 0.35,
    "email": 0.25,
    "dist_50": 0.25,
    "dist_300": 0.15,
    "dist_2000": 0.05,
    "dist_lejos": -0.20,           # > 50 km
    "cp_igual": 0.10,              # solo si no hay coordenadas
    "provincia_distinta": -0.20,   # solo si no hay coordenadas
    "forma_distinta": -0.30,
}

# =============================================================================
# Texto
# =============================================================================
def quitar_tildes(t: str) -> str:
    """Quita tildes y diéresis; la ñ pasa a n (igual que unaccent en Postgres), porque muchas
    fuentes escriben MUNOZ en vez de MUÑOZ y deben casar."""
    t = unicodedata.normalize("NFD", t)
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def normalizar_texto(t) -> str:
    """minúsculas, sin tildes, sin signos, espacios simples."""
    if t is None or (isinstance(t, float) and math.isnan(t)):
        return ""
    t = quitar_tildes(str(t)).lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# Formas jurídicas: (patrón sobre texto ORIGINAL en minúsculas sin tildes, código)
# El orden importa: primero las más largas.
_FORMAS = [
    (r"sociedad limitada laboral|s\.?\s?l\.?\s?l\.?(?=\W|$)", "SLL"),
    (r"sociedad limitada unipersonal|s\.?\s?l\.?\s?u\.?(?=\W|$)", "SLU"),
    (r"sociedad limitada nueva empresa|s\.?\s?l\.?\s?n\.?\s?e\.?(?=\W|$)", "SLNE"),
    (r"sociedad de responsabilidad limitada|sociedad limitada|s\.?\s?r\.?\s?l\.?(?=\W|$)|s\.?\s?l\.?(?=\W|$)", "SL"),
    (r"sociedad anonima laboral|s\.?\s?a\.?\s?l\.?(?=\W|$)", "SAL"),
    (r"sociedad anonima unipersonal|s\.?\s?a\.?\s?u\.?(?=\W|$)", "SAU"),
    (r"sociedad anonima|s\.?\s?a\.?(?=\W|$)", "SA"),
    (r"sociedad cooperativa andaluza|s\.?\s?coop\.?\s?and\.?(?=\W|$)|s\.?\s?c\.?\s?a\.?(?=\W|$)", "SCA"),
    (r"sociedad cooperativa|s\.?\s?coop\.?(?=\W|$)|cooperativa", "SCOOP"),
    (r"sociedad civil particular|s\.?\s?c\.?\s?p\.?(?=\W|$)", "SCP"),
    (r"sociedad civil|s\.?\s?c\.?(?=\W|$)", "SC"),
    (r"comunidad de bienes|c\.?\s?b\.?(?=\W|$)", "CB"),
]
_FORMAS_RE = [(re.compile(r"(?:(?<=\W)|^)(?:" + p + r")", re.I), c) for p, c in _FORMAS]

# Letra inicial del NIF → formas jurídicas compatibles
FORMA_POR_LETRA = {
    "A": {"SA", "SAU", "SAL"},
    "B": {"SL", "SLU", "SLL", "SLNE"},
    "C": {"SC"},  # sociedades colectivas
    "D": set(),   # comanditarias
    "E": {"CB"},
    "F": {"SCOOP", "SCA"},
    "G": set(),   # asociaciones, fundaciones
    "H": set(),   # comunidades de propietarios
    "J": {"SC", "SCP"},
    "U": set(),   # UTE
    "V": set(),
}


def extraer_forma_juridica(nombre) -> tuple[str | None, str]:
    """Devuelve (forma, nombre_sin_forma_normalizado).
    'Construcciones Pérez, S.L.' → ('SL', 'construcciones perez')"""
    if nombre is None:
        return None, ""
    t = quitar_tildes(str(nombre)).lower()
    forma = None
    for rx, codigo in _FORMAS_RE:
        if rx.search(t):
            if forma is None:
                forma = codigo
            t = rx.sub(" ", t)
    return forma, normalizar_texto(t)


PALABRAS_VACIAS = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "al", "para", "por", "con", "the", "and", "i"}

# Palabras frecuentes en nombres de empresa que por sí solas NO identifican (doc 05 §2.3)
PALABRAS_GENERICAS = {
    "construcciones", "construccion", "constructora", "constructores", "reformas", "reforma",
    "servicios", "servicio", "grupo", "sur", "norte", "este", "oeste", "andalucia", "andaluza", "andaluz",
    "obras", "obra", "instalaciones", "instalacion", "instaladora", "ingenieria", "proyectos", "promociones",
    "inmobiliaria", "gestion", "soluciones", "empresa", "hermanos", "hnos", "asociados", "comercial",
    "industrial", "industriales", "tecnicas", "tecnica", "tecnicos", "multiservicios", "integrales", "integral",
    "mantenimiento", "mantenimientos", "electricidad", "electrica", "electricas", "fontaneria", "pintura", "pinturas",
    "carpinteria", "metalica", "metalicas", "estructuras", "excavaciones", "transportes", "general", "generales",
    "espana", "iberica", "global", "nuevas", "nueva", "hogar", "casa", "decoracion", "climatizacion",
    "sevilla", "huelva", "cadiz", "cordoba", "malaga", "granada", "jaen", "almeria", "madrid", "levante",
    "materiales", "suministros", "aluminios", "aluminio", "cristaleria", "rehabilitacion", "rehabilitaciones",
    "desarrollos", "inversiones", "consulting", "consultoria", "arquitectura", "diseno", "total", "plus",
}


def normalizar_nombre(nombre) -> str:
    """Nombre sin forma jurídica y sin palabras vacías, para comparar."""
    _, n = extraer_forma_juridica(nombre)
    return " ".join(w for w in n.split() if w not in PALABRAS_VACIAS)


def tokens_distintivos(nombre_norm: str) -> set[str]:
    return {w for w in nombre_norm.split() if w not in PALABRAS_GENERICAS and w not in PALABRAS_VACIAS and len(w) > 1}


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def similitud_nombres(a: str, b: str) -> float:
    """Mezcla 50/50 de token_set y token_sort (sobre nombres ya normalizados).
    Solo token_set daría 1,0 a 'construcciones perez' vs 'construcciones perez sevilla',
    que suelen ser empresas distintas; la mezcla lo baja a ~0,9."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    sort_a, sort_b = " ".join(sorted(ta)), " ".join(sorted(tb))
    token_sort = _ratio(sort_a, sort_b)
    inter = " ".join(sorted(ta & tb))
    t1 = (inter + " " + " ".join(sorted(ta - tb))).strip()
    t2 = (inter + " " + " ".join(sorted(tb - ta))).strip()
    token_set = max(_ratio(inter, t1), _ratio(inter, t2), _ratio(t1, t2)) if inter else _ratio(t1, t2)
    return round(0.5 * token_set + 0.5 * token_sort, 4)


# =============================================================================
# NIF / CIF / NIE
# =============================================================================
_LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
_LETRAS_CONTROL_CIF = "JABCDEFGHI"
_LETRAS_CIF = "ABCDEFGHJNPQRSUVW"


def _letra_dni(numero: int) -> str:
    return _LETRAS_DNI[numero % 23]


def _control_cif(siete_digitos: str) -> tuple[str, str]:
    """Devuelve (digito_control, letra_control) para los 7 dígitos centrales de un CIF."""
    d = [int(c) for c in siete_digitos]
    pares = d[1] + d[3] + d[5]
    impares = sum(sum(divmod(2 * x, 10)) for x in (d[0], d[2], d[4], d[6]))
    control = (10 - (pares + impares) % 10) % 10
    return str(control), _LETRAS_CONTROL_CIF[control]


def normalizar_nif(nif) -> str:
    if nif is None or (isinstance(nif, float) and math.isnan(nif)):
        return ""
    n = re.sub(r"[^A-Za-z0-9]", "", str(nif)).upper()
    if n.startswith("ES") and len(n) == 11:  # formato VAT intracomunitario
        n = n[2:]
    return n


def validar_nif(nif) -> dict:
    """Valida NIF de sociedad (CIF), DNI, NIE y NIF especiales K/L/M.
    Devuelve {nif, valido, tipo, persona_fisica, aviso}."""
    n = normalizar_nif(nif)
    r = {"nif": n, "valido": False, "tipo": None, "persona_fisica": None, "aviso": None}
    if not n:
        r["aviso"] = "vacío"
        return r
    if re.fullmatch(r"\d{8}[A-Z]", n):
        r.update(tipo="dni", persona_fisica=True, valido=n[-1] == _letra_dni(int(n[:8])))
    elif re.fullmatch(r"[XYZ]\d{7}[A-Z]", n):
        num = int(str("XYZ".index(n[0])) + n[1:8])
        r.update(tipo="nie", persona_fisica=True, valido=n[-1] == _letra_dni(num))
    elif re.fullmatch(r"[KLM]\d{7}[A-Z]", n):
        r.update(tipo="nif_especial", persona_fisica=True, valido=n[-1] == _letra_dni(int(n[1:8])))
    elif re.fullmatch(r"[" + _LETRAS_CIF + r"]\d{7}[0-9A-J]", n):
        digito, letra = _control_cif(n[1:8])
        r.update(tipo="sociedad", persona_fisica=False, valido=n[-1] in (digito, letra))
        if r["valido"]:
            if n[0] in "ABEH" and n[-1] == letra and letra != digito:
                r["aviso"] = "control con letra en tipo que suele usar dígito"
            elif n[0] in "NPQRSW" and n[-1] == digito:
                r["aviso"] = "control con dígito en tipo que suele usar letra"
    else:
        r["aviso"] = "formato no reconocido"
        return r
    if not r["valido"]:
        r["aviso"] = "dígito/letra de control incorrecto"
    return r


def forma_compatible_con_nif(forma: str | None, nif: str) -> bool | None:
    """None si no se puede juzgar; False si la letra del NIF contradice la forma jurídica."""
    if not forma or not nif or not nif[0].isalpha() or nif[0] in "XYZKLM":
        return None
    compatibles = FORMA_POR_LETRA.get(nif[0])
    if compatibles is None or not compatibles:
        return None
    return forma in compatibles


# =============================================================================
# Teléfono (España)
# =============================================================================
def normalizar_telefono(tel) -> dict:
    """→ {e164, valido, tipo: fijo|movil|especial|extranjero|None, aviso}"""
    r = {"e164": None, "valido": False, "tipo": None, "aviso": None}
    if tel is None or (isinstance(tel, float) and math.isnan(tel)):
        return r
    s = str(tel).strip()
    if isinstance(tel, float) and tel.is_integer():
        s = str(int(tel))
    s = re.sub(r"(ext|extensión|extension|ext\.)\s*\d+$", "", s, flags=re.I)
    digitos = re.sub(r"\D", "", s)
    if s.startswith("+") and not digitos.startswith("34"):
        r.update(e164="+" + digitos, tipo="extranjero", valido=8 <= len(digitos) <= 15, aviso="número no español: validar con libphonenumber")
        return r
    if digitos.startswith("0034"):
        digitos = digitos[4:]
    elif digitos.startswith("34") and len(digitos) == 11:
        digitos = digitos[2:]
    if len(digitos) != 9:
        r["aviso"] = f"longitud {len(digitos)} (se esperaban 9 dígitos)"
        return r
    p = digitos[0]
    if p in "67":
        tipo = "movil"
    elif digitos[:2] in ("80", "90"):
        tipo = "especial"
    elif p in "89":
        tipo = "fijo"
    else:
        r["aviso"] = "prefijo no válido en España"
        return r
    r.update(e164="+34" + digitos, valido=True, tipo=tipo)
    if tipo == "especial":
        r["aviso"] = "número de tarificación especial: no usar como señal de identidad"
    return r


# =============================================================================
# Email y dominios
# =============================================================================
PREFIJOS_GENERICOS = {
    "info", "informacion", "contacto", "contact", "hola", "hello", "admin", "administracion", "comercial",
    "ventas", "sales", "oficina", "office", "presupuestos", "presupuesto", "pedidos", "facturacion", "rrhh",
    "empleo", "recepcion", "atencioncliente", "clientes", "soporte", "support", "general", "gerencia",
    "direccion", "compras", "proyectos", "obras", "tecnico", "marketing", "prensa", "secretaria", "calidad",
    "logistica", "almacen", "taller", "reservas", "consultas", "correo", "mail", "web", "estudio", "central",
}
PROVEEDORES_GRATUITOS = {
    "gmail.com", "hotmail.com", "hotmail.es", "outlook.com", "outlook.es", "yahoo.com", "yahoo.es", "live.com",
    "icloud.com", "me.com", "msn.com", "telefonica.net", "movistar.es", "terra.es", "ono.com", "gmx.es",
    "gmx.com", "protonmail.com", "proton.me", "aol.com",
}
DOMINIOS_PLATAFORMA = {
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "google.com", "goo.gl", "g.page", "business.site", "negocio.site", "wixsite.com", "wix.com", "blogspot.com",
    "wordpress.com", "webnode.es", "jimdo.com", "jimdosite.com", "square.site", "linktr.ee", "sites.google.com",
    "paginasamarillas.es", "einforma.com", "infoempresa.com", "axesor.es", "empresia.es", "habitissimo.es",
    "cronoshare.com", "yelp.es", "tripadvisor.es", "milanuncios.com", "infocif.es", "iberinform.es",
    "librebor.me", "datoscif.es", "guiaempresa.universia.es", "cylex.es", "hotfrog.es", "wa.me", "whatsapp.com",
}
_SEGUNDO_NIVEL = {"com.es", "org.es", "nom.es", "gob.es", "edu.es", "co.uk", "com.ar", "com.mx", "com.co", "com.pe", "com.br", "com.pt"}


def extraer_dominio(url_o_email) -> str | None:
    """Dominio registrable: 'https://www.obras.perez.es/x' → 'perez.es'; 'a@b.com.es' → 'b.com.es'."""
    if url_o_email is None or (isinstance(url_o_email, float) and math.isnan(url_o_email)):
        return None
    s = str(url_o_email).strip().lower()
    if not s:
        return None
    if "@" in s and "://" not in s:
        host = s.split("@")[-1]
    else:
        host = re.sub(r"^[a-z]+://", "", s).split("/")[0].split("?")[0].split("#")[0].split(":")[0]
    host = host.strip(".")
    if host.startswith("www."):
        host = host[4:]
    partes = host.split(".")
    if len(partes) < 2 or not re.fullmatch(r"[a-z0-9.\-]+", host):
        return None
    if ".".join(partes[-2:]) in _SEGUNDO_NIVEL and len(partes) >= 3:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


def es_dominio_plataforma(dominio: str | None, host_completo: str | None = None) -> bool:
    if not dominio:
        return False
    if dominio in DOMINIOS_PLATAFORMA or dominio in PROVEEDORES_GRATUITOS:
        return True
    return bool(host_completo and any(host_completo.endswith(p) for p in ("sites.google.com",)))


def normalizar_email(email) -> dict:
    r = {"email": None, "valido": False, "dominio": None, "es_generico": None, "proveedor_gratuito": False}
    if email is None or (isinstance(email, float) and math.isnan(email)):
        return r
    e = str(email).strip().lower().replace("mailto:", "")
    e = re.sub(r"\s*\(?\s*arroba\s*\)?\s*", "@", e)
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", e):
        return r
    local, dom = e.split("@")
    r.update(email=e, valido=True, dominio=dom, proveedor_gratuito=dom in PROVEEDORES_GRATUITOS)
    base = re.split(r"[.\-_+0-9]", local)[0]
    # Genérico si el prefijo está en la lista. Si no, se trata como POSIBLE dato personal (criterio conservador, doc 06).
    r["es_generico"] = local in PREFIJOS_GENERICOS or base in PREFIJOS_GENERICOS
    return r


# =============================================================================
# Código postal y provincia
# =============================================================================
PROVINCIAS = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz",
    "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla",
    "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}
_ALIAS_PROVINCIA = {
    "araba": "01", "alava": "01", "vitoria": "01", "alacant": "03", "baleares": "07", "islas baleares": "07",
    "balears": "07", "mallorca": "07", "coruna": "15", "la coruna": "15", "a coruna": "15", "gerona": "17",
    "guipuzcoa": "20", "lerida": "25", "rioja": "26", "orense": "32", "principado de asturias": "33",
    "gran canaria": "35", "tenerife": "38", "santa cruz de tenerife": "38", "castello": "12",
    "castellon de la plana": "12", "valencia": "46", "vizcaya": "48", "nafarroa": "31",
    "comunidad foral de navarra": "31", "comunidad de madrid": "28", "region de murcia": "30",
}


def codigo_provincia(nombre) -> str | None:
    n = normalizar_texto(nombre)
    if not n:
        return None
    for cod, nom in PROVINCIAS.items():
        if normalizar_texto(nom) == n:
            return cod
    return _ALIAS_PROVINCIA.get(n)


def validar_cp(cp, provincia=None) -> dict:
    """Arregla el cero inicial perdido por Excel (4001 → 04001) y comprueba la provincia."""
    r = {"cp": None, "valido": False, "provincia_cp": None, "coherente_provincia": None, "aviso": None}
    if cp is None or (isinstance(cp, float) and math.isnan(cp)):
        return r
    s = str(int(cp)) if isinstance(cp, float) and cp.is_integer() else re.sub(r"\D", "", str(cp))
    if len(s) == 4:
        s = "0" + s
        r["aviso"] = "cero inicial restaurado"
    if not re.fullmatch(r"(0[1-9]|[1-4]\d|5[0-2])\d{3}", s):
        r["aviso"] = "código postal no válido"
        return r
    r.update(cp=s, valido=True, provincia_cp=PROVINCIAS[s[:2]])
    if provincia:
        cod = codigo_provincia(provincia)
        if cod:
            r["coherente_provincia"] = cod == s[:2]
            if not r["coherente_provincia"]:
                r["aviso"] = f"CP de {PROVINCIAS[s[:2]]} pero provincia indicada '{provincia}'"
    return r


# =============================================================================
# Distancia
# =============================================================================
def distancia_m(lat1, lon1, lat2, lon2) -> float | None:
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    if any(math.isnan(x) for x in (lat1, lon1, lat2, lon2)):
        return None
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# =============================================================================
# Registro normalizado
# =============================================================================
def _lista(v) -> list:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return []
    if isinstance(v, (list, tuple, set)):
        return [x for x in v if x is not None and str(x).strip()]
    return [x for x in re.split(r"[;,/|]| y ", str(v)) if x.strip()]


def normalizar_registro(reg: dict) -> dict:
    """Recibe un dict con claves estándar (nif, razon_social, nombre_comercial, forma_juridica, telefono(s),
    email(s), web, direccion, cp, municipio, provincia, lat, lon, place_id) y devuelve una versión normalizada."""
    forma_rs, rs_norm = extraer_forma_juridica(reg.get("razon_social"))
    _, nc_norm = extraer_forma_juridica(reg.get("nombre_comercial"))
    nif = validar_nif(reg.get("nif"))
    telefonos = [normalizar_telefono(t) for t in _lista(reg.get("telefonos") or reg.get("telefono"))]
    emails = [normalizar_email(e) for e in _lista(reg.get("emails") or reg.get("email"))]
    web = reg.get("web")
    dominio = extraer_dominio(web)
    host = str(web).lower() if web else None
    if dominio and es_dominio_plataforma(dominio, host):
        dominio_valido = None
    else:
        dominio_valido = dominio
    if not dominio_valido:  # si no hay web, usar el dominio de un email corporativo
        for e in emails:
            if e["valido"] and not e["proveedor_gratuito"] and not es_dominio_plataforma(e["dominio"]):
                dominio_valido = extraer_dominio(e["email"])
                break
    forma = (str(reg.get("forma_juridica")).upper().replace(".", "").replace(" ", "")
             if reg.get("forma_juridica") and str(reg.get("forma_juridica")) != "nan" else None) or forma_rs
    cp = validar_cp(reg.get("cp"), reg.get("provincia"))
    return {
        "nif": nif["nif"] or None,
        "nif_valido": nif["valido"] if nif["nif"] else None,
        "nif_tipo": nif["tipo"],
        "nif_aviso": nif["aviso"] if nif["nif"] else None,
        "persona_fisica": nif["persona_fisica"],
        "razon_social": reg.get("razon_social"),
        "nombre_comercial": reg.get("nombre_comercial"),
        "nombre_norm": " ".join(w for w in rs_norm.split() if w not in PALABRAS_VACIAS),
        "comercial_norm": " ".join(w for w in nc_norm.split() if w not in PALABRAS_VACIAS),
        "forma_juridica": forma,
        "forma_coherente_nif": forma_compatible_con_nif(forma, nif["nif"]) if nif["valido"] else None,
        "telefonos": sorted({t["e164"] for t in telefonos if t["valido"]}),
        "telefonos_especiales": sorted({t["e164"] for t in telefonos if t["valido"] and t["tipo"] == "especial"}),
        "telefonos_invalidos": [str(x) for x, t in zip(_lista(reg.get("telefonos") or reg.get("telefono")), telefonos) if not t["valido"]],
        "emails": sorted({e["email"] for e in emails if e["valido"]}),
        "emails_personales": sorted({e["email"] for e in emails if e["valido"] and not e["es_generico"]}),
        "dominio": dominio_valido,
        "cp": cp["cp"],
        "cp_aviso": cp["aviso"],
        "provincia": reg.get("provincia") or cp["provincia_cp"],
        "cod_provincia": (cp["cp"] or "")[:2] or codigo_provincia(reg.get("provincia")),
        "municipio": reg.get("municipio"),
        "lat": reg.get("lat"),
        "lon": reg.get("lon"),
        "place_id": reg.get("place_id") if reg.get("place_id") and str(reg.get("place_id")) != "nan" else None,
    }


# =============================================================================
# Comparación de dos registros (doc 05 §2.2-2.4)
# =============================================================================
def _mejor_similitud(a: dict, b: dict) -> tuple[float, bool]:
    """Máxima similitud entre las combinaciones de nombres y si comparten palabras distintivas."""
    na = [x for x in (a.get("nombre_norm"), a.get("comercial_norm")) if x]
    nb = [x for x in (b.get("nombre_norm"), b.get("comercial_norm")) if x]
    if not na or not nb:
        return 0.0, False
    mejor, distintivas = 0.0, False
    for x in na:
        for y in nb:
            s = similitud_nombres(x, y)
            if s > mejor:
                mejor = s
            if tokens_distintivos(x) & tokens_distintivos(y):
                distintivas = True
    return mejor, distintivas


def comparar(a: dict, b: dict, telefonos_compartidos: set | None = None) -> dict:
    """Compara dos registros NORMALIZADOS (salida de normalizar_registro).
    Devuelve {puntuacion, decision, regla, senales}."""
    compartidos = telefonos_compartidos or set()
    senales: list[str] = []
    sim, distintivas = _mejor_similitud(a, b)

    def resultado(p, regla):
        p = max(0.0, min(1.0, round(p, 3)))
        decision = "misma" if p >= UMBRAL_FUSION_AUTO else ("revision" if p >= UMBRAL_REVISION else "distinta")
        return {"puntuacion": p, "decision": decision, "regla": regla, "senales": senales, "similitud_nombre": sim}

    # --- Reglas duras ---
    if a.get("nif_valido") and b.get("nif_valido"):
        if a["nif"] != b["nif"]:
            senales.append(f"NIF distintos ({a['nif']} ≠ {b['nif']})")
            return resultado(0.0, "R1_nif_distinto")
        senales.append(f"NIF igual ({a['nif']})")
        if sim < 0.5 and not distintivas:
            senales.append("nombres muy distintos con mismo NIF: ¿NIF de un tercero (agencia web, gestoría)?")
            return resultado(0.70, "R2_nif_igual_nombres_distintos")
        return resultado(1.0, "R2_nif_igual")
    if a.get("place_id") and a.get("place_id") == b.get("place_id"):
        senales.append("mismo place_id de Google")
        return resultado(0.95, "R3_place_id")

    p = 0.0
    # --- Nombre ---
    if a.get("nombre_norm") or a.get("comercial_norm"):
        if b.get("nombre_norm") or b.get("comercial_norm"):
            if sim >= 0.95:
                aporte = PESOS["nombre_095"]
            elif sim >= 0.88:
                aporte = PESOS["nombre_088"]
            elif sim >= 0.80:
                aporte = PESOS["nombre_080"]
            elif sim < 0.50:
                aporte = PESOS["nombre_bajo"]
            else:
                aporte = 0.0
            if aporte > 0 and not distintivas:
                aporte = min(aporte, PESOS["nombre_solo_genericas"])
                senales.append("nombres parecidos pero solo con palabras genéricas en común")
            if aporte:
                senales.append(f"similitud de nombre {sim:.2f} ({aporte:+.2f})")
            p += aporte
    # --- Forma jurídica ---
    if a.get("forma_juridica") and b.get("forma_juridica") and a["forma_juridica"] != b["forma_juridica"]:
        p += PESOS["forma_distinta"]
        senales.append(f"formas jurídicas distintas ({a['forma_juridica']} vs {b['forma_juridica']})")
    # --- Dominio ---
    dominio_comun = bool(a.get("dominio") and a.get("dominio") == b.get("dominio"))
    if dominio_comun:
        p += PESOS["dominio"]
        senales.append(f"mismo dominio ({a['dominio']})")
    # --- Teléfono ---
    tel_comunes = (set(a.get("telefonos", [])) & set(b.get("telefonos", []))) - set(a.get("telefonos_especiales", [])) - compartidos
    if tel_comunes:
        p += PESOS["telefono"]
        senales.append(f"mismo teléfono ({', '.join(sorted(tel_comunes))})")
    # --- Email ---
    if set(a.get("emails", [])) & set(b.get("emails", [])):
        p += PESOS["email"]
        senales.append("mismo email")
    # --- Ubicación ---
    d = distancia_m(a.get("lat"), a.get("lon"), b.get("lat"), b.get("lon"))
    if d is not None:
        if d <= 50:
            p += PESOS["dist_50"]
        elif d <= 300:
            p += PESOS["dist_300"]
        elif d <= 2000:
            p += PESOS["dist_2000"]
        elif d > 50000:
            p += PESOS["dist_lejos"]
        senales.append(f"distancia {d:.0f} m")
    else:
        if a.get("cp") and a.get("cp") == b.get("cp"):
            p += PESOS["cp_igual"]
            senales.append(f"mismo CP ({a['cp']})")
        if a.get("cod_provincia") and b.get("cod_provincia") and a["cod_provincia"] != b["cod_provincia"]:
            p += PESOS["provincia_distinta"]
            senales.append("provincias distintas")
    if dominio_comun:
        p = max(p, PESOS["dominio_minimo"])
    return resultado(p, "puntuacion")
