"""Normalización de dominios web y correos (doc 05 §1).

Un dominio propio (no de una plataforma, no de un proveedor de correo
gratuito) es una señal de identidad fuerte (doc 05 §2.3: +0,45 y mínimo
0,60 de puntuación de fusión). Por eso separamos dominios "reales" de
plataformas/directorios que no identifican a una empresa.
"""

from __future__ import annotations

import math
import re

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
    # Añadidos 2026-09-23 tras una búsqueda real (fontanería, San Sebastián de los Reyes): directorios,
    # marketplaces y alojamientos compartidos que se estaban guardando como si fueran "la empresa".
    "google.es", "maps.google.com", "houzz.es", "houzz.com", "prontopro.es", "trustlocal.es", "starofservice.es",
    "eleconomista.es", "empresite.eleconomista.es", "informa.es", "localo.site", "top-rated.online", "doctoralia.es",
    "fontaneros.es", "instaladoresdemadrid.com", "certicalia.com", "zaask.es", "tuugo.es", "infoisinfo.es",
    "misterwhat.es", "vulka.es", "infobel.com", "10best.es", "homify.es", "manomano.es", "leroymerlin.es",
    "amazon.es", "wallapop.com", "idealista.com", "fotocasa.es", "indeed.com", "infojobs.net", "glassdoor.es",
    "wikipedia.org", "boe.es", "gob.es", "scribd.com", "issuu.com", "slideshare.net", "pinterest.com",
    "pinterest.es", "tricantinos.com", "todoestaentrescantos.com",
    # 2026-09-24 (reformas, Alcobendas): directorio de contratistas cuya ficha se tomó por la web de la empresa.
    "profymarket.com",
}
_SEGUNDO_NIVEL = {
    "com.es", "org.es", "nom.es", "gob.es", "edu.es", "co.uk", "com.ar", "com.mx", "com.co", "com.pe",
    "com.br", "com.pt",
}


def extraer_dominio(url_o_email: object) -> str | None:
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
    host = host.removeprefix("www.")
    partes = host.split(".")
    if len(partes) < 2 or not re.fullmatch(r"[a-z0-9.\-]+", host):
        return None
    if ".".join(partes[-2:]) in _SEGUNDO_NIVEL and len(partes) >= 3:
        return ".".join(partes[-3:])
    return ".".join(partes[-2:])


# Rutas típicas de la ficha de una empresa dentro de un directorio o
# marketplace ("/contratistas/la-encina-sl", "/ficha/123"). No se incluye
# "/empresa/": muchas webs propias la usan para "quiénes somos".
_RX_RUTA_FICHA = re.compile(
    r"/(?:contratistas|directorio|ficha|fichas|listing|listings|companies|company-profile|proveedores|profesionales)/[^/?#]+",
    re.IGNORECASE,
)


def parece_ficha_de_directorio(url: str | None) -> bool:
    return bool(url and _RX_RUTA_FICHA.search(url))


def es_dominio_plataforma(dominio: str | None, host_completo: str | None = None) -> bool:
    if not dominio:
        return False
    if dominio in DOMINIOS_PLATAFORMA or dominio in PROVEEDORES_GRATUITOS:
        return True
    return bool(host_completo and any(host_completo.endswith(p) for p in ("sites.google.com",)))


def normalizar_email(email: object) -> dict:
    r: dict = {"email": None, "valido": False, "dominio": None, "es_generico": None, "proveedor_gratuito": False}
    if email is None or (isinstance(email, float) and math.isnan(email)):
        return r
    e = str(email).strip().lower().replace("mailto:", "")
    e = re.sub(r"\s*\(?\s*arroba\s*\)?\s*", "@", e)
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", e):
        return r
    local, dom = e.split("@")
    r.update(email=e, valido=True, dominio=dom, proveedor_gratuito=dom in PROVEEDORES_GRATUITOS)
    base = re.split(r"[.\-_+0-9]", local)[0]
    # Genérico si el prefijo está en la lista. Si no, se trata como POSIBLE
    # dato personal (criterio conservador, doc 06).
    r["es_generico"] = local in PREFIJOS_GENERICOS or base in PREFIJOS_GENERICOS
    return r
