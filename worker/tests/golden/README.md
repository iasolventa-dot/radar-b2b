# Golden set

Aquí vive el conjunto de referencia verificado a mano (doc 07 §6): ~200 empresas del sector y zona piloto (construcción, Sevilla provincia — D-01, D-02), con casos difíciles a propósito (homónimos, franquicias, disueltas, traslados, autónomos, web con datos de agencia).

Pendiente — Fase 1, Paso 10 de la guía de montaje. Formato previsto:

- `golden_set.csv` — un registro por empresa, con las columnas de verdad de campo (NIF, razón social, estado, sede, teléfono, web) y cómo se verificó cada una.
- `README.md` (este archivo) ampliado con los criterios exactos de selección y verificación.
- `evaluar.py` — script que corre el pipeline contra el golden set y calcula las métricas del doc 01 §5 (precisión de identidad, tasa de duplicados, falsas fusiones…).

**Regla de oro** (doc 07 §6): ningún cambio de reglas de matching, fiabilidades o prompts se da por bueno sin evaluarlo antes contra este conjunto.
