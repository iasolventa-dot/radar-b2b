# Web — Radar B2B

Next.js 16 (App Router) + Tailwind, desplegado en Vercel, conectado a Supabase solo con la clave **publishable** (nunca la secreta — toda la autorización de lectura/escritura la hace RLS en Postgres).

## Qué es esto ahora mismo (D-13)

Esto **no** es todavía la interfaz completa del doc 02 §3 / doc 07 §7 (chat con el agente, tabla+mapa de resultados, exportación) — esa sigue perteneciendo a la Fase 3 del roadmap y depende de que exista el agente y el descubrimiento multi-fuente (Fase 2).

Lo que hay hoy es un **panel mínimo, de uso interno**, para una sola cosa muy concreta: revisar los candidatos que genera `worker/scripts/generar_candidatos_golden.py` (tabla `golden_candidatos`) y promoverlos a entidades verificadas del golden set (tabla `golden_entidades`), en vez de editar `registros_entrada.csv`/`entidades.csv` a mano. Ver `worker/tests/golden/README.md`.

Pantallas:
- `/` — progreso del golden set por categoría (normales, homónimos, franquicias, grupo, disueltas, traslados, autónomos, web-agencia, nombre genérico) frente al objetivo de doc 07 §6.
- `/revision` — cola de candidatos pendientes, filtrable por categoría, con acceso directo a la evidencia del BORME.
- `/revision/[id]` — ficha de un candidato con toda la evidencia extraída (objeto social, tipos de acto, administradores, posibles homónimos/grupo) y el formulario para promoverlo a `golden_entidades` (NIF, estado, caso difícil, fuentes de verificación...) o descartarlo.
- `/entidades` — tabla de solo lectura de lo ya verificado.

Según avancen las fases del roadmap se añaden más pantallas (tabla de `empresas` con filtros cuando haya descubrimiento multi-fuente real, chat del agente en Fase 3) — no se reescribe esto, se amplía.

## Desarrollo local

```powershell
cd web
npm install
Copy-Item .env.example .env.local
# rellena NEXT_PUBLIC_SUPABASE_URL y NEXT_PUBLIC_SUPABASE_ANON_KEY (la publishable) en .env.local
npm run dev
```

Requiere que la migración `supabase/migrations/202609102000_golden_set_revision.sql` esté aplicada y que tu usuario tenga acceso (Supabase Dashboard → Authentication → Users → Invite user, con tu email; y en Authentication → Providers, confirma que "Email" con enlace mágico está activo).

## Despliegue en Vercel

Ver la guía paso a paso que Claude entregó en el chat (comandos de Vercel CLI). En resumen: `vercel link`, `vercel env add` para las dos variables `NEXT_PUBLIC_*`, `vercel --prod` — todo desde `web/`.

## Convenciones

Mismas del resto del repo: comentarios y textos de interfaz en español, `snake_case` en lo que toca a Postgres, componentes y variables en `camelCase`/`PascalCase` como es habitual en TypeScript/React. Sin `service_role` ni ninguna clave secreta en este proyecto — si algún día hace falta una operación que RLS no puede cubrir, se hace en una Route Handler server-side con muchísimo cuidado, nunca en el cliente.
