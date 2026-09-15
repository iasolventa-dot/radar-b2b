"""Geocodificación con CartoCiudad (IGN) — plan de conexión de fuentes
pendientes (2026-09-14), la más sencilla de las seis: dato abierto (CC BY
4.0), sin clave de API, sin registro, sin coste. Verificado en vivo el
2026-09-14 contra `https://www.cartociudad.es/geocoder/api/geocoder/find`.

Deliberadamente conservador (principio 5, nunca inventar): solo se acepta
un resultado si el tipo de coincidencia es de precisión de calle o mejor
(`"portal"`: número exacto; `"callejero"`: la calle, sin número).

Se rechaza `"poblacion"` y cualquier otro tipo — comprobado en vivo:
pedir solo "Alcalá de Guadaíra, Sevilla" (sin calle, el caso más común
del BORME, que no da domicilio) devuelve `type="poblacion"` apuntando a
un barrio/urbanización CUALQUIERA del municipio ("Urbanización
Residencial Sevilla-Golf"), no al centro ni a nada representativo —
guardar ese punto como si fuera la sede real sería peor que no guardar
ninguno. Por eso `geocodificar()` ni intenta la llamada si no hay una
`direccion` (calle) que geocodificar.

No es responsabilidad de este módulo escribir nada en la base de
datos — eso es `radar.orquestador.bd`, que nunca llama a una API externa
por convención de este proyecto (separación de `fuentes/` vs
`orquestador/`). Este módulo solo geocodifica; quien llama (`radar.orquestador.procesar`)
decide qué hacer con el resultado.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

URL_FIND = "https://www.cartociudad.es/geocoder/api/geocoder/find"

# Tipos de coincidencia de CartoCiudad que se consideran fiables como
# ubicación de una sede — ver docstring del módulo. Otros tipos conocidos
# ("poblacion", "municipio", "provincia"...) se rechazan porque apuntan a
# un punto arbitrario dentro de una zona, no a la dirección pedida.
TIPOS_ACEPTABLES = {"portal", "callejero"}


@dataclass
class ResultadoGeocodificacion:
    lat: float
    lon: float
    tipo: str  # 'portal' | 'callejero' — precisión real del punto devuelto
    municipio_ine: str | None  # 'muniCode' de CartoCiudad, mismo formato que municipios.codigo_ine


def geocodificar(
    direccion: str | None,
    municipio: str | None = None,
    provincia: str | None = None,
    *,
    _transporte: httpx.BaseTransport | None = None,
) -> ResultadoGeocodificacion | None:
    """Síncrono a propósito: `radar.orquestador.bd`/`procesar_registro` son
    síncronos de punta a punta (psycopg sync) — llamar aquí con
    `httpx.Client` no introduce nada que ese código no tenga ya (la propia
    escritura en Postgres bloquea igual). `httpx.Client()` de usar y
    cerrar por llamada, no una conexión persistente: una búsqueda
    geocodifica como mucho unas pocas decenas de direcciones, no merece
    la pena gestionar el ciclo de vida de un cliente compartido para eso.

    `_transporte` es solo para tests (`httpx.MockTransport`, ver
    `worker/tests/unit/test_fuentes_cartociudad.py`) — nunca se pasa en
    producción, así que un guion bajo delante en vez de documentarlo como
    parte pública de la función.

    No intenta la llamada si no hay `direccion` — sin calle, CartoCiudad
    solo puede dar un punto de tipo `"poblacion"` (ver docstring del
    módulo), que se rechazaría igualmente al comprobar `TIPOS_ACEPTABLES`.
    Cualquier fallo (sin resultado, tipo de precisión insuficiente, la API
    caída, tiempo de espera agotado) devuelve `None` — nunca lanza: es
    "mejor esfuerzo", igual que el resto de normalización de direcciones
    de este proyecto (doc 02 §3/§6).
    """
    if not direccion:
        return None
    # Si municipio y provincia coinciden en texto (muy común en España: "Sevilla,
    # Sevilla", "Huelva, Huelva"...), no repetir el nombre en la consulta --
    # comprobado en vivo: "Calle Sierpes, Sevilla, Sevilla" resuelve a un
    # municipio de OTRA provincia (Málaga) en vez de a la Sevilla correcta,
    # mientras que "Calle Sierpes, Sevilla" sí resuelve bien. La repetición
    # literal confunde al ranking del geocodificador, no es un problema de
    # tildes/mayúsculas -- comparación simple basta, no hace falta normalizar.
    if municipio and provincia and municipio.strip().casefold() == provincia.strip().casefold():
        provincia = None
    partes = [p for p in (direccion, municipio, provincia) if p]
    if not partes:
        return None
    try:
        with httpx.Client(timeout=5.0, transport=_transporte) as cliente:
            respuesta = cliente.get(URL_FIND, params={"q": ", ".join(partes)})
    except httpx.HTTPError:
        return None
    if respuesta.status_code != 200:
        return None  # incluye 204 (sin resultados) y cualquier otro fallo
    try:
        datos = respuesta.json()
    except ValueError:
        return None
    if not isinstance(datos, dict) or datos.get("state") != 0:
        return None
    tipo = datos.get("type")
    if tipo not in TIPOS_ACEPTABLES:
        return None
    lat, lon = datos.get("lat"), datos.get("lng")
    if lat is None or lon is None:
        return None
    return ResultadoGeocodificacion(lat=float(lat), lon=float(lon), tipo=tipo, municipio_ine=datos.get("muniCode"))
