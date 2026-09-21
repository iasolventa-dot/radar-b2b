---
name: verificacion-empresas-es
description: Normaliza, valida, deduplica y audita datos de empresas españolas (NIF/CIF, razón social, teléfonos, emails, webs, códigos postales) con reglas deterministas de resolución de entidades. Úsala SIEMPRE que el usuario suba o mencione un listado de empresas (CSV, Excel, JSON, exportación de Google Maps, directorio, CRM) y quiera limpiarlo, quitar duplicados, validar NIF, comprobar calidad, fusionar fuentes o saber si dos registros son la misma empresa; y también cuando se diseñen o modifiquen reglas de matching, normalización o confianza del proyecto Radar B2B, aunque no diga "verificar".
---

# Verificación de empresas (España)

Herramientas y procedimiento para convertir listados de empresas desordenados en datos fiables, siguiendo las reglas del documento **05 — Verificación, resolución de entidades y confianza** del proyecto Radar B2B. Los scripts implementan esas reglas: si cambias una regla, cambia el código y el documento a la vez.

## Principios (por qué se hace así)

- **El NIF manda**: dos NIF válidos distintos son dos empresas aunque compartan nombre, web y teléfono (franquicias, grupos). Nunca se fusiona solo por nombre.
- **Formato válido ≠ dato correcto**: un teléfono bien formado puede no ser de la empresa. Los scripts validan forma; la pertenencia la confirman fuentes independientes.
- **No inventar**: no completes NIF, emails (`info@…`) ni teléfonos que no estén en los datos. Si falta, se marca como faltante.
- **Datos personales**: DNI/NIE (autónomos) y emails tipo `nombre.apellido@` son datos personales. Señálalos en el resultado.

## Procedimiento

1. **Inspecciona el fichero** (primeras filas, columnas, nº de registros). Si el nombre de alguna columna es ambiguo, usa `--map`.
2. **Ejecuta el flujo completo**:
   ```bash
   python /ruta/a/la/skill/scripts/procesar_empresas.py todo ENTRADA.csv -d /home/claude/salida
   # columnas no detectadas: --map razon_social="Nombre empresa" --map telefono="Tlf 1"
   ```
   Genera `normalizado.csv`, `clusters.csv` (mismo `cluster_id` = misma empresa), `pares_revision.csv` (zona gris) e `informe_calidad.md`. Acepta CSV (detecta separador y codificación) y XLSX.
3. **Revisa la zona gris** (`pares_revision.csv`): para cada par, razona con las señales y las reglas de abajo y da un veredicto `misma | distinta | incierto` con motivos. Si es incierto, di qué dato lo resolvería (p. ej. "NIF del aviso legal de la web X"). No fuerces un veredicto.
4. **Entrega**: resumen en prosa (filas → entidades, % duplicados, principales problemas), los ficheros de salida y, si se pide, un Excel limpio con una fila por `cluster_id` eligiendo en cada campo el valor mejor validado.
5. **Comparación rápida de dos registros**:
   ```bash
   python scripts/procesar_empresas.py comparar --a '{"razon_social":"Construcciones Pérez SL","telefono":"955123456","cp":"41001"}' --b '{"razon_social":"CONSTRUCCIONES PEREZ S.L.","telefono":"+34 955 12 34 56"}'
   ```

6. **Extraer datos de un aviso legal o página de contacto** (HTML o texto), sin LLM:
   ```bash
   python scripts/extraer_datos_legales.py pagina.html --dominio perezobras.es
   ```
   Devuelve NIF válidos (ordenados: primero los etiquetados y lejos de menciones de "diseño web"), NIF con errata, candidatos a razón social, datos registrales, teléfonos, emails (genérico / del dominio) y CP, con avisos. Si hay varios NIF válidos o uno junto a una agencia, **decide el titular razonando con el contexto**, no cojas el primero a ciegas. Usa un LLM solo para lo que las reglas no encuentren.
7. **Tests de regresión**: `python scripts/test_lib_empresas.py`. Si modificas reglas, ejecútalos y añade el caso nuevo.
8. **Datos de prueba**: `assets/empresas_prueba.csv` (24 filas con casos trampa: duplicados reales, franquicias, homónimos, NIF de agencia, teléfono de gestoría). Úsalo para demostrar o comprobar el procesador: `python scripts/procesar_empresas.py todo assets/empresas_prueba.csv -d salida/`.

Para usar las funciones desde otro código: `import lib_empresas as L` → `L.validar_nif`, `L.normalizar_telefono`, `L.normalizar_email`, `L.extraer_dominio`, `L.validar_cp`, `L.extraer_forma_juridica`, `L.normalizar_registro`, `L.comparar`.

## Reglas implementadas (resumen)

**Reglas duras**: NIF válidos distintos → distintas · NIF igual → misma, salvo nombres sin parecido (posible NIF de agencia/gestoría → revisión) · mismo `place_id` → misma.

**Puntuación**: nombre ≥0,95 +0,45 · ≥0,88 +0,30 · ≥0,80 +0,15 · <0,50 −0,15 · solo palabras genéricas en común → tope +0,15 · mismo dominio +0,45 (mínimo 0,60) · mismo teléfono +0,35 · mismo email +0,25 · distancia ≤50 m +0,25 · ≤300 m +0,15 · ≤2 km +0,05 · >50 km −0,20 · sin coordenadas: mismo CP +0,10, provincia distinta −0,20 · formas jurídicas distintas −0,30.

**Decisión**: ≥0,80 fusión automática · 0,55–0,80 revisión · <0,55 distintas. La unión de clusters nunca junta dos NIF válidos distintos, ni por transitividad.

**Exclusiones de señal**: teléfonos 80x/90x; teléfonos presentes en más de 3 empresas con NIF distinto (gestorías, centralitas); dominios de plataformas (facebook, wix, directorios…) y de correo gratuito (gmail…).

**Normalización**: NIF sin guiones ni prefijo ES, con dígito de control (sociedades, DNI, NIE, K/L/M) · forma jurídica extraída del nombre (SL, SLU, SA, SAU, SCA, SCOOP, CB…) y coherencia con la letra del NIF · teléfono E.164 con tipo fijo/móvil/especial · email genérico vs. posiblemente personal · dominio registrable · CP con cero inicial restaurado (Excel lo pierde) y coherencia CP↔provincia · ñ tratada como n (igual que `unaccent` en Postgres).

## Casos difíciles a tener en cuenta al revisar

Franquicias y grupos (mismo nombre/web, NIF distinto → distintas) · homónimos en otras provincias · cambio de denominación (misma empresa) · domicilio social en gestoría · web cuyo aviso legal muestra datos de la agencia · nombre comercial distinto de la razón social (el puente es el dominio + aviso legal) · nombres genéricos ("Reformas y Construcciones del Sur").

## Limitaciones conocidas

- La similitud usa `difflib` (biblioteca estándar). Para listados de >50.000 filas conviene sustituirla por `rapidfuzz` en el worker de producción.
- Teléfonos no españoles: solo validación básica; en producción usar `phonenumbers`.
- No geocodifica: si hay direcciones sin coordenadas, compara por CP/provincia. En producción, geocodificar con CartoCiudad antes del matching.
- Los umbrales son iniciales; se calibran con el golden set del proyecto.
