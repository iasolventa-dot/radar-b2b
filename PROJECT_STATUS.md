# Radar B2B — estado real del proyecto

**Última auditoría a fondo contra el repo/BD reales**: sesión del
2026-09-14 al 2026-09-16 (chat "Orden de conectores fase 2 y golden set").
Antes de esa sesión, el registro de decisiones (`docs/08`) daba por hechas
varias cosas que la auditoría demostró que **no existían en el repositorio
remoto**. Este documento refleja lo verificado, no lo que dicen los docs
numerados. Si ha pasado tiempo desde la fecha de arriba, vuelve a
verificar antes de confiar en cifras concretas (nº de filas, etc.).

Repo: `https://github.com/iasolventa-dot/radar-b2b` (público).
Carpeta local: `C:\Users\32759\radar-b2b`.
Despliegue: **local únicamente** (worker + panel en la máquina del
usuario). Railway/Vercel no están en uso real pese a lo que digan
`docs/02` y `docs/08` — esa decisión quedó revocada en la práctica.

---

## 1. Resumen de una línea

El pipeline determinista (normalización → resolución de entidades →
verificación) y el agente (interpretación + planificador con tool use) funcionan
de punta a punta en local sobre las fuentes libres BORME, PLACSP, OpenStreetMap,
búsqueda web (LLM nativo) y CartoCiudad/INE DIRCE como apoyo. Google Places está
implementado y solo espera la clave en Ajustes. El panel web (búsqueda,
resultados, ficha de empresa con «búsqueda en profundidad», duplicados, cola de
revisión, golden set y ajustes) está construido y verificado en el navegador.
Todos los datos actuales son de prueba (ver §3).

---

## 2. Qué está construido y verificado de verdad

### Backend (`worker/radar/`)
- **Normalización, resolución de entidades y verificación** (`normalizacion/`,
  `resolucion/`, `verificacion/`, `orquestador/`): construidos con tests
  unitarios pasando (158 a fecha del 11/09; no reverificado el número tras
  los cambios de esta sesión de auditoría).
- **Conector BORME** (`fuentes/borme.py`): funciona contra el API real del
  BOE. Detecta constituciones, disoluciones, extinciones, cambios de
  domicilio/denominación. **No da NIF** (el BORME nunca lo publica en los
  actos) — confirmado, no es un bug.
- **Conector PLACSP** (construido en esta sesión de auditoría): parsea
  sindicación Atom en formato CODICE/XML (no tiene API REST, al contrario
  de lo que asumía `docs/04`). Da **NIF real** + señal de actividad
  reciente. Bug crítico encontrado y corregido en producción: lotes
  distintos de la misma licitación compartían `id_externo` y se
  descartaban como `ya_procesado` — se corrigió añadiendo el
  `ProcurementProjectLotID` como sufijo. Verificado con datos reales:
  ZIP de agosto 2025 (148.514.308 bytes), 47.114 entradas, 36.189 contratos
  con NIF real, 4.515 en CPV de construcción; tras el fix, Sevilla/agosto
  2025 dio 72 empresas. Se ejecuta como job periódico
  (`ejecutar_placsp.py`), no como herramienta del agente (la descarga
  tarda 1-2 min, demasiado para una ronda del planificador).
- **CartoCiudad (IGN)** conectado para geocodificación, con un bug de
  producción corregido: nombres de municipio duplicados tipo "Sevilla,
  Sevilla" hacían que el geocodificador devolviera resultados de la
  provincia equivocada.
- **INE DIRCE** conectado para estimación de cobertura — con la limitación
  real de que **no hay tabla oficial que cruce provincia + CNAE + nº de
  empresas** (solo a nivel CCAA), así que la estimación de cobertura es
  más aproximada de lo que el diseño original asumía. Herramienta nueva
  del agente: `estimar_cobertura`.
- **Búsqueda web** vía herramienta nativa del LLM (OpenAI `web_search` /
  Anthropic `web_search_20250305`), sin API externa de pago.
- **Agente**: interpretación (`agente/interpretacion.py`) y planificador
  con bucle de tool use (`agente/planificador.py`) construidos y
  funcionando end-to-end sobre las fuentes de arriba.
- **API HTTP del worker** (`radar/api/`, FastAPI): `POST /busquedas`,
  `/confirmar`, `/cancelar`, progreso por sondeo. Confirmado real y en uso
  desde el panel reconstruido (ver §3).

### Frontend (`web/`)
- **Panel del golden set** (`/`, `/revision`, `/revision/[id]`,
  `/entidades`): real, con commits reales, funcionando contra Supabase.
  Con login por Supabase Auth (`app/login/`, `auth/callback/`, `logout/`).
- **Panel de búsqueda del agente**: **NO EXISTÍA** en el repo remoto hasta
  esta sesión, pese a que `docs/07 §7` y `docs/08 D-17` lo daban por
  "construido y funcionando en local, next build/eslint limpios" desde el
  11/09. Auditoría directa (`git log -- web/`, `grep` en `web/src/`,
  revisión de `nav-links.tsx` y `.env.example`) confirmó que solo existían
  3 commits sobre `web/` y ninguno de frontend de búsqueda — probablemente
  un `git push` que nunca se hizo, o una descripción que nunca llegó a
  construirse de verdad. **Se reconstruyó en esta sesión**: `lib/api.ts`
  con `confirmarBusqueda`/`cancelarBusqueda`, formulario de nueva búsqueda,
  vista de progreso con sondeo cada 4s, histórico. El usuario confirmó
  "todo ok" tras probarlo en local con el worker levantado. **No confirmado
  si se ha hecho `git push` de esta reconstrucción** — verificar
  `git log -- web/` al empezar en Claude Code.

### Bugs encontrados y corregidos en esta sesión de auditoría
- `observaciones.confianza` se consultaba en vez de `confianza_fuente` →
  la sección de observaciones en la ficha de empresa devolvía siempre
  vacío.
- `pct_con_telefono_verificado` siempre 0,0 porque nada escribía nunca
  `estado = 'verificado'` en `canales_contacto`.
- `fusiones.empresa_origen` sin FK — añadida (es segura: `fusionar_empresas`
  conserva la fila de origen).
- Bug de React `key` duplicada en el panel de progreso (varias llamadas a
  herramientas en el mismo turno del LLM compartían `numero_ronda`).
- Filtros capturados por la interpretación pero nunca aplicados en
  `construir_where_empresas`: `sector.exclusiones`, `requisitos.*`,
  `calidad.*`. Corregidos.
- `ubicacion.ccaa` se capturaba pero nunca se usaba en el filtro — corregido
  usando la columna `ccaa` ya cargada en `municipios.csv`, con el mismo
  problema de orden de palabras del INE ("Rioja, La" vs "La Rioja") que
  hubo que normalizar en ambos sentidos.

---

## 3. Golden set — ya no es un bloqueo (decisión 2026-09-18)

`golden_candidatos` y `golden_entidades` están a 0: el usuario decidió que ningún
dato actual es real (fase de pruebas), se borraron los 690 candidatos y se
pospone la revisión manual hasta empezar la base real. El panel de revisión
(`/revision`, `/entidades`) sigue funcionando. Mientras tanto, la calidad del
cruce entre fuentes se comprueba con tests deterministas
(`worker/tests/unit/test_resolucion_scoring.py`) y con los scripts en vivo
`verificar_cruce_fuentes.py` / `verificar_places_simulado.py` (revierten todo).

## 4. Estado verificado contra la BD real (2026-09-21)

- 1.249 empresas activas; 93 con NIF (PLACSP), 143 con CNAE (clasificador
  `radar/clasificacion`, ya construido), 151 sedes geocodificadas
  (CartoCiudad validada contra el municipio INE).
- **Duplicados**: se resolvieron 264 «posibles duplicados» con reglas
  deterministas (`scripts/resolver_duplicados_por_reglas.py`): 160 fusiones por
  misma hoja registral (identidad del Registro Mercantil, regla R3b) y 104
  rechazos de series numeradas (R7, «REN 410» ≠ «REN 414»). Quedan 2 pendientes.
  El arbitraje LLM (`scripts/arbitrar_duplicados.py`) sigue disponible.
- El BORME no publica NIF ni CNAE: NIF solo viene de PLACSP; el CNAE se
  deduce del objeto social. 747 empresas del BORME no tienen sede porque solo
  los actos de constitución traen domicilio.
- El coste de tokens del LLM planificador **ya se resta del presupuesto** y se
  muestra en el panel (`radar/coste_llm.py`). El coste de extracción/interpretación
  con LLM sigue sin contarse.
- `consultar_bd` usa `cnae_coincide` (prefijo) y combina CNAE y palabras clave con OR.
- `sectores` sigue vacía y sin usar (la búsqueda por sector va por CNAE y
  palabras clave); `fusiones` ya tiene uso real (160 filas).
- Caché de descargas web: directorio local (el despliegue es local).
- Comprobaciones limpias: pytest (312), ruff, mypy, tsc, eslint y `next build`.

## 5. Fuentes: qué falta (Fase 2)

| Fuente | Estado | Notas |
|---|---|---|
| BORME | ✅ construida | Sin NIF (nunca lo publica) |
| PLACSP | ✅ construida | Con NIF real; job periódico, no herramienta del agente |
| Búsqueda web (LLM nativo) | ✅ construida | Sin coste de infraestructura extra |
| CartoCiudad | ✅ construida | Geocodificación básica |
| INE DIRCE | ✅ construida (parcial) | Solo estimación aproximada, sin cruce provincia+CNAE oficial |
| **Google Places** | ✅ construida (2026-09-21), a la espera de clave (opcional por búsqueda: casilla en «Nueva búsqueda») | API OFICIAL (no scraping de Maps). Cumple sus condiciones: solo se guarda el `place_id`; los datos de Google se usan en vivo para reconocer empresas ya guardadas o para seguir la web propia de la empresa (`radar/agente/descubrir_places.py`, `radar/fuentes/places.py`). Clave y tope mensual se pegan en **Ajustes** del panel (`/ajustes`; tabla `configuracion_secretos`, solo la lee el worker). Sin clave, la herramienta no se ofrece al planificador. Verificada con Google simulado contra la BD real (`scripts/verificar_places_simulado.py`); la llamada real solo se probó con una clave falsa (Google la rechaza y no se registra coste). Tarifas de lista ~32-35 $/1.000 págs. de 20 resultados: **a verificar** en tu consola de Google Cloud. |
| **OpenStreetMap (Overpass)** | ✅ construida (2026-09-21) | Fuente libre (ODbL) por municipio y sector: `radar/fuentes/osm.py`, herramienta `descubrir_osm`, `scripts/ejecutar_osm.py`. Sin NIF ni razón social (solo nombre comercial), cobertura irregular: 44 negocios de construcción en Sevilla capital. Overpass limita por IP: se reintenta y un error nunca se toma por «0 resultados». |
| **Apify** | ✅ conectada, 5 Actors independientes (2026-09-22), opcional por búsqueda (una casilla por Actor) | Cliente genérico de la API (`radar/fuentes/apify.py`: probar token, ejecutar cualquier Actor con tope de coste, leer dataset), un único token + tope mensual en **Ajustes**. Herramientas del agente, cada una con su casilla en «Nueva búsqueda» y gateada en `herramientas_activas`/`_HERRAMIENTAS_APIFY` (`radar/agente/herramientas.py`): `enriquecer_con_apify` (rastreo de webs propias, `apify/website-content-crawler`), `descubrir_google_search` (búsqueda en Google, `apify/google-search-scraper`, con más control que la búsqueda nativa del LLM), `descubrir_apify_maps` (Google Maps por zona/palabras clave, `compass/crawler-google-places` — a diferencia de Google Places SÍ guarda el registro completo, no solo el `place_id`: fuente nueva `apify_google_maps`, fiabilidad 0.55, mismo `grupo_independencia='google'` que `google_places` para no contarse como confirmación independiente entre sí), `enriquecer_con_linkedin` (`automation-lab/linkedin-company-scraper`, por nombre o URL — fuente `linkedin`, ya existía en el catálogo desde el esquema inicial pero con `permite_almacenar=false`; se habilitó en la migración 202609221000), `enriquecer_con_facebook` (páginas de empresa, `apify/facebook-pages-scraper`, fuente nueva `facebook`). `descubrir_google_search` no procesa directamente facebook.com/linkedin.com: los devuelve en `candidatos_facebook`/`candidatos_linkedin` para que el planificador decida si llama a las otras dos herramientas. Servicio de terceros con cuenta y facturación propias. Probado: pytest (mappers + rutas de guarda de cada orquestador, sin BD real) y, en Chrome, guardar/probar/borrar un token falso (Apify devuelve su 401 real, el token nunca se filtra). **No probado**: una ejecución real de ningún Actor (hace falta un token válido), ni las 5 casillas nuevas del formulario en el navegador (sesión de Chrome no disponible en el momento de verificarlo — sí se comprobó con `tsc`/`eslint`/`next build`). Los nombres exactos de campos de entrada/salida de cada Actor se verificaron contra `apify.com` el 2026-09-22, no contra una ejecución real: si Apify cambia el schema de alguno, revisar el mapeo correspondiente en `radar/fuentes/apify_*.py`. |
| Censo Cámaras (censo.camara.es) | ⬜ descartado | Datos mínimos (nombre, dirección, un epígrafe IAE, sin NIF) y reclamo a un producto de pago (Camerdata). |
| BDNS (subvenciones) | ⬜ descartada | API pública, pero solo consulta por NIF exacto (no por nombre ni zona): no sirve para descubrir ni para resolver NIF de empresas sin él. |
| REA | ⬜ reprioridad a la baja | Se descubrió que **no es fuente de descubrimiento**: solo consulta puntual (nombre/NIF) por formulario web sin API. Encajaría como paso de *refuerzo de confianza* sobre candidatos ya existentes, no como conector de búsqueda. Pendiente decisión de si merece la pena dado el esfuerzo de mantenimiento (frágil, depende del HTML de un formulario gubernamental) |
| LinkedIn (scraping directo, fuera de Apify) | ⬜ descartado | Seguía siendo cierto para un scraper propio; **ya no aplica a Apify** (ver fila de arriba: `enriquecer_con_linkedin` usa un Actor de Apify, decisión del usuario 2026-09-22 — la responsabilidad de las condiciones de la plataforma es de Apify/de quien lo lanza, no del código de este proyecto). |

## 6. Decisiones activas que contradicen `docs/`

- **Despliegue local, no Railway**: pese a D-07/D-16 en `docs/08`, el
  producto se usa siempre en local (worker + panel en la máquina del
  usuario). Railway queda como opción futura, no activa.
- **Proveedor LLM**: verificar si sigue siendo OpenAI por defecto
  (`proveedor_llm="openai"`, D-14) o si cambió — no confirmado en la
  última auditoría.

## 7. Siguiente paso recomendado

1. Pegar la clave de Google Places en **Ajustes** cuando se quiera activarla
   (ver §5) y probar una búsqueda real con presupuesto pequeño.
2. Cuando se empiece la base real: borrar los datos de prueba, lanzar los
   conectores (BORME, PLACSP, OSM, búsqueda web) por zona y sector, y retomar
   la revisión del golden set sobre datos reales.
3. Empujar los commits al remoto (`git push`): nada de esto está en GitHub todavía.
4. Pendiente de diseño: editar los filtros interpretados antes de confirmar
   una búsqueda (hoy solo se confirman o se rehace la petición).

## 8. Cambios de la sesión 2026-09-21 (cruce entre fuentes y búsqueda web)

- **Bloqueo por contacto exacto** (`bd.buscar_candidatos_por_contacto`, usado por `procesar.reunir_candidatos`): antes solo se comparaba por similitud de nombre, así que mismo dominio/teléfono/email/place_id con nombre distinto nunca llegaba a compararse.
- **Reglas de scoring nuevas**: R5 (mismo punto ≤50 m + palabra distintiva común ⇒ revisión) y R6 (mismo nombre casi idéntico + mismo punto ⇒ misma empresa, salvo NIF o forma jurídica contradictorios). Verificado en vivo con `scripts/verificar_cruce_fuentes.py` (transacción revertida).
- `buscar_web`: consultas automáticas por sector y zona (`radar/agente/consultas.py`) y descarte de URLs que no son la web propia (BOE, directorios, redes sociales incl. LinkedIn: solo se usan como resultado de búsqueda, nunca se descargan).
- «Búsqueda en profundidad» por empresa (`/empresas/{id}/profundizar`, botón en la ficha).
- Las empresas sin razón social (OSM) se muestran con su nombre comercial en el panel.

## 9. Cambios de la sesión 2026-09-22 (Apify: 5 Actors + casilla por búsqueda)

- Decisión del usuario: el cliente de Apify NO decide qué Actor/plataforma se puede ejecutar (se quitó el bloqueo de LinkedIn/redes/Maps que tenía `radar/fuentes/apify.py` al principio de la sesión) — es una tubería genérica; la responsabilidad de las condiciones de cada sitio es de Apify o de quien lo lanza, no del código de este proyecto.
- 4 herramientas nuevas del agente sobre Apify (ver fila "Apify" de la tabla de fuentes en §5): `descubrir_google_search`, `descubrir_apify_maps`, `enriquecer_con_linkedin`, `enriquecer_con_facebook`. Cada una con su propio mapeo item→`RegistroBruto` en `radar/fuentes/apify_maps.py` / `apify_linkedin.py` / `apify_facebook.py`, verificado con fixtures basados en los ejemplos de salida documentados en apify.com (no con una ejecución real).
- `busquedas.opciones.apify_actores` (antes `usar_apify: bool`) es ahora una lista de qué Actors están permitidos en esa búsqueda concreta (`web_crawler`/`google_search`/`google_maps`/`linkedin`/`facebook`); un único token/tope mensual en Ajustes cubre los 5.
- Formulario "Nueva búsqueda": 6 casillas de fuentes de pago (Google Places + 5 de Apify), cada una deshabilitada con aviso si falta la clave/token correspondiente.
- Fuente `linkedin` (existía desde el esquema inicial con `permite_almacenar=false`, sin ningún conector) habilitada; fuente nueva `apify_google_maps` (`grupo_independencia='google'`, no confirma nada de forma independiente respecto a `google_places`) y `facebook` (migración `202609221000_fuentes_apify.sql`).
