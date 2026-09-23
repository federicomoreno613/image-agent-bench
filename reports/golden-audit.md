# Evidencia: qué corrió y qué consiguió

**Veredicto: piloto técnico ejecutado; objetivo publicitario completo pendiente.**
No se considera 12/12 archivos PNG válidos como 12/12 creatividades aceptadas.

## Evidencia de ejecución

- `pilot.json`: 12 ejecuciones de agentes, 2 tareas × 2 brazos × 3 repeticiones.
- `traces.jsonl`: llamadas, respuestas de herramientas, tokens y costos; también
  conserva el intento de preparación que falló al guardar su traza.
- `golden-audit.json`: auditoría de los 12 resultados nativos de Harbor, fechas,
  UUID, hashes de resultados e imágenes, y conciliación de tokens/costo con las
  trazas ya publicadas. Incluye una segunda ejecución de Harbor con `nop` que
  verifica todos los archivos guardados. No se reejecutaron los modelos.
- `image-manifest.json`: origen y hash de cada imagen que se ve en el README.
- `provider-usage-check.json`: el CSV diario coincide con las seis llamadas JEV;
  no contiene precios y no demuestra los cargos de OpenAI.

El benchmark original exigía PNG 512×337 o 512×673, con límite de 10 MB. El
verificador visual anterior comprobaba estructura y tamaño, no calidad ni
similitud con un golden. Ahora la comparación está efectivamente ejecutada.

## Comparación automatizada completa

Se preservaron los nueve archivos congelados: original + ocho referencias.
Cada una de las seis salidas visuales se comparó con las ocho referencias:
**48 pares**, sin modificar, alinear ni redimensionar ninguna imagen.

| Sistema | Repetición | Recorte real en X | Diferencia con CR | Área del recorte CR conservada | Igualdad con algún golden |
|---|---:|---|---:|---:|---|
| Luna | 1 | 128–640 | −8 px | 98,44% | No |
| Luna | 2 | 150–662 | +14 px | 97,27% | No |
| Luna | 3 | 160–672 | +24 px | 95,31% | No |
| JEV → Luna | 1 | 128–640 | −8 px | 98,44% | No |
| JEV → Luna | 2 | 145–657 | +9 px | 98,24% | No |
| JEV → Luna | 3 | 150–662 | +14 px | 97,27% | No |

La referencia CR recorta X=136–648; todas tienen alto 673. La comprobación de
recorte verifica **todos los píxeles** contra el original: 6/6 son recortes
exactos, sin escala, deformación ni generación. El porcentaje de área conservada
describe solapamiento de rectángulos, **no porcentaje de calidad** ni de persona
conservada. MAE, RMSE y PSNR completos están en el JSON; PSNR nulo con MSE cero
representa distancia RGB nula, no un score omitido.

Los controles automáticos demuestran que una referencia consigo misma coincide,
una referencia distinta no se confunde con CR, las dimensiones incorrectas se
rechazan, y una alteración del hash del dataset detiene la comparación.

## Lo que sigue sin estar cumplido

- JPG/JPEG/GIF/PNG en las ocho dimensiones publicitarias: no ejecutado.
- Límite 150.000 bytes: ninguna de las 12 salidas actuales lo cumple.
- Calidad visual aceptada: pendiente. Igualdad con golden es verificable al
  100%, pero no equivale a la única solución correcta para un encuadre libre.
- Comparación con GUI/computer use, modelos especialistas y nuevas fotos:
  fuera de este piloto.

No se retocaron resultados ni se cambió retroactivamente el criterio del piloto.
La condición «igual al golden» se informa como una comprobación posterior, no
como una instrucción que los agentes hubieran recibido originalmente.

Fuentes: [RetargetMe y estudio](https://people.csail.mit.edu/mrub/retargetme/),
[formato de datos y votos](https://people.csail.mit.edu/mrub/retargetme/download.html),
[verificadores Harbor](https://docs.harborframework.com/core-concepts/tasks/verifier).

## Repetir la comprobación

```sh
uv run python -m unittest -v test_bench audit.test_golden
uv run python audit/golden.py run
```

Se necesitan los archivos locales de las ejecuciones originales. El JSON indica
el comando exacto, UUID y ubicación del resultado nativo del replay. No se cargan
claves API, no se ejecuta ningún LLM y el registro de gasto permanece idéntico.
