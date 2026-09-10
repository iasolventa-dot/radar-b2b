# 06 — Marco legal y cumplimiento

> **Archivado (2026-09-10, ver D-10).** Este documento ya no rige el diseño del proyecto: el foco actual es la capacidad técnica del agente (descubrir, clasificar, verificar empresas y empresarios), sin restricciones derivadas de RGPD/LOPDGDD/LSSI en el modelo de datos ni en las fuentes (autónomos, contactos personales, LinkedIn y otras redes sociales incluidos). El uso es estrictamente interno y los datos no se venden ni se hacen públicos (D-03). Se conserva como mapa de riesgos por si en el futuro se retoma esta dimensión.

> **Esto no es asesoramiento jurídico.** Es un mapa de riesgos para diseñar con cabeza y para llevar preguntas concretas a un abogado especializado en protección de datos y propiedad intelectual. Antes de la Fase 2 (descubrimiento masivo) y, sobre todo, antes de vender datos a terceros (Fase 5), hay que validarlo profesionalmente.

## 1. Datos de empresas vs. datos personales

- Los datos de **personas jurídicas** (una SL, una SA: su razón social, NIF, domicilio, teléfono general, `info@`) **no son datos personales** según el RGPD (considerando 14). Es el núcleo del producto y el terreno más seguro.
- Son **datos personales** y activan RGPD + LOPDGDD:
  - **Autónomos / empresarios individuales**: su NIF es su DNI; su nombre suele ser el nombre del negocio; su móvil suele ser personal.
  - **Personas de contacto**: nombres, cargos, emails tipo `nombre.apellido@empresa.es`, móviles directos.
  - **Administradores** que aparecen en el BORME.
- El modelo de datos lo refleja con `empresas.es_persona_fisica` y `canales_contacto.es_generico`.

## 2. Si tratamos datos personales (autónomos, contactos)

- **Base jurídica**: normalmente el **interés legítimo** (art. 6.1.f RGPD). La LOPDGDD (art. 19) presume el interés legítimo para tratar los **datos de contacto y la función** de personas que trabajan en una empresa y los datos de **empresarios individuales**, siempre que se usen para relacionarse con la empresa o con ellos **en su condición de empresarios**, no como particulares. Aun así, conviene documentar una **evaluación del interés legítimo**.
- **Deber de informar** cuando los datos no se obtienen del interesado (art. 14 RGPD): como regla, en el plazo de un mes o, a más tardar, en la primera comunicación. Hay que prever cómo se cumple.
- **Derechos**: oposición, supresión, acceso. El sistema debe poder **encontrar y borrar/bloquear a una persona** y no volver a incorporarla (lista de exclusión).
- **Minimización**: no recoger lo que no se necesita (ni fotos, ni perfiles personales de redes, ni datos de vida privada).
- **Registro de actividades de tratamiento**, plazo de conservación y medidas de seguridad.
- **Encargados del tratamiento**: si se envían datos personales a APIs de LLM o a proveedores, revisar sus acuerdos de tratamiento de datos (DPA) y las transferencias internacionales.
- Que un dato sea **accesible públicamente** (BORME, una web) **no** permite por sí mismo cualquier uso: la finalidad debe ser compatible y legítima.

**Recomendación de diseño (histórica, no vigente — ver banner superior)**: en el MVP, limitarse a datos de empresa (personas jurídicas) y canales genéricos. Los autónomos se pueden incluir marcados como tales, con canales genéricos y la lógica de exclusión preparada. Contactos personales, solo tras revisión legal.

## 3. Uso posterior de la base: comunicaciones comerciales

La base se usará para prospección, así que el diseño debe facilitar el cumplimiento:

- **Email comercial (LSSI, art. 21)**: prohíbe enviar comunicaciones comerciales por correo electrónico o medios equivalentes que no hayan sido solicitadas o autorizadas previamente, salvo relación contractual previa. En la interpretación habitual en España esto aplica también a destinatarios que son empresas. Consecuencia: **tener emails no equivale a poder enviar campañas en frío**. Consultar con el abogado qué enfoque de contacto es viable.
- **Llamadas comerciales**: la normativa de telecomunicaciones y la LOPDGDD (sistemas de exclusión publicitaria como la Lista Robinson) protegen sobre todo a personas físicas; en líneas de empresa el marco es distinto, pero los autónomos son personas físicas. Validar con el abogado.
- El producto puede ayudar guardando la **base legal y la procedencia** de cada contacto y respetando listas de exclusión.

## 4. Fuentes: condiciones de uso y derechos sobre bases de datos

| Riesgo | Detalle | Cómo lo gestionamos |
|---|---|---|
| **Condiciones de Google Maps Platform** | Sus políticas prohíben precargar, cachear o almacenar contenido de Places salvo excepciones; el `place_id` sí se puede guardar. Hay términos específicos para clientes del EEE | Places como descubrimiento y verificación en vivo; persistir solo `place_id`; datos persistentes desde fuentes que lo permitan. Nada de scrapers de Google Maps de terceros |
| **LinkedIn** | Su acuerdo de usuario prohíbe el scraping y la empresa lo persigue judicialmente | No scraping. Solo URL de la página de empresa y consulta manual |
| **Derecho *sui generis* sobre bases de datos** (Directiva 96/9/CE; en España, Ley de Propiedad Intelectual) | Protege al fabricante de una base de datos frente a la extracción de partes sustanciales, o repetida y sistemática de partes no sustanciales | No replicar directorios. Usarlos como pista puntual y verificar en fuente primaria (web propia, registros) |
| **Condiciones de uso de cada web** | Pueden prohibir la extracción automatizada | Respetar `robots.txt`, límites de velocidad, identificar el *user-agent*; descargar solo páginas necesarias (aviso legal, contacto) |
| **Datos abiertos oficiales** (BOE/BORME, PLACSP, INE, IGN) | Suelen permitir la reutilización con condiciones (citar fuente, no desnaturalizar) | Revisar el aviso de reutilización de cada organismo y citar la fuente |
| **Proveedores comerciales** | Licencias que limitan almacenamiento, reventa o uso | Registrar la licencia de cada proveedor en `fuentes.notas_condiciones` |
| **OpenStreetMap (ODbL)** | Bases derivadas distribuidas públicamente pueden quedar sujetas a compartir-igual | Si se usa, aislar esos datos y consultarlo |

## 5. Si Radar B2B se vende como producto (Fase 5)

Pasar de uso interno a **ceder o dar acceso a datos a terceros** cambia el perfil de riesgo: implica ser responsable del tratamiento de datos que se ceden, más exposición a reclamaciones de titulares de bases de datos y exigencias contractuales frente a clientes. Requiere análisis legal específico antes de lanzar. (Nota: por D-03, esta vía está descartada por ahora.)

## 6. Preguntas para llevar al abogado

1. ¿Es suficiente el interés legítimo (art. 19 LOPDGDD) para incluir autónomos y datos de contacto profesional en una base de prospección propia? ¿Y para cederla a clientes?
2. ¿Cómo cumplimos el deber de informar del art. 14 RGPD a escala?
3. ¿Qué uso podemos dar a los administradores publicados en el BORME?
4. ¿Qué enfoque de contacto comercial (email, teléfono, LinkedIn) es viable con esta base según la LSSI y la normativa de telecomunicaciones?
5. ¿Riesgo del derecho *sui generis* con el uso previsto de directorios?
6. ¿Encaje de los términos de Google Maps Platform para clientes del EEE con nuestro diseño?
7. Cláusulas necesarias en los contratos con clientes si vendemos listados.
