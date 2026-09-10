# 04 — Catálogo de fuentes de datos

> **Aviso**: endpoints, precios, cuotas y condiciones de uso cambian. Antes de implementar un conector, verifica la documentación vigente de la fuente y registra en `08_registro_decisiones.md` qué has comprobado y cuándo.

## 1. Cómo clasificamos las fuentes

Para cada fuente nos importan cuatro cosas:

1. **Qué aporta**: descubrir empresas nuevas, identificar (NIF, razón social), localizar, contactar, confirmar actividad, estimar tamaño.
2. **Fiabilidad** por campo (valor inicial en la tabla `fuentes`, a calibrar con el golden set).
3. **Condiciones**: ¿se puede almacenar lo que devuelve? ¿se puede automatizar? ¿hay derechos sobre la base de datos?
4. **Independencia**: ¿es una fuente primaria o copia de otra?

## 2. Fuentes oficiales y datos abiertos (la columna vertebral de la identidad)

| Fuente | Qué aporta | Notas |
|---|---|---|
| **BORME** (Boletín Oficial del Registro Mercantil) | Constituciones, cambios de domicilio y denominación, nombramientos, ampliaciones de capital, **disoluciones, extinciones, concursos**. Razón social, domicilio social, objeto social (en constituciones), datos registrales | Publicación diaria por provincia. El BOE ofrece API de datos abiertos con los sumarios; los actos de la sección A vienen en PDF por provincia y hay que parsearlos. No incluye el NIF en los actos: el NIF se obtiene de otras fuentes y se cruza por razón social + provincia + datos registrales. Fuente clave para **detectar empresas muertas**. Solo sociedades mercantiles (no autónomos) |
| **Plataforma de Contratación del Sector Público (PLACSP)** | Adjudicatarios de contratos públicos **con NIF y razón social**, importes, CPV (tipo de contrato) | Datos abiertos (ficheros/sindicación). Excelente para construcción e ingeniería: identifica empresas con actividad real y reciente |
| **REA — Registro de Empresas Acreditadas** (construcción) | Empresas que trabajan en obras como contratistas/subcontratistas, con NIF | Gestionado por cada comunidad autónoma, con consulta pública. Revisar condiciones de reutilización de cada CCAA |
| **INE — DIRCE** | Número de empresas por CNAE, provincia y estrato de asalariados | Datos **agregados**, no listados. Sirve para **estimar la cobertura**: "en Sevilla hay ~N empresas de la división 41; tenemos M" |
| **INE — CNAE** | Catálogo de actividades | Existe la CNAE-2009 y la nueva CNAE-2025; confirmar cuál usan las fuentes y cargar la tabla de correspondencias |
| **CartoCiudad (IGN)** | Geocodificación y normalización de direcciones españolas | Datos abiertos, almacenables con atribución. Alternativa a Google para guardar coordenadas de forma permanente |
| **Límites municipales (IGN) y códigos INE** | Polígonos y códigos de municipio | Para filtros geográficos y rejillas de búsqueda |
| **VIES (Comisión Europea)** | Comprueba si un NIF está dado de alta como operador intracomunitario | Para España **no devuelve nombre ni dirección**: solo confirma validez. Señal positiva, pero muchas pymes no están dadas de alta |
| **AEAT — comprobación de NIF** | Verificar que un NIF corresponde a una razón social | La AEAT ofrece servicios de comprobación de NIF con certificado electrónico. Investigar requisitos y si el uso encaja (Fase 2) |
| **BOE — anuncios de revocación de NIF** | Sociedades a las que la AEAT ha revocado el NIF | Señal fuerte de inactividad |
| **Registro Mercantil (publicidad formal)** | Nota simple, cuentas depositadas (empleados, facturación) | De pago por consulta. Reservar para casos de alto valor o ambiguos |

## 3. Web corporativa de la empresa (la mejor fuente de contacto)

La **LSSI (art. 10)** obliga a los prestadores de servicios de la sociedad de la información a publicar en su web denominación social, NIF, domicilio y datos de inscripción registral. En la práctica, casi todas las webs de empresa españolas tienen un **aviso legal** con esos datos.

Esto convierte la web en un **puente de identidad**: une el nombre comercial y el dominio con el NIF y la razón social. Procedimiento:

1. Descargar portada y localizar enlaces a "aviso legal", "legal", "privacidad", "contacto", "quiénes somos".
2. Extraer con reglas: NIF/CIF (regex + dígito de control), teléfonos, emails, dirección, "inscrita en el Registro Mercantil de…, tomo…, folio…, hoja…".
3. Solo si faltan datos, extracción con LLM y salida estructurada.
4. Guardar la URL exacta de evidencia.

Cuidado con: webs hechas por una agencia que ponen **los datos de la agencia** en el aviso legal; grupos empresariales con un aviso legal común; plantillas sin rellenar; webs abandonadas (copyright antiguo).

## 4. Mapas

| Fuente | Qué aporta | Condiciones críticas |
|---|---|---|
| **Google Places API (New)** | Descubrimiento por categoría y zona, nombre, dirección de establecimiento, teléfono, web, `businessStatus` (p. ej. cerrado permanentemente), `place_id` | Las políticas de Places prohíben precargar, cachear o almacenar su contenido salvo excepciones; el **`place_id` sí puede guardarse indefinidamente**. Además hay **términos específicos para clientes con dirección de facturación en el EEE**: revisarlos. Consecuencia de diseño: Google sirve para **descubrir candidatos y verificar en vivo**, guardando el `place_id`; los datos que persistimos deben venir de fuentes que lo permitan (web propia, registros). Las búsquedas por texto devuelven un número limitado de resultados por consulta: hay que dividir la zona en rejilla |
| **OpenStreetMap** (Overpass/Nominatim) | Negocios con nombre, categoría, a veces teléfono y web | Licencia ODbL: permite reutilizar, pero una base de datos derivada que se distribuya públicamente puede quedar sujeta a compartir-igual. Cobertura de empresas B2B irregular. Nominatim público tiene límites de uso estrictos |
| Scrapers de Google Maps de terceros | Volumen alto y barato | Incumplen las condiciones de Google. **No recomendado** |

## 5. Buscadores web (para descubrir webs y fichas)

- APIs de búsqueda: Brave Search, Serper, SerpAPI, Tavily, Exa, u otras; la herramienta de búsqueda web de la API de Anthropic también sirve para el agente. Comparar precio, calidad para consultas locales en español y condiciones de uso (algunas APIs extraen resultados de Google, con su propio riesgo contractual).
- Uso: consultas del tipo `"reformas" "Dos Hermanas"`, `site:dominio.es aviso legal`, `"B12345678"` (buscar un NIF concreto para ver en qué webs aparece).
- **Los snippets no son evidencia**: sirven para encontrar URLs que luego se descargan y se leen.

## 6. Directorios

| Tipo | Ejemplos | Uso |
|---|---|---|
| Directorios generales | Páginas Amarillas, directorios de "empresas de España" basados en BORME, etc. | Descubrimiento y pistas. **Se copian entre sí** → mismo `grupo_independencia`. Muchos están desactualizados. La extracción sistemática de una parte sustancial puede vulnerar el derecho *sui generis* del fabricante de la base de datos |
| Directorios sectoriales y asociaciones | Asociaciones provinciales de constructores, colegios profesionales, cámaras de comercio, clústeres | Alta relevancia sectorial; revisar condiciones de cada una |
| Ferias y eventos | Listados de expositores | Buen indicador de actividad reciente |

## 7. Redes sociales

- **LinkedIn**: fuente evaluable como cualquier otra (ver D-10) por fiabilidad y coste técnico de acceso — con la salvedad práctica de que el scraping automatizado puede toparse con bloqueos/rate limits propios de la plataforma, no por restricción de diseño del proyecto. Guardar la URL pública de la página de empresa cuando aparece en la web corporativa o en resultados de buscador es siempre válido; explorar en Fase 2 si merece la pena un conector más profundo (rango de empleados, contactos).
- **Facebook / Instagram**: igual criterio (URL como identificador y señal de actividad: fecha de la última publicación visible si se obtiene de forma permitida).

## 8. Proveedores comerciales de datos (evaluar en Fase 2)

Informa D&B (eInforma), Axesor, Iberinform, Insight View, OpenCorporates, servicios basados en BORME con API, etc. Aportan NIF, CNAE, empleados, facturación y estado ya consolidados, con API.

- Pros: tamaño y facturación (lo más difícil de obtener), cobertura, rapidez.
- Contras: coste por registro, **condiciones de licencia** (a menudo prohíben revender o almacenar indefinidamente — no aplica a nuestro uso, que es interno, pero sí limita cómo se guarda/actualiza), y no son infalibles.
- Enfoque recomendado: usarlos como **una fuente más** con su fiabilidad, no como verdad absoluta; pedir prueba gratuita y medir contra el golden set.

## 9. Qué fuente usar para cada campo (resumen)

| Campo | Fuente primaria | Confirmación | Evitar como única fuente |
|---|---|---|---|
| NIF | Aviso legal web, PLACSP, REA, proveedor comercial | Dígito de control + segunda fuente | Directorios |
| Razón social | BORME, PLACSP, REA | Aviso legal web | Google (da nombre comercial) |
| Nombre comercial | Web, Google Places | Rótulo/marca en redes | — |
| Domicilio social | BORME (último acto) | Aviso legal web | Directorios |
| Sede operativa | Web (contacto), Google Places | CartoCiudad (normalización) | BORME (puede ser una gestoría) |
| Teléfono | Web propia | Google Places (verificación en vivo) | Directorios |
| Email | Web propia | — | Adivinar patrones (info@…) |
| Estado (activa/muerta) | BORME + revocaciones NIF | Places `businessStatus`, web viva, licitaciones recientes | Ausencia de datos |
| Tamaño | Proveedor comercial, cuentas depositadas | Señales (LinkedIn, nº de sedes, web) | Estimación LLM |
| CNAE / sector | Proveedor comercial, objeto social BORME | Clasificación LLM sobre la web | Categoría de Google sola |
