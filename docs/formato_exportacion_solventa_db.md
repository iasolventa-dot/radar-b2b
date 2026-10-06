# Formato de exportación Radar B2B → Solventa DB («solventa-db», versión 1)

Radar B2B exporta los resultados de una búsqueda como un XML pensado para importarse en **Solventa DB**
(`iasolventa-dot/solventa-db`, el mini-CRM de Solventa IA) como una **lista aparte**, con sus propias
fichas y contactos, sin tocar la lista principal (`data/clientes.json`).

- Generador: `worker/radar/exportacion/solventa.py` (tests: `worker/tests/unit/test_exportacion_solventa.py`).
- Endpoint del worker: `GET /busquedas/{busqueda_id}/exportar/solventa-db` → `application/xml`, descarga
  `radar-<peticion>.xml`.
- Panel: botón **«Exportar a Solventa DB»** en el detalle de cada búsqueda (junto a «Exportar CSV»).
- Ejemplo con datos ficticios: `docs/ejemplo_exportacion_solventa_db.xml`.

## Qué empresas van

Las mismas y en el mismo orden que la tabla del panel (`resultados_busqueda()`): sin las descartadas por el
filtro de sector o de autónomos, de más a menos completas (contacto, nombre, CIF, teléfono y email).

## Estructura

```xml
<?xml version="1.0" encoding="UTF-8"?>
<exportacion origen="Radar B2B" formato="solventa-db" version="1" generado="2026-10-06T12:00:00+00:00">
  <lista radar-busqueda-id="UUID" nombre="fontaneros en Dos Hermanas" creada="ISO-8601" total="18">
    <descripcion>Zona: Dos Hermanas · Sector: Fontanería</descripcion>
  </lista>
  <clientes>
    <cliente radar-id="UUID" completitud="5" clasificacion="relevante" confianza="0.86">
      <campo nombre="Razón Social">...</campo>
      <campo nombre="NIF">...</campo>
      ...
      <contactos-adicionales>          <!-- opcional -->
        <contacto><nombre/><cargo/><telefono/><email/></contacto>
      </contactos-adicionales>
      <evidencias>                     <!-- opcional, informativo -->
        <evidencia campo="NIF" fuente="..." url="..." fecha="AAAA-MM-DD"/>
      </evidencias>
    </cliente>
  </clientes>
</exportacion>
```

| Elemento / atributo | Significado |
|---|---|
| `exportacion@formato`, `@version` | Siempre `solventa-db` y `1`. El importador debe rechazar otros valores. |
| `lista@nombre` | Nombre propuesto para la lista importada (la petición de la búsqueda). |
| `lista@radar-busqueda-id` | Id de la búsqueda en Radar: sirve para detectar reimportaciones. |
| `lista@total` | Número de `<cliente>`. |
| `cliente@radar-id` | Id de la empresa en Radar (estable entre exportaciones). |
| `cliente@completitud` | 0-5: cuántos de contacto, nombre, CIF, teléfono y email tiene. |
| `cliente@clasificacion` | `relevante`, `dudoso` (Radar no pudo confirmar el sector) o vacío (sin revisar). |
| `cliente@confianza` | 0.00-1.00, confianza global de Radar en la ficha (puede faltar). |
| `campo@nombre` | **Nombre exacto del campo en Solventa DB.** Solo se exportan campos con valor. |
| `contactos-adicionales/contacto` | Otras personas de la empresa → `ContactosAdicionales` de Solventa DB. |
| `evidencias/evidencia` | De qué fuente sale cada dato (`campo` usa el nombre de Solventa DB). |

## Campos (`<campo nombre="...">`)

Todos con los nombres y formatos que ya usa `data/clientes.json` de Solventa DB:

| Campo | Contenido y formato |
|---|---|
| `Razón Social` | Razón social; si no se conoce, nombre comercial. **Siempre presente.** |
| `NIF` | NIF/CIF en mayúsculas (`B12345678`; autónomos: DNI). |
| `Contacto`, `Cargo` | Contacto preferente: el cargo de la web (gerente, CEO…) o el administrador de mayor jerarquía del BORME (`Administrador único`, `Presidente`…). En autónomos, el titular con cargo `Propietario`. |
| `TELEFONO 1`, `TELEFONO 2` | Teléfonos españoles de 9 cifras sin +34 (`954123456`); los extranjeros, con su prefijo. |
| `Email` | Email del contacto: uno personal si lo hay; si no, el genérico (`info@`…). |
| `E-MAIL CORPORATIVO` | Otro email (genérico) si además hay uno personal. |
| `Web` | `https://dominio`. |
| `Dirección`, `CP`, `Población`, `Provincia` | Sede principal; provincia por nombre (`Sevilla`). |
| `CNAE` | Código CNAE (4 cifras) si se conoce. |
| `ACTIVIDAD` | Objeto social (máx. 300 caracteres). |
| `SECTORES` | Sector de la búsqueda en mayúsculas (`FONTANERÍA`). |
| `TRABAJADORES` | Número de empleados si alguna fuente lo da (casi nunca). |
| `Estado` | Siempre `Lead`. |
| `Origen Cliente` | Siempre `RADAR B2B`. |
| `Observaciones` | Fecha de importación, búsqueda, completitud, confianza, nombre comercial y aviso si el sector es dudoso. |

No se exportan los campos propios de la gestión comercial de Solventa (`Agente Responsable`, `Gestiones`,
`FECHA GESTION`, seguros, energía, `FACTURACION`…): el importador los deja vacíos.
