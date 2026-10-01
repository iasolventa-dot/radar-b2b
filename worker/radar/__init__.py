"""Radar B2B — worker de descubrimiento, verificación y resolución de entidades.

Ver docs/02_arquitectura_tecnica.md para el flujo completo y
docs/08_registro_decisiones.md para el estado y las decisiones vigentes.
"""

__version__ = "0.1.0"


def _usar_certificados_del_sistema() -> None:
    """Verifica HTTPS con el almacén de certificados del sistema operativo en
    vez de la lista propia de Python (certifi).

    Visto en vivo 2026-10-01: el antivirus (Kaspersky) inspecciona parte del
    tráfico HTTPS firmándolo con su propia raíz, instalada en Windows. El
    navegador confía en ella; Python no, y las llamadas a Apify fallaban de
    forma intermitente con "CERTIFICATE_VERIFY_FAILED: self-signed certificate
    in certificate chain". Con `truststore` se sigue verificando todo igual de
    estricto, pero contra los mismos certificados que usa Windows/Chrome.
    """
    try:
        import truststore
    except ImportError:  # pragma: no cover -- dependencia declarada en pyproject
        return
    truststore.inject_into_ssl()


_usar_certificados_del_sistema()
