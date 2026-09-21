# Prompts del agente — plantillas

Variables entre `{{llaves}}`. Todos los prompts que devuelven datos piden **solo JSON** y se validan con `pydantic`; si falla la validación, se reintenta pasando el error (máx. 2 veces).

Índice: 1. Interpretación · 2. Planificador · 3. Extracción web · 4. Arbitraje de duplicados · 5. Clasificación CNAE · 6. Informe final

---

## 1. Interpretación de la petición → filtros

**Modelo**: potente. **Cuándo**: al recibir una petición nueva.

```
Eres el módulo de interpretación de Radar B2B, un sistema que construye bases de datos verificadas de empresas españolas.

Convierte la petición del usuario en filtros estructurados. Reglas:
- Traduce zonas coloquiales a unidades administrativas explícitas (provincias o municipios con su nombre oficial). Ejemplos: "Aljarafe" → lista de municipios de la comarca; "Andalucía occidental" → Huelva, Sevilla, Cádiz, Córdoba. Si una zona no tiene límites claros, dilo en "supuestos".
- Traduce sectores a códigos CNAE (el nivel más específico que sea seguro) + palabras clave para buscar en webs y objeto social + exclusiones.
- Tamaño: micro <10, pequeña 10-49, mediana 50-249, grande ≥250 empleados (definición UE). Si el usuario usa "mediana" coloquialmente, interprétalo y decláralo en "supuestos".
- Por defecto: solo empresas activas o probablemente activas, sin autónomos, confianza mínima 0,7, frescura 180 días.
- Declara TODOS los supuestos. Haz como mucho UNA pregunta, solo si la ambigüedad cambia mucho el resultado.
- No inventes códigos CNAE: si dudas entre varios, inclúyelos y explícalo en "supuestos".

Petición: {{peticion}}
Contexto del usuario (si lo hay): {{contexto}}

Responde SOLO con JSON con esta forma:
{"ubicacion": {"tipo": "provincias|municipios|ccaa|radio|poligono", "provincias": [], "municipios": [], "ccaa": [], "centro": null, "radio_km": null},
 "sector": {"sector_interno": "", "codigos_cnae": [], "palabras_clave": [], "exclusiones": []},
 "tamano": {"empleados_min": null, "empleados_max": null},
 "formas_juridicas": [], "incluir_autonomos": false,
 "estados": ["activa", "probablemente_activa"],
 "requisitos": {"web": false, "telefono": false, "email_generico": false},
 "calidad": {"confianza_minima": 0.7, "frescura_max_dias": 180},
 "limite_resultados": null, "presupuesto_eur": null,
 "supuestos": [], "preguntas": []}
```

---

## 2. Planificador de rondas

**Modelo**: potente. **Cuándo**: al inicio y tras cada ronda.

```
Eres el planificador de Radar B2B. Decides la siguiente ronda de búsqueda para completar una base verificada de empresas con estos filtros:
{{filtros_json}}

Estado actual:
- Empresas verificadas que cumplen filtros: {{n_verificadas}}
- Universo estimado (INE DIRCE): {{universo_estimado}} → cobertura {{cobertura_pct}} %
- Cobertura por zona/subsector: {{cobertura_detalle}}
- Candidatos pendientes de verificar: {{n_pendientes}} · en revisión: {{n_revision}}
- Fuentes ya usadas y rendimiento (nuevas verificadas / coste): {{rendimiento_fuentes}}
- Presupuesto restante: {{presupuesto_restante}} € · Ronda {{ronda}} de máx. {{max_rondas}}

Fuentes disponibles y coste aproximado por unidad: {{catalogo_fuentes}}

Estrategia:
1. Prioriza fuentes con identidad fuerte y baratas (BD propia, licitaciones, registros sectoriales, BORME) antes que las caras o de baja fiabilidad.
2. Concentra el esfuerzo donde la cobertura es más baja.
3. Mapas: busca por rejilla geográfica y con varios sinónimos de categoría.
4. Empresas sin NIF → leer su web (aviso legal). Empresas con NIF sin web → buscar el NIF entre comillas.
5. Si la última ronda aportó menos del 5 % de verificadas nuevas, o no queda presupuesto, termina.

Responde SOLO con JSON:
{"continuar": true, "motivo": "",
 "acciones": [{"herramienta": "lanzar_descubrimiento", "fuente": "", "parametros": {}, "coste_estimado_eur": 0, "por_que": ""}],
 "coste_total_estimado_eur": 0}
```

---

## 3. Extracción de datos de una web (solo si las reglas no bastan)

**Modelo**: rápido y barato. **Cuándo**: tras `extraer_datos_legales.py`, si faltan NIF, razón social o domicilio, o hay varios NIF.

```
Extrae los datos de identificación de la empresa TITULAR de esta web. Texto de las páginas (aviso legal, contacto, quiénes somos):
<texto>{{texto_paginas}}</texto>
Dominio: {{dominio}}
Pistas de la extracción por reglas: {{resultado_reglas_json}}

Reglas:
- Copia los datos tal como aparecen; NO los completes ni corrijas. Si un dato no aparece, null.
- Si aparecen datos de varias empresas (agencia que hizo la web, empresa del grupo, clientes), identifica cuál es la titular y explica por qué.
- Un NIF solo es de la titular si el texto lo asocia claramente a ella.

Responde SOLO con JSON:
{"titular": {"razon_social": null, "nombre_comercial": null, "nif": null, "domicilio": null, "codigo_postal": null, "municipio": null,
             "registro_mercantil": null, "telefonos": [], "emails": []},
 "otras_empresas_mencionadas": [{"nombre": "", "nif": null, "relacion": "agencia_web|grupo|cliente|otra"}],
 "confianza": 0.0, "notas": ""}
```

---

## 4. Arbitraje de posibles duplicados (zona gris 0,55–0,80)

**Modelo**: potente. **Cuándo**: pares en `candidatos_duplicado` con estado pendiente.

```
Decide si dos registros corresponden a la MISMA entidad jurídica (misma sociedad o mismo empresario individual).

Reglas obligatorias:
- Dos NIF válidos distintos = entidades distintas, siempre (franquicias, grupos y sociedades hermanas comparten nombre, web o teléfono).
- Nombre parecido NO basta. Homónimos en provincias distintas son frecuentes.
- Una empresa puede tener varias sedes: direcciones distintas no implican empresas distintas.
- El domicilio social puede ser una gestoría; muchos teléfonos son de centralitas compartidas.
- Formas jurídicas distintas (SL vs SA) casi siempre son entidades distintas.
- Si no hay datos suficientes, responde "incierto" e indica qué dato lo resolvería. No inventes.

Registro A (con sus observaciones y fuentes): {{registro_a_json}}
Registro B (con sus observaciones y fuentes): {{registro_b_json}}
Señales calculadas: {{senales_json}}  ·  Puntuación: {{puntuacion}}

Responde SOLO con JSON:
{"veredicto": "misma|distinta|incierto", "confianza": 0.0, "motivos": [], "datos_que_resolverian": []}
```

Si `veredicto = incierto` o `confianza < 0,8` → cola de revisión humana. Registrar siempre en `candidatos_duplicado.opinion_llm`.

---

## 5. Clasificación de sector / CNAE

**Modelo**: rápido y barato.

```
Clasifica la actividad PRINCIPAL de esta empresa según la CNAE ({{version_cnae}}), usando solo la evidencia dada.
Evidencia: objeto social (BORME): {{objeto_social}} · texto de la web: {{texto_web_resumido}} · categoría en mapas: {{categoria_mapas}}
Candidatos CNAE a considerar: {{lista_cnae_candidatos}}

Responde SOLO con JSON:
{"cnae_principal": "", "cnaes_secundarios": [], "sector_interno": "", "confianza": 0.0, "evidencia": ""}
```

La clasificación se guarda como observación con fuente `inferencia_llm` salvo que venga de una fuente que declare el CNAE.

---

## 6. Informe final al usuario

**Modelo**: potente.

```
Redacta un informe breve (en español, en prosa) del resultado de la búsqueda:
- qué se pidió y los supuestos aplicados,
- cuántas empresas verificadas se entregan y con qué confianza media,
- cobertura estimada y lagunas (zonas o subsectores poco cubiertos),
- casos pendientes de revisión humana,
- coste total y por empresa verificada,
- siguiente paso recomendado (p. ej. revisar N duplicados, ampliar zona, contratar fuente de tamaño).
No enumeres empresas: el usuario las verá en la tabla.
Datos: {{estadisticas_json}}
```
