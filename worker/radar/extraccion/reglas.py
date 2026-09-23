"""Extracción por reglas (sin LLM) de NIF, razón social, datos registrales,
teléfonos, emails y códigos postales del texto de un aviso legal / página
de contacto (doc 02 §5, doc 04 §3).

Puerto directo de la skill `verificacion-empresas-es`
(`scripts/extraer_datos_legales.py`), reemplazando su `lib_empresas` por
los módulos ya existentes de `radar.normalizacion`. Si cambias una regla
aquí, cámbiala también en esa skill (el doc 05, cabecera, ya pide lo mismo
para normalización/resolución).

La LSSI (art. 10) obliga a publicar denominación social, NIF, domicilio y
datos registrales, así que el aviso legal es el "puente de identidad"
entre dominio/nombre comercial y NIF/razón social. Este módulo SOLO usa
reglas deterministas; `radar.extraccion.llm` es el respaldo con modelo,
que solo se llama si esto no basta (doc 04 §3, paso 3).
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from radar.normalizacion.dominio import normalizar_email
from radar.normalizacion.nif import validar_nif
from radar.normalizacion.telefono import normalizar_telefono

RX_NIF = re.compile(
    r"(?<![A-Z0-9])(?:ES[\s\-]?)?("
    r"[ABCDEFGHJNPQRSUVW][\s.\-]?\d{2}[\s.\-]?\d{3}[\s.\-]?\d{2}[\s.\-]?[0-9A-J]"
    r"|\d{2}[\s.]?\d{3}[\s.]?\d{3}[\s\-]?[A-Z]"
    r"|[XYZKLM][\s\-]?\d{7}[\s\-]?[A-Z])(?![A-Z0-9])",
    re.IGNORECASE,
)
RX_TEL = re.compile(r"(?<!\d)(?:\+34|0034)?[\s.\-]?\(?[6789]\d{2}\)?(?:[\s.\-]?\d){6}(?!\d)")
RX_EMAIL = re.compile(
    r"[a-z0-9._%+\-]+\s*(?:@|\[at\]|\(at\)|\(arroba\)|\sarroba\s)\s*[a-z0-9.\-]+\.[a-z]{2,}", re.IGNORECASE
)
RX_CP = re.compile(r"(?<!\d)((?:0[1-9]|[1-4]\d|5[0-2])\d{3})(?!\d)")
RX_REGISTRO = re.compile(
    r"Registro\s+Mercantil\s+de\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]*(?:[\s\-](?:de\s+|del\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)"
    r"[\s,.;:]*.{0,40}?Tomo\s*:?\s*([\d.]*\d).{0,40}?Folio\s*:?\s*(\d+)"
    r".{0,60}?Hoja\s*(?:n[º°o.]*\s*)?:?\s*([A-Z]{1,2}[\s\-]?\d[\d.]*\d|[A-Z]{1,2}[\s\-]?\d)",
    re.IGNORECASE | re.DOTALL,
)
FORMAS = (
    r"(?:S\.?\s?L\.?\s?U\.?|S\.?\s?L\.?\s?L\.?|S\.?\s?L\.?|S\.?\s?A\.?\s?U\.?|S\.?\s?A\.?"
    r"|S\.?\s?Coop\.?(?:\s?And\.?)?|Sociedad\s+Limitada|Sociedad\s+An[oó]nima)"
)
RX_RAZON = re.compile(r"([A-ZÁÉÍÓÚÑ0-9][\wÁÉÍÓÚÑáéíóúñ&'.\- ]{2,80}?,?\s" + FORMAS + r")(?=[\s,.;:)]|$)")
RX_ETIQUETA_RAZON = re.compile(
    r"(?:denominaci[oó]n\s+social|raz[oó]n\s+social|titular(?:\s+de\s+(?:la|este|esta)\s+"
    r"(?:web|sitio(?:\s+web)?|p[aá]gina(?:\s+web)?))?|(?:web|sitio|p[aá]gina)\s+(?:es\s+)?propiedad\s+de)"
    r"\s*(?:[:\-]|\ses\b|\ssiendo\b)\s*([^\n;|(]{3,100})",
    re.IGNORECASE,
)
RX_AGENCIA = re.compile(
    r"(dise[ñn]o(?:\s+y\s+desarrollo)?\s+web|desarrollado\s+por|dise[ñn]ado\s+por|web\s+creada\s+por|powered\s+by)",
    re.IGNORECASE,
)


def html_a_texto(contenido: str) -> str:
    """HTML → texto visible plano, quitando script/style y colapsando espacios."""
    if "<" in contenido and ">" in contenido:
        contenido = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", contenido)
        contenido = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", contenido)
        contenido = re.sub(r"(?s)<[^>]+>", " ", contenido)
    texto = html_lib.unescape(contenido)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


def _cerca(texto: str, pos: int, radio: int = 250) -> str:
    return texto[max(0, pos - radio) : pos + radio]


@dataclass
class NifEncontrado:
    nif: str
    tipo: str | None
    etiquetado_como_nif: bool
    cerca_de_mencion_agencia: bool


@dataclass
class EmailEncontrado:
    email: str
    es_generico: bool
    del_dominio: bool


@dataclass
class RegistroMercantilEncontrado:
    registro: str
    tomo: str
    folio: str
    hoja: str


@dataclass
class DatosLegalesExtraidos:
    nifs: list[NifEncontrado] = field(default_factory=list)
    nifs_invalidos_etiquetados: list[str] = field(default_factory=list)
    razones_sociales: list[str] = field(default_factory=list)
    registro_mercantil: RegistroMercantilEncontrado | None = None
    telefonos: list[str] = field(default_factory=list)
    emails: list[EmailEncontrado] = field(default_factory=list)
    codigos_postales: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def nif_titular(self) -> str | None:
        """El NIF más probable del titular (doc 04 §3): el primero de la
        lista ya viene ordenado para preferir un NIF etiquetado como tal,
        lejos de menciones de agencia/diseño web."""
        for n in self.nifs:
            if not n.cerca_de_mencion_agencia:
                return n.nif
        return None

    @property
    def necesita_llm(self) -> bool:
        """Doc 04 §3 / skill prompts.md #3: llamar al LLM de respaldo solo
        si faltan NIF, razón social o domicilio, o hay varios NIF."""
        return (
            not self.nif_titular
            or not self.razones_sociales
            or not self.codigos_postales
            or len(self.nifs) > 1
        )



# Frases de texto legal que el regex de "Titular: ..." a veces toma como si
# fueran el nombre (visto en vivo 2026-09-23: razón social = "propietario de
# todos los derechos de propiedad intelectual e industrial de su página web").
_RX_NO_ES_NOMBRE = re.compile(
    r"derechos|propiedad intelectual|p[aá]gina web|sitio web|presente (?:sitio|p[aá]gina|aviso)|usuario|"
    r"condiciones|aviso legal|pol[ií]tica de|responsable del|datos personales|cookies",
    re.IGNORECASE,
)
_RX_NIF_DELANTE = re.compile(r"^[A-Za-z]?\d{7,8}[A-Za-z]?[\s.,:;-]+")


def limpiar_razon_social(c: str | None) -> str | None:
    """Normaliza una razón social candidata o devuelve `None` si no parece un
    nombre de empresa (texto legal, demasiado larga)."""
    if not c:
        return None
    c = re.sub(r"^(?:la\s+empresa|la\s+sociedad|el\s+titular|esta\s+web\s+es\s+propiedad\s+de|propiedad\s+de)\s+", "", c, flags=re.IGNORECASE)
    c = _RX_NIF_DELANTE.sub("", c.strip())
    c = re.sub(r"\s+", " ", c).strip(" ,:;-").lstrip(".")
    if not (3 <= len(c) <= 100) or len(c.split()) > 12 or _RX_NO_ES_NOMBRE.search(c):
        return None
    return c


def extraer(texto: str, dominio: str | None = None) -> DatosLegalesExtraidos:
    res = DatosLegalesExtraidos()

    # --- NIF (solo los que pasan el dígito de control) ---
    vistos: set[str] = set()
    candidatos_nif: list[tuple[NifEncontrado, int]] = []
    for m in RX_NIF.finditer(texto):
        v = validar_nif(m.group(1))
        if not v["valido"]:
            if re.search(r"(?:C\.?\s?I\.?\s?F|N\.?\s?I\.?\s?F)\.?\s*:?\s*$", texto[max(0, m.start() - 12) : m.start()], re.IGNORECASE):
                res.nifs_invalidos_etiquetados.append(v["nif"])
            continue
        if v["nif"] in vistos:
            continue
        vistos.add(v["nif"])
        contexto = _cerca(texto, m.start(), 120)
        etiquetado = bool(re.search(r"C\.?\s?I\.?\s?F|N\.?\s?I\.?\s?F|identificaci[oó]n\s+fiscal", contexto, re.IGNORECASE))
        cerca_agencia = bool(RX_AGENCIA.search(_cerca(texto, m.start(), 150)))
        candidatos_nif.append(
            (NifEncontrado(nif=v["nif"], tipo=v["tipo"], etiquetado_como_nif=etiquetado, cerca_de_mencion_agencia=cerca_agencia), m.start())
        )
    candidatos_nif.sort(key=lambda par: (par[0].cerca_de_mencion_agencia, not par[0].etiquetado_como_nif, par[1]))
    res.nifs = [n for n, _ in candidatos_nif]

    if res.nifs_invalidos_etiquetados:
        res.avisos.append("NIF con dígito de control incorrecto publicado en la web (posible errata): no usar sin confirmar")
    if len(res.nifs) > 1:
        res.avisos.append("varios NIF válidos: puede haber datos de la agencia web, de un grupo o de un cliente; decidir el titular")
    if any(n.cerca_de_mencion_agencia for n in res.nifs):
        res.avisos.append("hay un NIF junto a una mención de diseño/desarrollo web: probablemente es de la agencia")

    # --- Razón social: etiquetas explícitas y nombres con forma jurídica cerca del NIF principal ---
    candidatas: list[tuple[float, str]] = []
    for m in RX_ETIQUETA_RAZON.finditer(texto):
        c = m.group(1)
        mf = RX_RAZON.search(c)
        candidatas.append((0.0, (mf.group(1) if mf else c.split(",")[0]).strip(" .,:")))
    ref = next((pos for n, pos in candidatos_nif if not n.cerca_de_mencion_agencia), None)
    for m in RX_RAZON.finditer(texto):
        if RX_AGENCIA.search(texto[max(0, m.start() - 80) : m.start()]):
            continue
        distancia = abs(m.start() - ref) if ref is not None else float(m.start())
        candidatas.append((1 + distancia / 10000, m.group(1).strip(" .,:")))
    ordenadas = [c for _, c in sorted(candidatas, key=lambda par: par[0])]
    limpias: list[str] = []
    for c in ordenadas:
        c = limpiar_razon_social(c)
        if c and c.lower() not in [x.lower() for x in limpias]:
            limpias.append(c)
    res.razones_sociales = limpias[:5]

    # --- Registro mercantil ---
    m_registro = RX_REGISTRO.search(texto)
    if m_registro:
        res.registro_mercantil = RegistroMercantilEncontrado(
            registro=m_registro.group(1).strip(), tomo=m_registro.group(2), folio=m_registro.group(3),
            hoja=re.sub(r"\s", "", m_registro.group(4)).rstrip("."),
        )

    # --- Teléfonos, emails, CP ---
    tels: list[str] = []
    for m in RX_TEL.finditer(texto):
        t = normalizar_telefono(m.group(0))
        if t["valido"] and t["e164"] not in tels:
            tels.append(t["e164"])
    res.telefonos = tels

    emails: list[EmailEncontrado] = []
    vistos_email: set[str] = set()
    for m in RX_EMAIL.finditer(texto):
        e = normalizar_email(m.group(0))
        if e["valido"] and e["email"] not in vistos_email:
            vistos_email.add(e["email"])
            emails.append(
                EmailEncontrado(
                    email=e["email"], es_generico=bool(e["es_generico"]),
                    del_dominio=bool(dominio and e["dominio"] and e["dominio"].endswith(dominio)),
                )
            )
    res.emails = emails
    res.codigos_postales = sorted(set(RX_CP.findall(texto)))[:5]
    if dominio and emails and not any(e.del_dominio for e in emails):
        res.avisos.append(f"ningún email pertenece al dominio {dominio}")
    return res
