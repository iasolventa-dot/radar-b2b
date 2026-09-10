# 07 — Diseño del agente y evaluación

Plantillas concretas (prompt de sistema del agente de producción, definiciones JSON de herramientas, checklist de conectores) en la skill `agente-busqueda-empresas`.

## 1. Qué hace el agente (y qué no)

El agente es el **orquestador inteligente** del pipeline del doc 02. Sus tareas:

1. **Interpretar** la petición del usuario y convertirla en filtros estructurados, preguntando solo lo ambiguo.
2. **Planificar** rondas de búsqueda: qué fuentes, con qué consultas, en qué zonas, con qué presupuesto.
3. **Supervisar** el progreso: cobertura estimada, verificadas, pendientes de revisión, coste.
4. **Decidir** cuándo parar.
5. **Informar** al usuario del resultado con transparencia (qué se encontró, con qué confianza, qué falta).

Lo que **no** hace: escribir directamente en la base de datos, inventar datos, decidir fusiones fuera de la zona gris, ni descargar páginas enteras a su contexto. Todo eso lo hacen las herramientas (código) y devuelven **resúmenes compactos**.

## 2. Asignación de modelos (orientativa, verificar modelos y precios vigentes)

| Tarea | Volumen | Modelo |
|---|---|---|
| Interpretar petición, planificar rondas, redactar informe | Bajo | Modelo potente (familia Sonnet u Opus) |
| Arbitraje de duplicados en zona gris | Medio | Modelo potente |
| Extracción de datos de páginas web (aviso legal, contacto) | Alto | Modelo rápido y barato (familia Haiku), con salida estructurada |
| Clasificación de sector/CNAE a partir de la web | Alto | Modelo rápido y barato |

## 3. Paso 1: interpretación → filtros

Salida estructurada que se muestra al usuario para confirmar:

```json
{
  "ubicacion": {"tipo": "provincias", "provincias": ["Sevilla", "Huelva"], "municipios_ine": [], "centro": null, "radio_km": null},
  "sector": {"sector_interno": "Construcción de edificios", "codigos_cnae": ["41"], "palabras_clave": ["constructora", "obra nueva", "rehabilitación"], "exclusiones": ["promotora sin obra propia"]},
  "tamano": {"empleados_min": 10, "empleados_max": 49},
  "formas_juridicas": ["SL", "SA"],
  "incluir_autonomos": false,
  "estados": ["activa", "probablemente_activa"],
  "requisitos": {"web": false, "telefono": true, "email_generico": false},
  "calidad": {"confianza_minima": 0.7, "frescura_max_dias": 180},
  "limite_resultados": 500,
  "presupuesto_eur": 20,
  "supuestos": ["'medianas' interpretado como 10-49 empleados (pequeña empresa según UE); confirmar"],
  "preguntas": []
}
```

Reglas: mapear zonas coloquiales ("Aljarafe", "Andalucía occidental") a listas de municipios/provincias explícitas; mapear sectores a CNAE + palabras clave; declarar siempre los **supuestos**; como máximo una pregunta al usuario si algo es realmente ambiguo.

## 4. Paso 2-8: bucle del planificador

```
estado = consultar_bd(filtros)                     # lo ya verificado y fresco
cobertura = estimar_cobertura(filtros)             # universo aprox. (INE DIRCE) vs. lo que tenemos
mientras no condicion_parada(estado, cobertura, presupuesto):
    plan = LLM.planificar(filtros, estado, cobertura, fuentes_usadas, presupuesto_restante)
    #  p. ej. [PLACSP por CPV de obras en Sevilla, Places en rejilla de 2 km sobre Dos Hermanas, buscador "constructora" + 12 municipios]
    ejecutar(plan)                                  # conectores → registros_brutos (cola pgmq)
    enriquecer_pendientes(); arbitrar_duplicados()  # web propia, normalización, matching, verificación (código)
    estado = consultar_bd(filtros); registrar_coste()
informe = LLM.redactar_informe(estado)
```

**Condiciones de parada** (cualquiera): presupuesto agotado · cobertura estimada ≥ objetivo · rendimientos decrecientes (la última ronda aportó < 5 % de empresas verificadas nuevas) · máximo de rondas (p. ej. 5).

**Estrategias que el planificador debe conocer**:
- Empezar por fuentes baratas y con identidad fuerte (BD propia, PLACSP, REA, BORME) antes que por las caras o de baja fiabilidad.
- Google Places por **rejilla** geográfica (las búsquedas devuelven un número limitado de resultados) y por varias categorías/sinónimos.
- Para empresas sin NIF: buscar la web → aviso legal. Para empresas con NIF sin web: buscar el NIF entre comillas en el buscador.
- Concentrar esfuerzo donde la cobertura estimada es más baja (por municipio o por subsector).

## 5. Herramientas (resumen; esquemas completos en la skill)

| Herramienta | Qué hace | Devuelve al agente |
|---|---|---|
| `consultar_bd` | Busca en la BD propia con filtros | Recuento y muestra de empresas + estadísticas de calidad |
| `estimar_cobertura` | Universo aproximado por CNAE × provincia × tamaño (INE DIRCE) | Estimación y % cubierto |
| `lanzar_descubrimiento` | Encola trabajos de un conector con parámetros | Id del trabajo |
| `estado_trabajos` | Progreso de los trabajos encolados | Candidatos, nuevas, vinculadas, en revisión, errores, coste |
| `enriquecer_pendientes` | Web propia (aviso legal, contacto), normalización, matching y confianza de los candidatos nuevos | Id del trabajo y coste estimado |
| `arbitrar_duplicados` | Arbitraje de pares en zona gris 0,55-0,80 (prompt de la skill); lo incierto va a revisión humana | Nº de pares misma / distinta / incierto |
| `verificar_empresa` | Verificación profunda de una empresa concreta (identidad, estado, contacto) | Resultado y confianza por campo |
| `preguntar_usuario` | Aclaración (máx. una por búsqueda salvo necesidad) | Respuesta |
| `finalizar_busqueda` | Cierra y genera informe y exportación | Enlace a resultados |

## 6. Evaluación: el golden set

Sin un conjunto de referencia **no se puede afirmar que la base está "bien contrastada"**. Es lo primero que se construye en la Fase 1.

### Cómo construirlo
1. Elegir **zona y sector piloto** (p. ej. un municipio mediano del área metropolitana de Sevilla + construcción, CNAE 41-43).
2. Reunir el universo de candidatos desde varias fuentes.
3. Verificar a mano ~200 entidades: NIF, razón social, nombre comercial, estado, sede operativa, teléfono (llamar a una muestra), web. Anotar fuente y fecha.
4. Incluir **a propósito** casos difíciles: homónimos, franquicias, grupos, disueltas, traslados, autónomos, web con datos de agencia, nombres genéricos.
5. Guardarlo versionado en `worker/tests/golden/` (CSV + README con criterios).

### Métricas (se calculan automáticamente tras cada cambio)
- Precisión y exhaustividad de **pares de duplicados** (fusiones correctas, fusiones erróneas, duplicados no detectados).
- Precisión por campo: NIF, razón social, teléfono, dirección, estado.
- % de empresas inactivas que se cuelan como activas.
- Cobertura sobre el golden set (¿cuántas de las 200 encuentra el pipeline partiendo de cero?).
- Coste total y por empresa verificada.

### Regla de oro del desarrollo
Cualquier cambio en reglas de matching, fiabilidades o prompts **se evalúa contra el golden set antes de darlo por bueno**. Si una métrica de precisión baja, el cambio no entra aunque suba la cobertura.

## 7. Interfaz (Fase 3)

- Chat con el agente (el usuario ve los filtros interpretados y los confirma).
- Progreso de la búsqueda en vivo (rondas, fuentes, verificadas, coste).
- Tabla con filtros + mapa; cada celda muestra su confianza y, al pasar el ratón, fuente y fecha.
- Cola de revisión de duplicados (dos fichas lado a lado, señales y opinión del LLM; botones "misma", "distinta", "aplazar").
- Exportación CSV/Excel con columnas de confianza, fuente principal y fecha de verificación.
