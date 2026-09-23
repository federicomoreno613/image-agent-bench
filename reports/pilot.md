# Piloto: Luna vs JEV + Luna

Estado: mediciones reales; calidad visual pendiente de revisión humana.

| Tarea | Sistema | OK técnico | Tiempo medio (s) | Llamadas al modelo | Herramientas | Costo estimado medio (USD) |
|---|---|---:|---:|---:|---:|---:|
| technical | luna | 3/3 | 5.653 | 2.7 | 1.7 | 0.000411–0.000411 |
| technical | jev_luna | 3/3 | 1.736 | 1.0 | 1.0 | 0.000018–0.000018 |
| visual | luna | 3/3 | 12.206 | 4.0 | 3.0 | 0.000885–0.000948 |
| visual | jev_luna | 3/3 | 13.709 | 5.0 | 3.0 | 0.000992–0.001078 |

La tarea técnica es un control de exportación proporcional. La visual usa las dimensiones originales de RetargetMe.
Los votos del estudio valoran sus ocho resultados, no las salidas nuevas. No se afirma superioridad visual ni generalización.
Las llamadas y herramientas se cuentan por separado. El tiempo mostrado cubre el agente completo, incluida la clasificación; el JSON también conserva el tiempo total de Harbor.
La calidad visual pendiente impide calcular costo por éxito visual. Las estimaciones de costo incluyen llamadas fallidas cuando su consumo es conocido; si no, quedan desconocidas.

[Datos y estudio original](https://people.csail.mit.edu/mrub/retargetme/download.html)
