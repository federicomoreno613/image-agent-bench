# Image Agent Bench

¿Puede un clasificador pequeño reconocer un procedimiento conocido y ahorrar
llamadas a un agente generalista, conservando el resultado?

Piloto con **Harbor 0.20.0**, **GPT-5.6 Luna** y **JEV vía LangChain**.
Luna dispone de las mismas herramientas y procedimientos en ambos brazos.
JEV clasifica texto; no observa imágenes ni genera comandos arbitrarios.

## Imagen y referencias

Elegimos **DKNYgirl** de [RetargetMe](https://people.csail.mit.edu/mrub/retargetme/):
una persona delante de taxis. El objetivo visual es pasar de 1024×673 a
512×673 conservando a la persona sin deformarla. RetargetMe incluye resultados
de ocho métodos y preferencias humanas; no existe una única respuesta perfecta.
Los votos originales no califican automáticamente una nueva salida.

Los archivos originales y referencias se obtienen del archivo oficial de 2011,
sin alterar sus dimensiones ni incluir referencias dentro del entorno del agente.
El código es abierto; las imágenes conservan sus créditos y condiciones originales.

## Alcance del piloto

1. **Procedimiento conocido:** reducir el ancho a 512 manteniendo la proporción
   y exportar un PNG. Es un control técnico, no una tarea oficial de RetargetMe.
2. **Decisión visual:** reducir solamente el ancho a 512, mantener alto 673 y
   preservar a la persona. Sin márgenes ni imágenes generadas. Se compara contra
   las referencias originales de RetargetMe.

Dos sistemas × dos tareas × tres repeticiones, secuenciales y en orden alternado.
Tope de API: USD 5 incluyendo preparación; 10 minutos y 40 llamadas por tarea.
Las referencias y los votos permanecen exclusivamente en el evaluador.
La calidad visual exige revisión humana ciega; éxito técnico no significa calidad.

## Primer resultado medido

12/12 salidas pasaron la verificación técnica. Una foto y tres repeticiones por
combinación; la revisión humana de calidad visual sigue pendiente.

Promedios por ejecución. Tiempo = agente completo; llamadas y herramientas se cuentan por separado.

| Tarea | Sistema | Tokens entrada / salida | Llamadas modelo | Herramientas | Tiempo (s) | USD estimados |
|---|---|---:|---:|---:|---:|---:|
| technical | luna | 1358.3 / 116.3 | 2.67 | 1.67 | 5.65 | 0.0004113 |
| technical | jev_luna | 436.0 / 38.0 | 1.00 | 1.00 | 1.74 | 0.0000183 |
| visual | luna | 5475.3 / 396.3 | 4.00 | 3.00 | 12.21 | 0.0008851–0.0009484 |
| visual | jev_luna | 5990.0 / 436.0 | 5.00 | 3.00 | 13.71 | 0.0009918–0.0010778 |

En el resize conocido, JEV + receta usó **95,5% menos costo estimado** y **69,3% menos
tiempo de agente**. En el caso visual, JEV derivó a Luna las tres veces: añadió una
llamada y el conjunto fue algo más lento y caro. Esto apoya reconocer procedimientos
conocidos; no prueba que encadenar modelos siempre sea mejor.

Con arranque del contenedor y evaluación, los tiempos medios de Harbor fueron:
technical / luna: 22.06 s; technical / jev_luna: 18.22 s; visual / luna: 29.07 s; visual / jev_luna: 30.67 s.

Costo de API del trabajo experimental completo: **USD 0,00742694–0,00787494**,
incluyendo un intento previo fallido al guardar la traza. Son estimaciones por
tokens, no facturas; no incluyen desarrollo, infraestructura ni esta conversación.

[Resultados por intento](reports/pilot.json) · [Protocolo](reports/protocol.md) ·
[Trazas ATIF y llamadas](reports/traces.jsonl) · [Controles](reports/controls.json) ·
[Conciliación de consumo](reports/accounting-audit.json)

## Ejecutar

Requiere Docker funcionando y [uv](https://docs.astral.sh/uv/). El primer paso
descarga el archivo oficial (~595 MB); selecciona una foto y ocho referencias.

```sh
uv sync --locked
uv run python prepare.py
uv run python -m unittest -v test_bench
uv run python run.py controls
uv run python run.py pilot --env-file /ruta/privada/.env
uv run python run.py report
```

El archivo privado debe definir `OPENAI_API_KEY` y `TYPESAFE_API_KEY`; también
se aceptan `open_ai_api_key` y `jev_api_key`. Las claves se cargan en memoria
del controlador y no se copian al contenedor ni a las trazas. No publicar `.env`.

Los controles exigen que la solución conocida pase y que no hacer nada falle,
para ambas tareas. Un cambio de código o datos invalida ese control.
Docker ejecuta las herramientas sin red y con usuario sin privilegios;
el evaluador comprueba que no haya rutas IPv4 y que una conexión externa devuelva
«red inalcanzable» (el kernel puede mostrar interfaces de túnel inactivas).
La instalación de herramientas ocurre al construir la imagen, antes del agente.

`reports/pilot.md` resume resultados; `reports/pilot.json` conserva cada medición.
`local-results/comparison.html` permite revisar salidas con los brazos ocultos.
Las trazas ATIF, llamadas y archivos completos quedan en `local-results/jobs/`.
`budget.json` conserva gasto estimado y reservas de solicitudes inciertas entre
ejecuciones; no borrarlo para repetir pruebas bajo el mismo presupuesto.

## Qué prueba y qué queda pendiente

JEV selecciona una receta conocida y valida sus parámetros; ante una petición
visual o desconocida usa exactamente el mismo Luna del otro brazo. La función
`select_route` concentra la integración JEV: otro clasificador puede reemplazarla
manteniendo su contrato, pero habría que volver a medir precisión y latencia.
No hay un modelo entrenado para ImageMagick ni una colección de especialistas.

Es un piloto de una foto, dos instrucciones y tres repeticiones por combinación;
no prueba generalización. Usa terminal e inspección de imágenes, no una GUI.
Los formatos publicitarios originales (8 dimensiones únicas × JPG/JPEG/GIF/PNG,
incluidos 300×600, 320×50 y 320×250, hasta 150 kB) son una siguiente evaluación;
este piloto conserva las dimensiones del estudio y admite PNG hasta 10 MB.

Tarifas verificadas el 23/09/2026: [Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
y [JEV](https://docs.typesafe.ai/models). Se informan estimaciones por tokens,
con intervalo si el proveedor no distingue escrituras de caché; no facturas.
Un consumo ausente queda desconocido y conserva su reserva presupuestaria.

## Referencia

Michael Rubinstein, Diego Gutierrez, Olga Sorkine y Ariel Shamir.
*A Comparative Study of Image Retargeting*. ACM Transactions on Graphics 29(6),
SIGGRAPH Asia 2010. [Datos, resultados y votos](https://people.csail.mit.edu/mrub/retargetme/download.html).
