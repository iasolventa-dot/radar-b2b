# 05 — Verificación, resolución de entidades y confianza

Este documento define **cómo decidimos que un dato es fiable** y **cuándo dos registros son la misma empresa**. Las reglas están implementadas en la skill `verificacion-empresas-es` (`scripts/lib_empresas.py`); si se cambian aquí, hay que cambiarlas allí (y viceversa). Los umbrales son valores iniciales: **se calibran con el golden set** (doc 07).

---

## 1. Normalización (determinista, antes de comparar nada)

| Campo | Normalización | Validación |
|---|---|---|
| **NIF/CIF** | Mayúsculas, sin espacios/guiones/puntos, sin prefijo `ES` | Dígito de control (CIF de sociedad, DNI, NIE, NIF especiales K/L/M). La **letra inicial** indica tipo de entidad: A=SA, B=SL, F=cooperativa, G=asociación/fundación, J=sociedad civil, E=comunidad de bienes, P/Q/S=administración… Si la letra no casa con la forma jurídica declarada → alerta |
| **Razón social** | Sin tildes, minúsculas, sin puntuación, **sin forma jurídica** (SL, SA, SLU, S.Coop.And., Sociedad Limitada…) → `razon_social_norm`. La forma jurídica se extrae a un campo aparte | Coherencia forma jurídica ↔ letra del NIF |
| **Teléfono** | Formato E.164 (`+34955123456`) | 9 dígitos en España; 6/7 móvil, 8/9 fijo; 900/901/902/905 = tarificación especial (no sirven como señal de identidad) |
| **Email** | Minúsculas, sin espacios | Sintaxis; el dominio tiene registro MX; clasificar **genérico** (info@, contacto@, administracion@…) vs. **personal** (nombre.apellido@ → dato personal) |
| **Web** | Dominio registrable sin `www` ni ruta (`perezobras.es`) | Excluir dominios de plataformas (facebook.com, wixsite.com, google.com, páginas de directorios): **no identifican a una empresa** |
| **Dirección** | Geocodificar con CartoCiudad → vía, número, CP, municipio INE, coordenadas, precisión | CP de 5 dígitos con prefijo 01-52; **los 2 primeros dígitos del CP deben coincidir con la provincia**; CP ↔ municipio coherente |

## 2. Resolución de entidades: ¿son la misma empresa?

### 2.1 Bloqueo (reducir comparaciones)
Solo se comparan registros que comparten al menos una clave de bloque: NIF, dominio, teléfono, `place_id`, o (primeras palabras distintivas del nombre + provincia). En BD: función `buscar_candidatos_empresa()` (similitud trigram + radio geográfico).

### 2.2 Reglas duras (se aplican primero, en este orden)

1. **NIF válido distinto en ambos → DISTINTAS.** Siempre. Aunque compartan nombre, web y teléfono (grupos de empresas, franquicias, sociedades hermanas).
2. **NIF válido igual en ambos → MISMA**, salvo que los nombres no se parezcan nada (similitud < 0,5 y sin coincidencia con nombre comercial): entonces **revisión** con alerta "posible NIF de tercero" (típico: el aviso legal muestra el NIF de la agencia que hizo la web).
3. **Mismo `place_id` de Google → mismo establecimiento** (puntuación 0,95), salvo que la regla 1 lo impida.
4. **Formas jurídicas distintas y conocidas** (SL vs SA): penalización fuerte; normalmente son empresas distintas.

### 2.3 Puntuación por señales (si ninguna regla dura decide)

| Señal | Aporte |
|---|---|
| Similitud de nombre ≥ 0,95 | +0,45 |
| Similitud de nombre ≥ 0,88 | +0,30 |
| Similitud de nombre ≥ 0,80 | +0,15 |
| Similitud de nombre < 0,50 (ambos con nombre) | −0,15 |
| Mismo dominio web (no plataforma) | +0,45 y **mínimo 0,60** (siempre al menos revisión) |
| Mismo teléfono (no especial, no compartido) | +0,35 |
| Mismo email | +0,25 |
| Distancia ≤ 50 m | +0,25 |
| Distancia ≤ 300 m | +0,15 |
| Distancia ≤ 2 km | +0,05 |
| Distancia > 50 km | −0,20 |
| Sin coordenadas: mismo CP | +0,10 |
| Sin coordenadas: provincia distinta | −0,20 |
| Formas jurídicas distintas | −0,30 |

- **Similitud de nombre**: la máxima entre todas las combinaciones razón social / nombre comercial de ambos registros, sobre nombres normalizados, con una mezcla 50/50 de las métricas *token set* y *token sort* (insensibles al orden). Solo *token set* daría 1,0 a "construcciones perez" frente a "construcciones perez sevilla", que suelen ser empresas distintas; la mezcla lo deja en ~0,92. La ñ se trata como n (igual que `unaccent` en Postgres), porque muchas fuentes escriben MUNOZ. **Palabras genéricas** (construcciones, reformas, servicios, grupo, sur, andalucía, obras, instalaciones…) se descuentan: si al quitarlas no queda ninguna palabra distintiva en común, el aporte del nombre se limita a +0,15. Así "Reformas y Construcciones del Sur SL" no se fusiona con cualquier otra "Construcciones del Sur".
- **Teléfonos compartidos**: si un teléfono aparece en más de 3 empresas con NIF distinto (gestorías, centralitas de polígono, agencias), se marca como compartido y deja de puntuar.
- **Direcciones compartidas**: igual con domicilios que aparecen en muchas empresas (domicilio social en una gestoría o un centro de negocios).

### 2.4 Decisión

| Puntuación | Decisión |
|---|---|
| ≥ 0,80 | **Fusión automática** (registrada en `fusiones` con instantánea para deshacer) |
| 0,55 – 0,80 | **Revisión**: primero arbitraje LLM; si el LLM dice "incierto" o su confianza es baja → cola humana |
| < 0,55 | **Distintas** |

### 2.5 Arbitraje LLM
Se le pasan ambos registros con **todas sus observaciones y fuentes**, las señales calculadas y las reglas de este documento. Responde en JSON: `{"veredicto": "misma|distinta|incierto", "confianza": 0-1, "motivos": [...], "datos_que_resolverian": [...]}`. El LLM **no inventa datos**: si necesita más información, lo dice en `datos_que_resolverian` (p. ej. "buscar el NIF en el aviso legal de X") y el planificador puede lanzar esa comprobación.

### 2.6 Casos difíciles conocidos

| Caso | Tratamiento |
|---|---|
| **Franquicias / marcas con licenciatarios** | Mismo nombre comercial, NIF distintos → empresas distintas. La marca puede guardarse como atributo |
| **Grupos empresariales** | Comparten web/teléfono; el NIF los separa. En el futuro, tabla de relaciones entre empresas |
| **Homónimos en distintas provincias** ("Construcciones García SL") | Penalización por distancia/provincia; nunca fusionar solo por nombre |
| **Cambio de denominación** (acto BORME) | Guardar la denominación anterior como identificador `denominacion_anterior`; es la misma empresa |
| **Traslado de domicilio** | Nueva sede; la anterior `activa=false`; evento en `eventos_empresa` |
| **Fusión por absorción** (BORME) | La absorbida pasa a extinguida con evento que apunta a la absorbente |
| **Domicilio social en gestoría** | No usar esa dirección como señal de identidad ni como sede operativa |
| **Autónomo con nombre comercial** ("Reformas Manolo") | Es persona física: el NIF es su DNI |
| **Web con datos de la agencia** | Regla dura 2 + comprobar que la razón social del aviso legal se parece al nombre de la empresa |
| **Nombre comercial ≠ razón social** ("Pérez Obras" / "Construcciones Pérez Martín SL") | La web (dominio + aviso legal) es el puente; sin puente, no fusionar por nombre |

## 3. Consolidación del registro oro (qué valor gana)

Para cada campo de una empresa:

1. Se agrupan las observaciones vigentes por valor normalizado.
2. **Confianza de un valor** = combinación de las fuentes **independientes** que lo afirman:
   `c = 1 − Π(1 − cᵢ)`, tomando solo la mayor `cᵢ` dentro de cada `grupo_independencia`.
   (Dos directorios que dicen lo mismo cuentan como uno.)
3. **Decaimiento por antigüedad**: `c_efectiva = c × 0,5^(días_desde_última_observación / semivida)`.
4. Gana el valor con mayor `c_efectiva`. Empate → el más reciente. Para razón social y domicilio social, prioridad a registro oficial.
5. **Campos multivalor** (teléfonos, emails): se guardan todos los que superan un umbral (0,5), ordenados por confianza.
6. **Conflicto**: si el segundo valor tiene `c_efectiva` > 0,7 y es distinto del primero, se registra evento de conflicto y la confianza del campo se rebaja.

### Semividas iniciales

| Campo | Semivida | Comentario |
|---|---|---|
| NIF, razón social, fecha de constitución | sin decaimiento | Solo cambian por actos del BORME, que se vigilan |
| Domicilio social | sin decaimiento | Ídem |
| Estado | 180 días | El BORME diario lo actualiza en tiempo real para sociedades |
| Sede operativa, dirección | 540 días | |
| Teléfono, email | 365 días | |
| Web viva | 90 días | Comprobación barata, se repite a menudo |
| Tamaño (empleados) | 365 días | |

### Fiabilidad de partida por fuente
Ver tabla `fuentes` (doc 03b). Registro oficial 0,95 · licitaciones 0,90 · web propia 0,85 · Google Places 0,80 · LinkedIn manual 0,60 · directorio 0,50 · snippet de buscador 0,40 · inferencia LLM 0,20. Puede afinarse por campo (p. ej. la web propia es excelente para teléfono pero regular para empleados).

**Un dato cuya única fuente es un LLM (`inferencia_llm`) nunca supera 0,2 y nunca se marca como verificado.**

## 4. Estado de la empresa (¿sigue existiendo?)

Se evalúan en este orden; la primera regla que aplica fija el estado:

1. BORME: extinción / cierre de hoja → **extinguida** (0,95).
2. BORME: disolución (con o sin liquidación) → **disuelta** / **en_liquidacion** (0,95).
3. BORME o BOE: concurso de acreedores → **en_concurso** (puede seguir operando).
4. BOE: revocación del NIF → **inactiva** (0,90).
5. Google Places: cerrado permanentemente (verificación en vivo) → **inactiva** si no hay señales positivas recientes; si las hay → **dudosa**.
6. Señales positivas (cada una de un grupo independiente): web viva y actualizada en los últimos 12 meses · adjudicación pública en los últimos 24 meses · acto societario no extintivo en BORME en los últimos 24 meses · Google Places operativo · actividad reciente en redes.
   - ≥ 2 señales → **activa**
   - 1 señal → **probablemente_activa**
   - señales positivas y negativas a la vez → **dudosa**
   - ninguna señal → **desconocida**

**Web viva** = responde 200, no es página de *parking* ni "en construcción", y hay alguna señal de actualización (año de copyright, fechas en noticias, `lastmod` del sitemap). Un dominio que no resuelve o está caducado es señal negativa.

## 5. Qué NO hacemos para verificar

- No "adivinamos" emails por patrón (`info@dominio`) ni los damos por válidos sin haberlos visto publicados.
- No sondeamos servidores de correo (SMTP RCPT) para comprobar buzones: poco fiable y puede considerarse abusivo.
- No damos un teléfono por válido solo porque tiene formato correcto: formato válido ≠ pertenece a la empresa.
- No fusionamos nunca solo por nombre.

## 6. Confianza global de la empresa

Media ponderada de las confianzas efectivas de: identidad (NIF + razón social) 40 % · estado 25 % · ubicación 15 % · contacto (mejor teléfono o email genérico) 20 %. Una empresa sin NIF confirmado no puede superar 0,6 de confianza global.
