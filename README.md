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
el evaluador comprueba que solo exista la interfaz de loopback.
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
