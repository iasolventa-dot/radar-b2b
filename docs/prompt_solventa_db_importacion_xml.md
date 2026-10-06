# Prompt para Claude Code en el proyecto Solventa DB — importar listas XML de Radar B2B

> Copia todo lo que hay debajo de la línea y pégalo en Claude Code dentro de `C:\Users\32759\solventa-db`.

---

Quiero que Solventa DB pueda **importar listas en XML exportadas desde Radar B2B** (mi otra aplicación, que busca y verifica empresas). Cada XML importado debe convertirse en una **lista aparte**, con **sus propias fichas y sus propios contactos**, **separada de la lista principal** («Todos», `data/clientes.json`): importar no debe añadir ni modificar nada en `data/clientes.json` ni en `data/listas.json`.

Antes de empezar: lee `CLAUDE.md`, `PROJECT_STATUS.md` y la skill `.claude/skills/solventa-db-conventions/`, haz `git pull --no-rebase` (la producción escribe commits en `data/*.json`) y respeta todas sus convenciones: sin base de datos (solo ficheros JSON en el repo vía `lib/github.ts`), cada acción del usuario = un commit con mensaje en español, los 409 de GitHub se traducen con `errorResponse` de `lib/api.ts`, quirks de PowerShell con las carpetas `[id]`, interfaz en español con los tokens de `app/globals.css` y los componentes de `components/ui/`.

## 1. El formato que llega (lo genera Radar B2B; no lo cambies)

Ejemplo real con datos ficticios: `C:\Users\32759\radar-b2b\docs\ejemplo_exportacion_solventa_db.xml` (léelo y cópialo a `docs/ejemplo_radar.xml` de este repo para probar). Especificación completa: `C:\Users\32759\radar-b2b\docs\formato_exportacion_solventa_db.md`.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<exportacion origen="Radar B2B" formato="solventa-db" version="1" generado="ISO-8601">
  <lista radar-busqueda-id="UUID" nombre="fontaneros en Dos Hermanas" creada="ISO-8601" total="18">
    <descripcion>Zona: Dos Hermanas · Sector: Fontanería</descripcion>
  </lista>
  <clientes>
    <cliente radar-id="UUID" completitud="0-5" clasificacion="relevante|dudoso|" confianza="0.00-1.00">
      <campo nombre="Razón Social">...</campo>        <!-- siempre presente -->
      <campo nombre="NIF">...</campo>                 <!-- solo se envían campos con valor -->
      ...
      <contactos-adicionales>                          <!-- opcional -->
        <contacto><nombre/><cargo/><telefono/><email/></contacto>
      </contactos-adicionales>
      <evidencias>                                     <!-- opcional, informativo -->
        <evidencia campo="NIF" fuente="..." url="..." fecha="AAAA-MM-DD"/>
      </evidencias>
    </cliente>
  </clientes>
</exportacion>
```

- `<campo nombre="X">` usa **exactamente los nombres de campo de `data/clientes.json`**, ya en vuestro formato (teléfono de 9 cifras sin +34, NIF en mayúsculas, provincia por nombre, `Web` con `https://`). Nombres posibles: `Razón Social`, `NIF`, `Contacto`, `Cargo`, `TELEFONO 1`, `TELEFONO 2`, `Email`, `E-MAIL CORPORATIVO`, `Web`, `Dirección`, `CP`, `Población`, `Provincia`, `CNAE`, `ACTIVIDAD`, `SECTORES`, `TRABAJADORES`, `Estado` (siempre `Lead`), `Origen Cliente` (siempre `RADAR B2B`), `Observaciones`.
- `Contacto`/`Cargo`/`TELEFONO 1`/`Email` son el **contacto preferente** (igual que en vuestro modelo de `lib/contactos.ts`).
- `<contactos-adicionales>` corresponde a vuestro campo `ContactosAdicionales` (`{id, nombre, cargo, telefono, email}`): genera un `id` (uuid) para cada uno al importar.
- Los clientes vienen ordenados de más a menos completos (`completitud` = cuántos tiene de contacto, nombre, CIF, teléfono y email).
- Rechaza con un mensaje claro cualquier XML cuyo `formato` no sea `solventa-db` o cuya `version` no sea `1`, que no sea XML válido o que tenga un `<cliente>` sin `Razón Social`.
- Ignora (sin fallar) cualquier `campo@nombre` que no esté en la lista de arriba: así una versión futura de Radar con campos nuevos no rompe el importador.

## 2. Almacenamiento (nuevo, separado de clientes.json y listas.json)

- **`data/importaciones.json`** (índice; puede no existir → usa `getFileRawIfExists`):
  ```json
  [{ "id": "uuid", "nombre": "fontaneros en Dos Hermanas", "origen": "radar-b2b",
     "radarBusquedaId": "UUID", "descripcion": "Zona: ... · Sector: ...", "total": 18,
     "archivo": "data/importaciones/<id>.json", "archivoOriginal": "radar-fontaneros-en-dos-hermanas.xml",
     "importadoEn": "ISO-8601" }]
  ```
- **`data/importaciones/<id>.json`** (una por lista importada):
  ```json
  { "id": "uuid", "nombre": "...", "origen": "radar-b2b", "radarBusquedaId": "UUID", "descripcion": "...",
    "importadoEn": "ISO-8601", "clientes": [ /* fichas */ ] }
  ```
  Cada ficha tiene **la misma forma que un cliente de `data/clientes.json`**: `id` (uuid nuevo) + **todos** los campos base inicializados a `""` (los de `lib/campos.ts::BLOQUES`) + los valores que traiga el XML + `ContactosAdicionales` (si hay) + un bloque propio:
  ```json
  "radar": { "id": "radar-id", "completitud": 5, "clasificacion": "relevante", "confianza": 0.86,
             "evidencias": [{ "campo": "NIF", "fuente": "...", "url": "...", "fecha": "..." }] },
  "yaEnTodosId": "uuid-del-cliente-en-clientes.json"   // solo si ya existe en «Todos» (ver abajo)
  ```
  Así `ClientesTable`, `ClienteModal`, `ClienteForm`, `lib/contactos.ts` (incluido `promoverAPreferente`), `lib/csv.ts` e `ImprimirContactos` funcionan con estas fichas sin cambios en su lógica.
- Añade en `lib/github.ts` los wrappers: leer/escribir el índice, leer/escribir una importación y **borrar** un fichero (Contents API `DELETE` con `sha`).
- **Ya existe en «Todos»**: al importar, compara cada ficha con `data/clientes.json` (sin los de la papelera) por **NIF normalizado** (mayúsculas, sin espacios/puntos/guiones; si no hay NIF, por razón social normalizada sin tildes ni forma jurídica). Si coincide, guarda `yaEnTodosId`. No modifiques el cliente de «Todos».
- **Reimportar la misma búsqueda** (mismo `radarBusquedaId`): pregunta si **reemplazar** la lista existente (sustituye sus fichas manteniendo su `id` y su nombre) o **crear otra**.
- Orden de escritura al crear: primero el fichero de la importación, luego el índice (si falla el índice, el fichero huérfano no rompe nada).
- Límite: el cuerpo de una petición a una función de Vercel es de ~4,5 MB. Una exportación de Radar tiene como mucho 300 empresas (~500 KB), así que cabe; aun así, rechaza con mensaje claro un XML de más de 4 MB.

## 3. Rutas API

- `GET /api/importaciones` → índice.
- `POST /api/importaciones` → recibe `{ nombre, archivoOriginal, modo: "nueva" | "reemplazar", lista, clientes }` (el XML ya parseado en el navegador, ver §4); **vuelve a validar en el servidor** (formato, versión, `Razón Social`, lista blanca de campos, longitud máxima razonable de cada valor); crea/reemplaza y devuelve la importación. Commit: `Importar lista XML de Radar B2B: <nombre> (<N> empresas)`.
- `GET /api/importaciones/[id]` → la importación completa.
- `PUT /api/importaciones/[id]` → renombrar. `DELETE /api/importaciones/[id]` → borra fichero + entrada del índice.
- `PUT /api/importaciones/[id]/clientes/[clienteId]` → editar la ficha. `DELETE` → quitarla de esa lista.
- Contactos de una ficha importada (añadir/editar/eliminar/preferente), reutilizando `lib/contactos.ts`, con las mismas rutas que ya tenéis para `clientes/[id]/contactos/...` pero colgando de `importaciones/[id]/clientes/[clienteId]/contactos/...`.
- `POST /api/importaciones/[id]/pasar-a-todos` → copia las fichas seleccionadas a `data/clientes.json` con `id` nuevo (sin el bloque `radar` ni `yaEnTodosId`), salta las que ya tienen `yaEnTodosId`, y marca en la importación `pasadoATodosId`. Commit: `Pasar a Todos desde <nombre>: N empresas`.

## 4. Interfaz

- Botón **«Importar XML de Radar B2B»** junto a la gestión de listas. Abre un modal: selector de archivo `.xml` → se parsea **en el navegador con `DOMParser`** (sin dependencias nuevas) → vista previa: nombre (editable), descripción, nº de empresas, reparto de completitud (5/5, 4/5…), cuántas ya están en «Todos», errores encontrados → Confirmar.
- En las pestañas (`ListasTabs`), un **grupo aparte «Importadas»** con cada lista importada (icono distinto a las listas normales), que abre `/importaciones/[id]`.
- `/importaciones/[id]`: la misma tabla de clientes, con:
  - columna **Completitud** (0-5 puntos) y orden por defecto completitud ↓;
  - insignia **«Ya en Todos»** (enlace a la ficha principal) y **«Sector dudoso»** si `radar.clasificacion = "dudoso"`;
  - acciones: editar ficha y contactos, quitar de la lista, **pasar a Todos** (selección múltiple), exportar CSV, imprimir, renombrar y eliminar la lista;
  - **sin** papelera ni acciones que escriban en `data/clientes.json` (salvo «Pasar a Todos»).
- En `ClienteModal`, si la ficha tiene `radar`, una sección **«Origen de los datos (Radar B2B)»** con completitud, confianza y la tabla de evidencias (campo, fuente, enlace, fecha).
- Fuera de alcance por ahora: sincronizar las listas importadas con Acumbamail (dilo en `ROADMAP.md` como siguiente paso).

## 5. Verificación (obligatoria antes de dar por terminado)

1. `npm run lint` y `npm run build` sin errores.
2. En local (`npm run dev`), importar `docs/ejemplo_radar.xml`. **Ojo: en local la app escribe en el repo real de GitHub**: avísame antes de importar y, al terminar las pruebas, elimina la lista de prueba desde la propia interfaz.
3. Comprobar: la lista aparece en «Importadas» con 3 empresas ordenadas 5/5, 4/5, 2/5; la primera tiene contacto preferente «Luis Ejemplo (Gerente)» y un contacto adicional «GARCIA PRUEBA ANA (Administrador único)»; el autónomo tiene `Contacto` = su nombre y `Cargo` = `Propietario`; `data/clientes.json` y `data/listas.json` **no** cambian; editar un contacto, marcarlo preferente, reimportar (reemplazar) y eliminar la lista funcionan y generan sus commits.
4. Un XML con `version="2"`, uno mal formado y uno sin `Razón Social` dan un error claro y no escriben nada.
5. Actualiza `PROJECT_STATUS.md` (modelo de datos de importaciones, rutas, pantallas) y haz commit + push.
