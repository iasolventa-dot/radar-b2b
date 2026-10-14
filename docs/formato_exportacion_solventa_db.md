# Formato de exportación Radar B2B → Solventa DB («solventa-db», versión 2)

> **Versión 2 (2026-10-14)**: sustituye a la versión 1. Cada `<cliente>` es ahora una ficha de Solventa DB
> tal cual la guarda `data/clientes.json`: todos sus campos, en su orden, con sus formatos y vocabularios.
> Ya no lleva nada de la estructura de Radar: ni completitud, ni confianza, ni clasificación, ni evidencias.
> Eso sirve solo para filtrar búsquedas dentro de Radar. Lo que cambia respecto a v1 está al final.

Radar B2B exporta los resultados de una búsqueda como un XML para importarlo en **Solventa DB**
(`iasolventa-dot/solventa-db`, el mini-CRM de Solventa IA). Se importa como una **lista aparte**, con sus propias
fichas y contactos, sin tocar la lista principal (`data/clientes.json`).

- Generador: `worker/radar/exportacion/solventa.py`. Tests: `worker/tests/unit/test_exportacion_solventa.py`.
- Endpoint del worker: `GET /busquedas/{busqueda_id}/exportar/solventa-db`. Devuelve `application/xml` y se
  descarga como `radar-<peticion>.xml`.
- Panel: botón **«Exportar a Solventa DB»** en el detalle de cada búsqueda.
- Ejemplo con datos ficticios: `docs/ejemplo_exportacion_solventa_db.xml`.
- Instrucciones para adaptar el importador de Solventa DB: `docs/solventa_db_importacion_v2.md`.

## Qué empresas van

Las mismas que la tabla del panel y en el mismo orden: sin las descartadas por el filtro de sector o de autónomos.

## Estructura

```xml
<?xml version="1.0" encoding="UTF-8"?>
<exportacion origen="Radar B2B" formato="solventa-db" version="2" generado="2026-10-14T12:00:00+00:00">
  <lista radar-busqueda-id="UUID" nombre="fontaneros en Dos Hermanas" creada="ISO-8601" total="18">
    <descripcion>Zona: Dos Hermanas · Sector: Fontanería</descripcion>
  </lista>
  <clientes>
    <cliente>
      <campo nombre="Contacto">...</campo>          <!-- SIEMPRE los 37 campos, en este orden; vacíos como <campo nombre="X" /> -->
      ...
      <campo nombre="Fotos de la Empresa" />
      <ContactosAdicionales>                        <!-- opcional: mismo nombre y forma que el campo de Solventa -->
        <contacto><nombre/><cargo/><telefono/><email/></contacto>
      </ContactosAdicionales>
    </cliente>
  </clientes>
</exportacion>
```

| Elemento / atributo | Significado |
|---|---|
| `exportacion@formato`, `@version` | `solventa-db` y `2`. |
| `lista@nombre` | Nombre propuesto para la lista importada (la petición de la búsqueda). |
| `lista@radar-busqueda-id` | Id de la búsqueda en Radar. Sirve para detectar que se reimporta la misma búsqueda. |
| `lista@total` | Número de `<cliente>`. |
| `cliente` | Sin atributos. |
| `campo@nombre` | Nombre exacto del campo en Solventa DB. Van todos, también los vacíos. |
| `ContactosAdicionales/contacto` | Otras personas de la empresa, con la forma `{nombre, cargo, telefono, email}`. El `id` lo genera el importador. |

## Campos, en el orden de `lib/campos.ts::BLOQUES`

Los formatos y vocabularios son los que ya usan los 1.079 clientes de `data/clientes.json`. Se perfilaron el
2026-10-14 sin copiar ningún dato.

| Campo | Qué pone Radar |
|---|---|
| `Contacto` | Persona de más rango, con mayúscula inicial («Ruiz Bulnes Francisco Javier»). El BORME da los apellidos delante y no se reordenan, porque con apellidos compuestos sería adivinar. En un autónomo, el titular. |
| `Cargo` | Vocabulario de Solventa: `DIRECTOR GRAL` (administradores y consejeros del BORME, CEO, director general, presidente), `Propietario` (autónomo o titular), `Gerente`, `Socio` (también fundador), `Admon.` (administración, facturación, contabilidad), `RRHH`, `TECNICO` (técnico, ingeniero, arquitecto, jefe de obra). Un cargo que no encaja se deja tal cual, con mayúscula inicial. |
| `Email` | Email personal si lo hay; si no, el genérico (`info@`…). |
| `E-MAIL CORPORATIVO` | El genérico, si `Email` ya es personal; o un segundo email. |
| `TELEFONO 1` | **Móvil** (empieza por 6 o 7), 9 cifras sin +34. Vacío si no hay móvil, como en la mayoría de fichas de Solventa. |
| `TELEFONO 2` | **Fijo**, 9 cifras; si no hay fijo, un segundo móvil. |
| `Web` | `www.dominio.es`, sin `https://`. |
| `Razón Social` | En MAYÚSCULAS; si no se conoce, el nombre comercial. Nunca está vacía. |
| `NIF` | Mayúsculas, sin espacios ni guiones. En autónomos, el DNI. |
| `Dirección`, `CP`, `Población`, `Provincia` | Sede principal, con mayúsculas de nombre propio. Si falta la provincia, se deduce del CP. |
| `CNAE` | Código de 4 cifras si se conoce. Hoy casi nunca: Radar no lo guarda. |
| `ACTIVIDAD` | Objeto social en corto, como mucho 150 caracteres. Si es más largo, el texto completo va a `Observaciones`. |
| `SECTORES` | Sector de la búsqueda traducido a los valores de Solventa: `FONTANERIA`, `CONSTRUCCIÓN`, `ELECTRICIDAD , ENERGIA`, `PINTURA Y DECORACION`, `CARPINTERIA`, `CARPINTERIA METALICA`, `HOSTELERIA`, `TRANSPORTES Y LOGISTICA`, `LIMPIEZA`, `AUTOMOCIÓN`, `METAL`… Si no encaja con ninguno, el sector en mayúsculas. |
| `TRABAJADORES` | Número, si alguna fuente lo da (casi nunca). |
| `FACTURACION` | Vacío: Radar no tiene facturación. |
| `Asesoría`, `Contacto Asesoría`, `Teléfono Asesoría`, `Email Asesoría` | Vacíos. |
| `Estado` | `Lead`; `Extinguida` si la sociedad está extinguida o disuelta; `Inactiva` si está inactiva, en liquidación o en concurso. |
| `Agente Responsable`, `SERVICIO-PRODUCTO`, `FECHA GESTION`, `Gestiones`, `Resumen IA de Gestiones`, `Acción` | Vacíos: son de la gestión comercial. |
| `Origen Cliente` | `RADAR B2B`. |
| `Observaciones` | Lo que Radar sabe y no tiene campo en Solventa, una línea por dato (ver abajo). |
| `SEGURO (TIPO)`, `ASEGURADORA`, `POLIZAS`, `COMPAÑÍA ENERGÍA`, `CONTRATO ENERGÍA`, `Fotos de la Empresa` | Vacíos. |

### Qué va en `Observaciones`

Una línea por cada dato que haya, separadas por `\n`:

```
Importado de Radar B2B el 14/10/2026 (búsqueda «fontaneros en Dos Hermanas»).
Nombre comercial: Fontanería Ejemplo.
Forma jurídica: SL; constituida el 01/06/2015; estado registral: en liquidacion.
Cargos en el BORME: Garcia Prueba Ana (Administrador único); Pérez Modelo Juan (Consejero).
Otros teléfonos: 955000009.
Otros emails: obras@empresa.es.
Otras direcciones: Calle Otra 2, 41700, Dos Hermanas.
Objeto social: <texto completo, si no cupo en ACTIVIDAD>
Sector sin confirmar: revisar si encaja.
```

## Cambios respecto a la versión 1

| v1 | v2 |
|---|---|
| Solo se enviaban los campos con valor (unos 20 permitidos). | Siempre los 37 campos de `BLOQUES`, en su orden, vacíos incluidos. |
| `<cliente radar-id completitud clasificacion confianza>` | `<cliente>` sin atributos. |
| `<evidencias>` por campo | Eliminado. |
| `<contactos-adicionales>` | `<ContactosAdicionales>`: el mismo nombre que el campo de Solventa. |
| Cargo con la etiqueta del BORME («Administrador solidario») | Vocabulario de Solventa (`DIRECTOR GRAL`…); el cargo exacto del BORME va en `Observaciones`. |
| `TELEFONO 1`/`2` por orden de confianza | `TELEFONO 1` = móvil, `TELEFONO 2` = fijo. |
| `Web` con `https://` | `www.dominio`. |
| Razón social y contacto tal cual venían | Razón social en MAYÚSCULAS; contacto con mayúscula inicial. |
| `SECTORES` = sector de la búsqueda en mayúsculas | Traducido al vocabulario de Solventa. |
| `ACTIVIDAD` hasta 300 caracteres | Hasta 150; el texto completo va a `Observaciones`. |
| `Observaciones` con completitud y confianza | Sin datos internos de Radar; con forma jurídica, constitución, BORME, otros teléfonos, emails y direcciones. |
