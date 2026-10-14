# Solventa DB — cambio del importador de listas XML de Radar B2B (formato v1 → v2)

> Pega todo lo que hay debajo de la línea en Claude Code, dentro de `C:\Users\32759\solventa-db`.

---

Esto es una **MODIFICACIÓN de la importación de listas XML de Radar B2B que ya está implementada** en este repo.
No es una funcionalidad nueva: no la rehagas desde cero.

La implementación actual está en:
- `lib/radar-xml.ts`, `lib/importaciones.ts`, `lib/importaciones-servidor.ts` y `lib/importaciones-contactos.ts`;
- `app/api/importaciones/**`, `app/importaciones/[id]`;
- `components/ImportarRadarModal.tsx`, `components/ClientesTable.tsx` y `components/ClienteModal.tsx`;
- `docs/ejemplo_radar.xml`.

Radar B2B ha cambiado lo que exporta: ahora genera el **formato «solventa-db» versión 2**. Adapta el importador a ese formato.

**Lo que NO cambia y debe seguir igual:**
- Cada XML importado es una **lista aparte**, con sus propias fichas y sus propios contactos, guardada en
  `data/importaciones.json` y `data/importaciones/<id>.json`.
- Importar **no** toca `data/clientes.json` ni `data/listas.json`.
- Siguen igual el grupo «Importadas» en las pestañas, la página `/importaciones/[id]`, la detección «Ya en Todos»
  (`yaEnTodosId`), reimportar la misma búsqueda (reemplazar o crear otra), «Pasar a Todos», editar fichas y
  contactos, quitar fichas, renombrar y eliminar la lista.
- Siguen igual el límite de 4 MB, la validación en el servidor, un commit por acción y las convenciones del repo.

Antes de empezar: lee `CLAUDE.md`, `PROJECT_STATUS.md` y `.claude/skills/solventa-db-conventions/`, y haz `git pull --no-rebase`.

## Qué cambia en el formato (lo genera Radar B2B; no lo cambies)

Hasta ahora cada `<cliente>` llevaba la estructura propia de Radar: atributos `radar-id`, `completitud` (0-5),
`clasificacion` y `confianza`, un bloque `<evidencias>`, `<contactos-adicionales>` y solo los campos con valor.
**Eso desaparece.** Esa estructura solo servía para filtrar búsquedas dentro de Radar.

En v2, **cada `<cliente>` es una ficha de Solventa DB tal cual la guardas en `data/clientes.json`**:
- **Todos** los campos de `lib/campos.ts::BLOQUES` (37), en ese orden, con los vacíos como `<campo nombre="X" />`.
- Ya en vuestros formatos y vocabularios, sacados de los datos reales de `clientes.json`:
  - razón social en MAYÚSCULAS;
  - `TELEFONO 1` = móvil y `TELEFONO 2` = fijo, 9 cifras sin +34;
  - `Web` como `www.dominio.es`;
  - `Cargo` con vuestros valores (`DIRECTOR GRAL`, `Propietario`, `Gerente`, `Socio`, `Admon.`, `RRHH`, `TECNICO`);
  - `SECTORES` con vuestros valores (`FONTANERIA`, `CONSTRUCCIÓN`…);
  - `Estado` = `Lead`, `Extinguida` o `Inactiva`;
  - `Origen Cliente` = `RADAR B2B`.
- Lo que Radar sabe y no tiene campo propio (nombre comercial, forma jurídica, fecha de constitución, cargos
  exactos del BORME, otros teléfonos, emails y direcciones, objeto social completo) llega como texto en
  `Observaciones`, una línea por dato.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<exportacion origen="Radar B2B" formato="solventa-db" version="2" generado="ISO-8601">
  <lista radar-busqueda-id="UUID" nombre="fontaneros en Dos Hermanas" creada="ISO-8601" total="3">
    <descripcion>Zona: Dos Hermanas · Sector: Fontanería</descripcion>
  </lista>
  <clientes>
    <cliente>                                   <!-- SIN atributos -->
      <campo nombre="Contacto">Garcia Prueba Ana</campo>
      <campo nombre="Cargo">DIRECTOR GRAL</campo>
      ...                                       <!-- los 37 campos de BLOQUES, en orden -->
      <campo nombre="Observaciones">línea 1
línea 2</campo>                                <!-- puede tener saltos de línea: consérvalos -->
      <campo nombre="Fotos de la Empresa" />
      <ContactosAdicionales>                    <!-- opcional; antes se llamaba <contactos-adicionales> -->
        <contacto><nombre>Luis Ejemplo</nombre><cargo>Gerente</cargo><telefono /><email /></contacto>
      </ContactosAdicionales>
    </cliente>
  </clientes>
</exportacion>
```

El ejemplo completo con datos ficticios está en `C:\Users\32759\radar-b2b\docs\ejemplo_exportacion_solventa_db.xml`.
Cópialo encima de `docs/ejemplo_radar.xml`. La especificación de cada campo está en
`C:\Users\32759\radar-b2b\docs\formato_exportacion_solventa_db.md`.

## Cambios que hay que hacer

### 1. `lib/importaciones.ts`
- `VERSION_RADAR = "2"`. Un XML v1 se rechaza con un mensaje claro: «Este XML es del formato antiguo (v1).
  Vuelve a exportarlo desde Radar B2B.».
- `CAMPOS_PERMITIDOS`: todos los `key` de `BLOQUES`, es decir, `CAMPOS_BASE`. Ya no es la lista de 20.
  - Los nombres desconocidos se siguen ignorando con un aviso.
  - `Observaciones`, `ACTIVIDAD`, `Gestiones` y `Resumen IA de Gestiones` admiten hasta 3000 caracteres y
    conservan los saltos de línea.
  - Los campos vacíos son válidos: no son un error ni se omiten.
- `ClienteRadar` pasa a ser `{ campos: Record<string, string>; contactos: ContactoRadar[] }`.
  - Quita `radarId`, `completitud`, `clasificacion`, `confianza` y `evidencias`, y el tipo `EvidenciaRadar`.
  - `validarPayload` deja de leerlos.
  - Sigue exigiendo `Razón Social` no vacía.
- `construirFicha`:
  - `id` nuevo, todos los `CAMPOS_BASE` a `""`, los `campos` del XML encima, `ContactosAdicionales` con un `id` por contacto.
  - Se mantiene `yaEnTodosId`.
  - **Ya no se crea el bloque `radar`.**
  - No añadas los campos heredados de Airtable que no están en `BLOQUES` («From field: Razón Social», «Hora ultima
    Actualizacion», «Sincronizar», «Modificado»): los clientes creados desde la app tampoco los llevan.
- `resumenImportacion`: deja de contar completitud y dudosas. Devuelve
  `{ total, yaEnTodos, conNif, conContacto, conTelefono, conEmail, sectores: Record<string, number> }`, calculado
  sobre los campos de la ficha:
  - `conTelefono` = `TELEFONO 1` o `TELEFONO 2`;
  - `conEmail` = `Email` o `E-MAIL CORPORATIVO`.

### 2. `lib/radar-xml.ts` (parser del navegador)
- Lee `<ContactosAdicionales>`; mantén también `<contactos-adicionales>` por tolerancia.
- No leas atributos de `<cliente>` ni `<evidencias>`.
- Guarda **todos** los `<campo>`, también los vacíos (valor `""`).
- Recorta solo los extremos (`trim`): no colapses los saltos de línea internos de `Observaciones`.

### 3. `components/ImportarRadarModal.tsx` (vista previa)
- Quita la barra de «Completitud de las fichas» (5/5, 4/5…) y la tarjeta «Sector dudoso».
- Muestra: nombre (editable), descripción, nº de empresas, cuántas ya están en «Todos», cuántas tienen NIF, contacto,
  teléfono y email, el reparto por `SECTORES`, y avisos y errores.

### 4. `components/ClientesTable.tsx` (tabla de una lista importada)
Debe verse y comportarse **igual que la tabla de «Todos»**.
- Quita `COLUMNA_COMPLETITUD` y su orden por defecto: el orden por defecto es el del XML, que ya viene de más a menos completo.
- Quita el contador de completas y dudosas, las columnas «Completitud Radar», «Clasificación Radar» y «Confianza Radar»
  del CSV, y la insignia «Sector dudoso».
- **Mantén** la insignia «Ya en Todos» con su enlace.
- Si el componente `Completitud` deja de usarse en todo el repo, bórralo.

### 5. `components/ClienteModal.tsx`
- Quita la sección «Origen de los datos (Radar B2B)» (completitud, confianza, clasificación, evidencias) y la insignia de dudoso.
- La información de Radar se ve en `Observaciones`. Comprueba que ese campo muestra bien los saltos de línea
  (`whitespace-pre-line` o equivalente) en la ficha y en la impresión.

### 6. `app/api/importaciones/[id]/pasar-a-todos/route.ts`
- Copia la ficha tal cual (ya está en el formato de `clientes.json`), sin `id`, `yaEnTodosId`, `pasadoATodosId` ni `radar`.
- Puedes dejar el `radar: _radar` del destructuring: no molesta y cubre fichas antiguas.

### 7. Datos ya guardados
- A fecha de este cambio `data/importaciones.json` está vacío (`[]`), así que no hay que migrar nada. Compruébalo tras el `git pull`.
- Si hubiera alguna lista importada con v1, sus fichas ya tienen la forma de `clientes.json` y siguen funcionando.
  El bloque `radar` simplemente se ignora: no la borres sin preguntarme.

### 8. Valores nuevos en los desplegables
`Origen Cliente` = `RADAR B2B` es un valor nuevo. También pueden llegar `Cargo` y `SECTORES` que no existían, cuando
Radar no encuentra equivalente. Como `calcularOpciones` saca las opciones de los valores existentes, no hace falta
tocar nada. Solo comprueba que esos valores no rompen ningún filtro.

### 9. Documentación
- Actualiza `PROJECT_STATUS.md`: formato v2, qué se quitó y por qué.
- Copia el nuevo ejemplo a `docs/ejemplo_radar.xml`.
- Si `ROADMAP.md` menciona la completitud de Radar, actualízalo.

## Verificación (obligatoria antes de dar por terminado)

1. `npm run lint` y `npm run build` sin errores.
2. Tests de parser y validación si los hay; si no, una comprobación rápida con el ejemplo:
   - 3 fichas;
   - la 1.ª con `Contacto` = «Garcia Prueba Ana», `Cargo` = `DIRECTOR GRAL`, `TELEFONO 1` = `600000001`,
     `TELEFONO 2` = `955000001` y `Web` = `www.fontaneria-ejemplo.es`;
   - 2 contactos adicionales: «Luis Ejemplo», `Gerente`, y «Marta Modelo», `Admon.`;
   - `Observaciones` con 5 líneas;
   - la 2.ª ficha es un autónomo con `Cargo` = `Propietario`;
   - la 3.ª tiene `Razón Social` = «DESATASCOS FICTICIO» y `Provincia` = `Sevilla`, deducida del CP;
   - cada ficha tiene los 37 campos de `BLOQUES` y ningún bloque `radar`.
3. En local (`npm run dev`), importa `docs/ejemplo_radar.xml`.
   **Ojo: en local la app escribe en el repo real de GitHub.** Avísame antes de importar y, al terminar, elimina la
   lista de prueba desde la propia interfaz.
4. Comprueba en la interfaz:
   - la vista previa sin completitud;
   - la lista en «Importadas»;
   - la tabla igual que «Todos»;
   - la ficha sin la sección de Radar y con las `Observaciones` en varias líneas;
   - editar un contacto y marcarlo como preferente;
   - «Pasar a Todos» con una ficha: comprueba el commit, luego quítala de «Todos» con la papelera y vacíala, avisándome antes;
   - reimportar (reemplazar) y eliminar la lista.
5. Un XML con `version="1"` da el mensaje de formato antiguo y no escribe nada. Uno mal formado o sin `Razón Social`
   sigue dando su error.
6. Commit y push.
