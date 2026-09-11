# Golden set — metodología

Conjunto de referencia verificado **una vez, por una persona** (doc 07 §6; skill `agente-busqueda-empresas`, `references/evaluacion.md`). No es parte del pipeline en producción — el pipeline (descubrimiento, matching, verificación) es y sigue siendo 100% automático. El golden set es la única forma de **medir** si ese pipeline automático acierta: hace falta una respuesta correcta que no haya sido generada por el propio sistema que se está midiendo (si lo fuera, solo comprobaríamos que el sistema está de acuerdo consigo mismo). Es el mismo motivo por el que un conjunto de test en machine learning se etiqueta aparte del modelo. Una vez construido, `evaluar.py` lo usa de forma automática cada vez que cambia una regla o un prompt.

Cualquier cambio en reglas de matching, fiabilidades o prompts se evalúa contra este conjunto antes de aceptarlo — si una métrica de precisión baja, el cambio no entra aunque suba la cobertura.

## 0. Qué parte es automática y qué parte no (actualizado 2026-09-10, D-12)

Se construyó y **se ejecutó de verdad** un conector BORME (`worker/radar/fuentes/borme.py`, con tests contra fixtures reales y probado en vivo contra el API del BOE) que genera candidatos sin intervención humana.

**Aviso de calidad detectado y corregido en la primera versión**: el primer filtro (buscar palabras como "construcción" en cualquier parte del objeto social) daba muchos falsos positivos, porque el objeto social de una SL española suele listar decenas de actividades como boilerplate ("todo tipo de actividades") aunque la empresa real sea, por ejemplo, un restaurante — "Construcción, instalaciones y mantenimiento" aparecía junto a hostelería, comercio, etc. sin que la empresa fuera del sector. Se corrigió exigiendo que la construcción sea la **actividad principal por código CNAE** declarado (`confianza=alta`, CNAE 41-43 como actividad principal) o que aparezca como código CNAE explícito aunque sea secundario (`confianza=media`); lo que solo coincide por palabra suelta sin ningún código CNAE se aparta a `revisar_objeto_generico` en vez de contar como candidato "normal". Esto es justo el principio nº1 del proyecto (calidad antes que volumen) aplicado a la propia generación de candidatos, no solo a la base final.

Resultado real de la ejecución corregida (180 días, provincia de Sevilla, 2026-09-10):

| Categoría | Candidatos automáticos obtenidos | Objetivo (§2) |
|---|---:|---:|
| Normales, confianza alta o media (CNAE 41-43 explícito) | 140 | 140 |
| Grupo empresarial (mismo administrador, distinta hoja registral) | 10 | 10 |
| Homónimo (nombre muy parecido, distinta hoja registral — fuzzy matching) | 1 | 10 |
| Disuelta (disolución/extinción + nombre sugiere construcción) | 28 | 10 |
| Traslado (cambio de domicilio + nombre sugiere construcción) | 22 | 10 |
| *Aparte:* revisar_objeto_generico (palabra suelta, sin CNAE — descartados del pool "normal") | 489 | — |
| **Total candidatos de calidad aceptable en `registros_entrada.csv`** | **201** | — |

Con esto, **normales, grupo, disuelta y traslado ya están cubiertos** con candidatos de confianza alta/media y su URL de evidencia. Falta ampliar **homónimos** (1 de 10) — se resuelve ampliando la ventana de días (`--dias 365` o más), ya que exigir CNAE explícito redujo mucho el pool donde el fuzzy-matching podía encontrar coincidencias.

Lo que el conector **no puede** hacer, y sigue siendo trabajo humano (mucho más acotado que antes):

- **NIF**: el BORME no lo publica en los anuncios (solo razón social, domicilio y "hoja registral" del Registro Mercantil). Hay que confirmarlo con REA, la web/aviso legal de la empresa, o una consulta puntual a un proveedor tipo e-informa.
- **Teléfono y web**: no están en el BORME. Se sacan de Google Maps/la propia web.
- **Autónomos**: el BORME es el registro **mercantil** — no cubre personas físicas. Esta categoría (5 entidades) sigue siendo 100% búsqueda manual (Google Maps, directorios).
- **Franquicias** y **web con aviso legal de agencia**: no hay señal fiable en el texto del BORME para detectarlas automáticamente; se identifican revisando las webs de los candidatos ya generados, no buscándolas desde cero.
- **Nombre genérico**: se puede elegir a ojo entre los 140 candidatos "normales" ya generados (es la categoría más barata de completar).
- **Confirmar que cada candidato automático es realmente del sector y está realmente activo/disuelto**: incluso con el filtro corregido, `confianza=media` (CNAE secundario) y las categorías `disuelta`/`traslado` (heurística por nombre, sin objeto social disponible) pueden fallar — cada fila lleva su `url_evidencia` para que la revisión sea rápida (leer el anuncio, no buscarlo).

Estimación de esfuerzo humano restante, con el pool ya generado: revisar y promover ~200 filas de `registros_entrada.csv` a `entidades.csv` (confirmar NIF/teléfono/web, descartar falsos positivos) + buscar desde cero las ~5 de autónomos ≈ **6-8 horas**, frente a las 21-23 horas estimadas cuando todo el sourcing era manual.

## 1. Alcance piloto (decidido)

- **Sector**: construcción, CNAE 41-43 (Construcción de edificios, Ingeniería civil, Actividades de construcción especializada), coherente con D-01/D-02.
- **Zona principal**: **Alcalá de Guadaíra** (Sevilla) como "municipio mediano del área metropolitana de Sevilla" (doc 07 §6). El resto de la provincia de Sevilla se usa como ampliación (hasta 50 de las 200) para no depender de un solo municipio en los casos difíciles.
- Alcance fijado por decisión delegada (el usuario dejó el criterio de zona/sector a mi juicio); ver D-11.

Nota: en la ejecución real, muy pocos candidatos cayeron exactamente en Alcalá de Guadaíra dentro de la ventana de 180 días (columna `es_municipio_principal` en `registros_entrada.csv`) — es zona industrial/logística más que de constituciones societarias nuevas. Si al promover candidatos a `entidades.csv` no hay suficientes con `es_municipio_principal=si`, se amplía la ventana de días o se acepta que el "municipio mediano" ancla represente una fracción menor del total, coherente con la ampliación ya prevista al resto de la provincia.

## 2. Tamaño y desglose por dificultad

Objetivo: **200 entidades**, deliberadamente con casos trampa (doc 07 §6):

| Categoría | Cantidad | Qué debe tener | Fuente del candidato |
|---|---:|---|---|
| Caso normal | 140 | NIF válido, un establecimiento, datos consistentes entre fuentes | Automática (BORME, `pool_normal_construccion`) |
| Homónimos | 10 | Razón social parecida, NIF distinto, empresas realmente distintas | Automática (BORME, `candidato_homonimo`, fuzzy matching) |
| Franquicias / cadenas | 10 | Misma marca, NIF distinto por delegación | Manual, a partir de las webs de los candidatos normales |
| Grupos empresariales | 10 | Varias sociedades relacionadas (mismo administrador), NIF propio cada una | Automática (BORME, `candidato_grupo`, mismo administrador) |
| Disueltas / de baja | 10 | Acto de disolución/extinción en BORME | Automática (BORME, `candidato_disuelta`) |
| Traslados de domicilio | 10 | Domicilio social distinto de la sede operativa, o cambio reciente | Automática (BORME, `candidato_traslado`) |
| Autónomos | 5 | Persona física de alta como constructora/reformista | Manual (BORME no cubre autónomos) |
| Web con aviso legal de agencia | 3 | Aviso legal de la web muestra el NIF de la agencia, no el de la constructora | Manual, revisando webs de candidatos normales |
| Nombre genérico | 2 | Razón social tipo "Reformas y Construcciones del Sur SL" | Manual, a elegir entre los candidatos normales ya generados |
| **Total** | **200** | | |

## 3. Cómo se generó el pool automático

`worker/radar/fuentes/borme.py` (conector, con tests en `worker/tests/unit/test_borme.py` contra fixtures reales en `worker/tests/fixtures/borme/`) + `worker/scripts/generar_candidatos_golden.py` (orquestación y heurísticas de filtrado):

1. Recorre día a día el sumario del BORME (`GET /datosabiertos/api/borme/sumario/{fecha}`, API pública y gratuita del BOE, verificada el 2026-09-10) para la provincia de Sevilla, sección A ("Empresarios. Actos inscritos").
2. Parsea cada acto (razón social, tipo de acto, domicilio/CP/municipio, hoja registral, objeto social si es una constitución, administradores nombrados).
3. Clasifica automáticamente:
   - **Constitución** con la "Actividad principal" declarada en CNAE 41-43 (`confianza=alta`) o con algún código CNAE 41-43 secundario (`confianza=media`) → `pool_normal_construccion`. Si solo coincide una palabra suelta sin ningún código CNAE explícito (objeto social "todo tipo de actividades") → `revisar_objeto_generico`, aparte del pool "normal".
   - **Disolución/extinción** + razón social con palabras de construcción (heurística débil por nombre, ya que el BORME no repite el objeto social en estos actos) → `candidato_disuelta`.
   - **Cambio de domicilio social** + misma heurística → `candidato_traslado`.
   - Dos candidatos con el **mismo administrador** y distinta hoja registral → ambos pasan a `candidato_grupo`.
   - Dos candidatos con nombre **igual o muy parecido** (similitud difusa, `rapidfuzz`, umbral 88/100) y distinta hoja registral → ambos pasan a `candidato_homonimo`.
4. Cada fila guarda su URL de evidencia (`url_evidencia`, el HTML oficial del BORME) — nunca se inventa un dato: lo que no está en el texto del BORME queda vacío.

Para regenerar o ampliar el pool (por ejemplo, con una ventana de más días si faltan homónimos, o para refrescarlo dentro de unos meses):

```powershell
cd C:\Users\32759\radar-b2b\worker
.venv\Scripts\Activate.ps1
python scripts\generar_candidatos_golden.py --dias 180
python scripts\generar_candidatos_golden.py --dias 365 --municipio-principal "ALCALA DE GUADAIRA"
```

No hace falta ninguna clave ni coste: el API del BOE es público y gratuito.

## 4. `registros_entrada.csv` (candidatos, generado automáticamente)

Una fila = un acto del BORME clasificado como candidato. No es todavía "verdad verificada" — es la lista de dónde buscar, con la categoría propuesta y la evidencia. Columnas: `id_fila`, `categoria_candidato`, `confianza_sector` (`alta`/`media`/`baja`/vacío — ver §0), `fuente`, `id_externo` (id del acto BORME), `razon_social`, `municipio`, `codigo_postal`, `es_municipio_principal`, `hoja_registral`, `tipos_acto`, `objeto_social`, `capital_eur`, `administradores`, `posible_homonimo_de`, `posible_grupo_con`, `url_evidencia`, `fecha_publicacion`, `identificador_boletin`, `entidad_id_real` (vacío hasta que se promueve a `entidades.csv`), `notas`.

## 5. Esquema de columnas de `entidades.csv`

Una fila = una entidad **verificada** (verdad de referencia). Nombres en `snake_case`, alineados con doc 03. Se rellena promoviendo filas de `registros_entrada.csv` una vez confirmado el NIF y contrastados los datos con al menos dos fuentes:

| Columna | Significado | Ejemplo / formato |
|---|---|---|
| `id_golden` | Identificador correlativo | `GS-0001` |
| `nif` | NIF/CIF con dígito de control (vacío + motivo en `notas` si no se localiza) | `B91234567` |
| `razon_social` | Razón social completa (viene de `registros_entrada.csv`) | |
| `nombre_comercial` | Si difiere de la razón social | |
| `forma_juridica` | SL, SLU, SA, SAU, SCOOP, CB, Autónomo... | `SL` |
| `es_persona_fisica` | `si`/`no` | `no` |
| `cnae_principal` | Código CNAE si se localiza | `4120` |
| `estado` | `activa`, `probablemente_activa`, `disuelta`, `inactiva` | `activa` |
| `municipio`, `municipio_ine`, `provincia`, `cp` | Sede que se verifica (operativa si se conoce) | |
| `direccion_domicilio_social` | Del BORME | |
| `direccion_sede_operativa` | Si es distinta de la social | |
| `telefono`, `telefono_verificado_llamada` | E.164; `si`/`no`/`no_aplica` (la llamada es opcional, ver §6) | |
| `web`, `email_generico` | | |
| `caso_dificil` | Vacío o: `homonimo`, `franquicia`, `grupo`, `disuelta`, `traslado`, `autonomo`, `web_agencia`, `nombre_generico` | |
| `fuente_verificacion` | Fuentes usadas, separadas por `;` | `BORME;REA;web_corporativa` |
| `url_evidencia` | URLs concretas, separadas por `;` (incluir la de `registros_entrada.csv`) | |
| `fecha_verificacion`, `verificado_por`, `notas` | | |

## 6. Lo que sigue siendo manual, y por qué está bien que lo sea

El pipeline en producción es automático de principio a fin (doc 07 §1). El golden set es la excepción deliberada: su verdad tiene que venir de fuera del sistema que se está evaluando, o la medición no significa nada. Con el pool ya generado, lo manual se reduce a:

1. Promover ~200 filas de `registros_entrada.csv` a `entidades.csv`, confirmando NIF/estado con REA o la web de cada una (2-3 fuentes por fila, con `url_evidencia` ya a mano).
2. Buscar desde cero las ~5 entidades de autónomos (el BORME no las cubre).
3. Revisar las webs de un puñado de candidatos normales para identificar los 10 de franquicia, 3 de web-agencia y 2 de nombre genérico.
4. *(Opcional)* Llamar a una muestra de 20-30 teléfonos — la parte más manual de todas; se puede omitir sin invalidar el golden set (`telefono_verificado_llamada=no_aplica`).

## 7. Criterios de aceptación de una fila

1. El NIF pasa la validación de dígito de control (o se anota por qué no hay NIF verificable).
2. Al menos dos fuentes independientes coinciden en razón social y NIF, o una fuente oficial (BORME/REA) sola basta para esos dos campos.
3. `estado` refleja la fuente más reciente (una disolución posterior manda sobre cualquier "activa" previo).
4. Si es un caso difícil, `notas` explica en una frase por qué lo es.

## 8. Archivos de este directorio

- `registros_entrada.csv` — candidatos generados automáticamente por `generar_candidatos_golden.py` (690 filas reales, ventana de 180 días, generado 2026-09-10; 201 de confianza alta/media + `disuelta`/`traslado`, 489 en `revisar_objeto_generico`). Punto de partida, no verdad verificada.
- `entidades.csv` — plantilla con la cabecera definitiva (§5) y filas de ejemplo **claramente marcadas como ficticias**. Las 200 filas reales se añaden promoviendo candidatos de `registros_entrada.csv`.
- `evaluar.py` — esqueleto de evaluación (skill `agente-busqueda-empresas`), con tests en `tests/unit/test_evaluar_golden.py` sobre la lógica de métricas. Necesita `entidades.csv` con datos reales y un `clusters.csv` real del pipeline de resolución (todavía por construir) para ejecutarse de verdad.
- `README.md` (este archivo).

**Regla de oro** (doc 07 §6): ningún cambio de reglas de matching, fiabilidades o prompts se da por bueno sin evaluarlo antes contra este conjunto.
