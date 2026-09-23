# Protocolo y límites

Fecha: 23 de septiembre de 2026. Código del piloto: `ef07a0c`.
La huella completa de código, tareas, dependencias y datos figura en `controls.json`.

- Una foto real: DKNYgirl, con 8 resultados originales de RetargetMe y sus votos.
- Dos instrucciones fijas × dos brazos × tres repeticiones, orden alternado.
- Luna: `gpt-5.6-luna`, razonamiento medium, 4096 tokens de salida por llamada.
- Composición: `jev-1.13.0` elige entre una receta proporcional y ese mismo Luna.
- Umbral JEV: confianza >= 0,90 y ancho único válido. Sin ajuste tras ver resultados.
- Ambos brazos reciben las mismas herramientas y la misma receta. Los archivos
  de referencia y el evaluador se incorporan después de terminar el agente.
- Herramientas: ImageMagick 6.9.11-60 Q16 aarch64; Python 3.11.2; Pillow 9.4.0.
- Harbor 0.20.0, Docker local aarch64. Usuario de herramienta sin privilegios;
  `network_mode: none`, verificado en Docker. El contenedor solo recibió `PATH`.
- Sin reintentos automáticos de Harbor ni de los clientes API. Límite: USD 5,
  600 segundos por agente y 40 llamadas al modelo por tarea.

Los 6 tests locales y los controles oracle/nop prueban el protocolo técnico.
La tarea proporcional exige PNG 512×337 y error absoluto medio por canal <= 3
respecto de un redimensionado independiente con Pillow. La tarea visual exige
PNG 512×673; su aceptación visual sigue pendiente de revisión humana ciega:
persona conservada, proporciones naturales, encuadre útil, ausencia de bordes.

El tiempo del agente incluye JEV, herramientas y API; el tiempo total de Harbor
también incluye contenedor y evaluación. Se cuentan por separado llamadas al
modelo y herramientas. Tokens ausentes quedan desconocidos. El costo se calcula
con tarifas publicadas, incluyendo reservas de llamadas de consumo desconocido.

Antes del piloto se resolvieron incompatibilidades locales del aislamiento y
descarga de paquetes de Docker. El primer intento pago produjo 3 llamadas a Luna
y falló al validar nuestra traza ATIF. Ese intento permanece registrado como
preparación, con su consumo; no se confunde con una falla de calidad del modelo.
Se corrigió la vinculación de observaciones y se volvió a pasar los controles.

Los votos históricos de RetargetMe no califican salidas nuevas. Ningún resultado
de este piloto demuestra aún superioridad visual, generalización a otras fotos,
entrenamiento de especialistas, o éxito en los tamaños publicitarios <=150 kB.
