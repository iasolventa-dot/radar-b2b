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

## 10. Cambios de la sesión 2026-09-23 (Apify funcionando de verdad + contacto en todas las búsquedas)

Problema reportado: con Apify configurado y marcado, las búsquedas solo usaban BORME y no traían ni web, ni teléfono, ni email. Causas encontradas (todas verificadas en vivo con el token real, plan FREE de Apify):

1. **Apify nunca devolvía nada**: los Actors de pago por evento (Google Maps, Google Search) rechazan con 400 cualquier `maxTotalChargeUsd` < 0,50 $, y el agente mandaba topes de céntimos. Ahora el tope nunca baja de 0,50 $ y el gasto real se limita con `maxItems` y con el número de resultados pedido, calculado a partir de las tarifas reales (`pricingInfo`): Maps 0,004 $/negocio, Search 0,0045 $/página, Facebook 0,012 $/página, LinkedIn 0,00345 $/empresa. El coste se relee tras terminar (al acabar la ejecución todavía no incluye todos los eventos cobrados).
2. **El LLM no elegía las fuentes de pago** (su prompt le decía "gratuitas primero"). Ahora `planificar()` tiene tres fases (`radar/agente/fases.py`): (1) las fuentes de pago marcadas se ejecutan siempre al principio, con argumentos sacados de los filtros; (2) el bucle LLM de siempre con el presupuesto que queda; (3) `completar_contacto` (`radar/agente/completar_contacto.py`) sobre todas las empresas encontradas: lee gratis la web de las que la tienen y busca por nombre las que no (Maps si está marcado, si no Google Search vía Apify, si no la búsqueda web del LLM), aceptando solo resultados cuyo nombre/NIF coincide.
3. **Maps + web propia**: cada web que devuelve Maps se lee con nuestro extractor (aviso legal → razón social, NIF, email). Nueva regla de resolución **R8**: marca (solo nombre comercial) y sociedad (razón social) bajo la misma web propia = misma empresa (antes quedaban como dos "en revisión").
4. **Ruido**: páginas con más de 8 teléfonos o emails se tratan como directorio y no se guardan; lista de plataformas ampliada (Houzz, ProntoPro, eleconomista, Scribd...); resultados de buscadores con código postal de otra provincia no entran en la búsqueda; razón social "de texto legal" descartada; teléfonos de relleno (600 000 000) inválidos; registros sin nombre ni NIF ya no crean empresas; a Facebook/LinkedIn solo se envían páginas de empresa.
5. **BORME**: en búsquedas por municipio se descartan los actos sin municipio conocido (antes "San Sebastián de los Reyes" metía 1.405 empresas de toda Madrid), máximo 90 días, y sin sector ya no se aplica el filtro de construcción por defecto.

Verificado en vivo (3 búsquedas reales):
- API, fontanería en San Sebastián de los Reyes, 0,20 €: destapó los fallos de ruido y marca/sociedad (corregidos después).
- API, electricistas en Alcobendas, 0,20 € → 26 empresas: 22 con teléfono, 22 con web, 13 con email. Coste 0,13 €.
- **Desde el panel en Chrome**, carpintería de aluminio en Tres Cantos, 0,10 €, 5 Actors marcados → completada, 16 empresas: 14 con teléfono, 15 con web, 14 con email. Coste 0,084 €. El panel muestra cada fase con su resumen.

Pendiente conocido: portales locales sin patrón claro todavía pueden colarse (se van añadiendo a `DOMINIOS_PLATAFORMA`); LinkedIn por nombre no resuelve (el Actor no encuentra ni "Acciona"), solo con URL `/company/`; `consultar_bd` devuelve 0 para las empresas recién encontradas porque su confianza < 0,5, lo que confunde al LLM; el contador "Rondas 12 / 3" cuenta pasos, no vueltas del LLM.

## 11. Cambios de la sesión 2026-09-24 (personas de contacto y datos contrastados entre fuentes)

Decisiones del usuario: (1) cuando la resolución duda de si un dato es de una empresa ya conocida, se UNE a la más probable y se marca, en vez de crear una fila nueva; (2) dos colas: «Datos sin contrastar» (contradicciones sin evidencia suficiente) y «Cola de revisión» (contradicciones resueltas solas con evidencia fuerte, para confirmar o deshacer).

- **Personas de contacto con su puesto**: la extracción web saca gerentes, directores, fundadores, responsables o personas de contacto de la web de la empresa (reglas para patrones claros "Gerente: Nombre", "Nombre – Director comercial"; LLM cuando la web menciona cargos y las reglas no emparejan nombre). Se guardan en `personas`/`cargos` con fuente y URL de evidencia, igual que los administradores del BORME, y salen en la columna «Contacto». Se descargan también las páginas de «equipo» y «la empresa». Máx. 5 personas por web.
- **Contradicciones entre fuentes** (`conflictos_datos`, migración 202609241000; `radar/verificacion/conflictos.py`): para NIF, razón social y web (campos de valor único; teléfonos/emails son multivalor y no se contradicen) la empresa guarda siempre el valor más probable. Si otra fuente da otro valor con peso real: con evidencia fuerte (varias fuentes independientes contra una, dato más antiguo sustituido por uno igual o más fiable, registro oficial, margen de confianza claro) → «Cola de revisión»; si no → «Datos sin contrastar».
- **Duda de identidad** (franja de revisión de la resolución): el registro rellena la empresa más probable y queda en «Datos sin contrastar» con «Sí, es la misma» / «Separar» (retira lo que aportó y lo procesa como empresa nueva). `candidatos_duplicado` ya no recibe filas nuevas; las 28 antiguas siguen al final de esa pantalla.
- Decisiones humanas = observación de la fuente `manual` (0,98) con el usuario en `url_evidencia` + reconsolidación: trazable y no se reabre. Endpoint `POST /conflictos/{id}/resolver`.
- Nueva regla de resolución: teléfono propio común + palabra distintiva del nombre en común ⇒ como mínimo unir con duda.
- Panel: «Posibles duplicados» pasa a «Datos sin contrastar» (`/duplicados`); nueva «Cola de revisión» (`/cola-revision`); la revisión del golden set sigue en `/revision`, enlazada desde «Golden set». La tabla de resultados marca las empresas con datos pendientes.
- Limpieza de ruido: lugares de Maps sin teléfono ni web descartados; organismos públicos no se guardan como empresa; prefijo «Titular:» fuera de la razón social.

Verificado: 360 tests, ruff, mypy, tsc, eslint, `next build`; caso controlado contra la BD real (4 fuentes de una empresa ficticia → una sola fila con 2 teléfonos, 2 emails y la gerente; contradicción de razón social detectada; confirmar / elegir / separar por la API; confirmar desde el panel, registrado con el email del usuario; datos de prueba borrados después); búsqueda real desde el panel (fontanería en Colmenar Viejo, 0,10 €): 17 empresas, 15 con teléfono, 12 con email.

Pendiente conocido: la mayoría de webs de pymes no nombran a ninguna persona (en Colmenar solo 1 de 17); para directivos, el BORME sigue siendo la mejor fuente pero solo cuando la empresa aparece en él. Las sedes siguen con «última observación gana» (no entran en las contradicciones). Los resultados de Google Search aún traen alguna web ajena al sector (una app, un directorio local).

## 12. Cambios de la sesión 2026-09-25 (efectividad de las búsquedas, dudas resueltas solas, nueva Cola de revisión)

Medición previa con búsquedas reales: entre el 30 y el 40 % de las empresas de una búsqueda no eran del sector pedido (ayuntamiento, directorios, una app, una aseguradora, una fuente de agua de Maps...). Nada comprobaba a qué se dedicaba cada empresa. La «Cola de revisión» salía vacía porque solo recibía contradicciones con evidencia fuerte, rarísimas en una búsqueda nueva.

- **Filtro de relevancia con IA** (`radar/agente/relevancia.py`, fase final de toda búsqueda): un LLM barato clasifica cada empresa con lo que se sabe de ella (categoría de Google Maps, título y descripción de su web — ahora se guardan al leer cada web —, objeto social, municipio): relevante / dudosa / descartada. Las descartadas no salen en los resultados ni en el CSV; nada se borra de la base. Criterio: descartar solo actividad claramente distinta o lo que no es una empresa (u otra provincia); otro municipio de la misma provincia = dudosa. Columna `busqueda_resultados.clasificacion` (migraciones 202609251000 y 202609251100 — `relevancia` ya existía como numeric). Coste medido: ~0,002 € por búsqueda.
- **Resolución automática de «Datos sin contrastar»** (`radar/agente/resolver_dudas.py`, al final de cada búsqueda y con el botón «Intentar resolver automáticamente»): 1) verificación dirigida en la web propia de la empresa (¿aparece el teléfono/email/NIF/nombre del registro en duda?; ¿cuál de las razones sociales/NIF en juego aparece?); 2) si no hay evidencia, sugerencia de IA con el perfil de la empresa SIN lo aportado por el registro en duda (antes era circular). Con confianza ≥ 0,85 se aplica (fuente nueva `verificacion_automatica`, 0,90) y pasa a la Cola de revisión; si no, la sugerencia se muestra en «Datos sin contrastar». Separar nunca se hace solo.
- **Cola de revisión rediseñada**: «decisiones que el sistema ha tomado solo»: (1) resultados dudosos o descartados por el filtro de relevancia, agrupados por búsqueda, con «Sí es del sector» / «No lo es»; (2) datos resueltos automáticamente (evidencia fuerte, evidencia en su web o IA), con confirmar / usar otro valor.
- **Búsqueda**: Maps recibe hasta el 50 % del presupuesto (antes 40 %) y Google Search el 10 % (antes 15 %); las consultas de Google van sin comillas y con `-site:` de los directorios conocidos; las palabras de Maps priorizan el nombre del sector; `consultar_bd` informa al planificador de lo que ya lleva la búsqueda (antes veía siempre "0"); reserva de presupuesto para los pasos finales. Emails de dominios de plataforma (google.com, wix...) descartados.

Verificado: 369 tests, ruff, mypy, tsc, eslint, `next build`; filtro sobre la búsqueda real de Colmenar Viejo (descarta el ayuntamiento, la app, la fuente, la tienda; los de pueblos vecinos quedan dudosos); resolución de dudas con un caso controlado y LLM real; búsqueda real «electricistas en Majadahonda» (0,20 €): 19 empresas todas con teléfono, 8 descartadas correctamente (electrodomésticos, puertas automáticas, persianas, un taller Bosch, aire acondicionado...), 3 dudosas y 8 electricistas relevantes; el panel lo muestra y «Sí es del sector» desde la Cola de revisión funciona. La confirmación de esa búsqueda se hizo por API porque la pestaña de Chrome se quedó bloqueada; la interpretación, las casillas y el resto sí se probaron en el panel.

Pendiente conocido: muchas dudosas en empresas guardadas antes de este cambio (sin título/descripción de web); el LLM planificador sigue llamando a BORME en búsquedas por municipio aunque casi nunca aporta nada.

## 13. Cambios de la sesión 2026-09-24 (BORME como fuente de identidad, calidad y limpieza)

- **Limpieza**: se vaciaron todos los datos de prueba (empresas, búsquedas, registros brutos, observaciones, personas, cargos, sedes, contactos, conflictos, duplicados, fusiones). Se conservan catálogos (fuentes, municipios, CNAE), configuración, `uso_apify` y el índice del BORME.
- **Índice local del BORME** (migración 202609251200, `radar/fuentes/borme_indice.py`): cada día/provincia se descarga una sola vez y sus actos quedan parseados en `borme_actos`. Cargado con `scripts/cargar_indice_borme.py` para **Madrid y Sevilla, 24-09-2025 a 24-09-2026: 180.615 actos, ~114.000 sociedades** (~20 min, gratis; relanzable, solo baja lo que falta). Un día reciente sin actos no se marca como cargado (puede no estar publicado aún). `descubrir_borme` ya no re-descarga ~21.000 actos por búsqueda.
- **Enriquecimiento con el BORME** (`radar/agente/enriquecer_borme.py`, fase 3b de toda búsqueda, coste 0): cada sociedad encontrada (Maps/web) con razón social se busca por denominación en el índice (misma forma jurídica); su acto se procesa y se une por la regla nueva **R9** (`scoring.py`: denominación social idéntica + misma forma jurídica, sin provincias ni ubicaciones contradictorias → misma empresa) y aporta administradores, hoja registral y domicilio. Cobertura limitada a sociedades con algún acto en el último año.
- **Calidad**: fichas de directorio (`/contratistas/<empresa>` en profymarket.com y similares) ya no se toman por la web de la empresa (`es_ficha_de_tercero`, `parece_ficha_de_directorio`); un DNI/NIE en una sociedad (SL, SA...) se descarta como NIF al normalizar (`dni_en_sociedad`); el filtro de relevancia marca como dudosas las webs de captación de leads de agencias; `completar_contacto` también acepta coincidencia por teléfono.
- **Velocidad**: las webs se leen en paralelo (5 a la vez, `enriquecer_varias`) en Maps, Google Search y la búsqueda web.
- **Planificador**: se le dice explícitamente que el presupuesto indicado es lo que le queda (antes creía que Maps había "superado el presupuesto total" y paraba con dinero sin gastar).

Verificado: 377 tests, ruff, mypy, tsc, eslint. Búsquedas reales desde el panel: «reformas y construcción en Alcobendas» (0,185 €, sin Maps): 21 empresas, 12 relevantes, BORME unió 3; «instaladores eléctricos en Getafe» (0,143 €, con Apify Maps): 25 empresas, 24 con teléfono, 20 con email, BORME añadió 6 actos con administradores/consejeros en 5 sociedades, 15 relevantes / 2 dudosas / 8 descartadas correctamente (calderas, cerrajero, tienda, proveedores de equipos, una empresa de Managua).

Pendiente conocido: `consultar_bd` informa al planificador de "0 empresas que cumplen los filtros" (confianza/frescura) aunque la búsqueda tenga 25, lo que le confunde; el coste del planificador LLM es ~50 % del gasto en búsquedas sin Maps; ampliar el índice del BORME a más provincias/años cuando se busque fuera de Madrid/Sevilla.
