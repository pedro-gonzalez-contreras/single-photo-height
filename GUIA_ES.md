# Guía de uso — Single Photo Height

[Proyecto](README.md) · [English guide](GUIDE_EN.md)

La demo necesita una foto de cuerpo entero y un tablero de ajedrez de tamaño conocido. Puede proponer automáticamente la coronilla y la base, o permitir marcarlas a mano. La persona y la referencia deben estar en el mismo plano. La presencia del tablero por sí sola no asegura una medida válida.

## Instalación en Windows

Con Python 3.11 y Tcl/Tk disponibles, desde la carpeta del proyecto:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe demo.py examples/frontal.png --manual
```

La imagen de ejemplo es completamente sintética. Su segmento cabeza–base mide 180 cm en el modelo que la genera.

## Medir sin los dos clics

Instala el componente opcional y descarga el modelo una vez:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-auto.txt
.venv/Scripts/python.exe download_model.py
.venv/Scripts/python.exe demo.py private_data/persona.jpg
```

Al abrir la foto, la demo propone el punto verde de la coronilla y el rojo de la base. Primero localiza a la persona con MediaPipe; después busca la coronilla en la silueta y una línea de unión suelo–pared cerca de los talones. La línea azul debe estar apoyada en segmentos visibles a ambos lados de la persona. No usa como base la punta del zapato ni directamente el talón estimado por el modelo.

La medida aparece sin marcar puntos. Revisa la superposición: **Correct manually** permite corregirla con dos clics y **Detect automatically** repite la detección. Si no hay evidencia suficiente, pide anotación manual. Sin interfaz:

```powershell
.venv/Scripts/python.exe measure.py private_data/persona.jpg --auto --output outputs/automatic.json
```

La inferencia se ejecuta localmente. El programa solo descarga el modelo cuando ejecutas `download_model.py`. Las fotos, salidas y pesos quedan excluidos de Git. El ejemplo dibujado no sirve para evaluar un detector de personas reales; úsalo con `--manual`.

Es un modo experimental para una sola persona erguida, con cabeza y talones visibles y una unión suelo–pared reconocible. Pelo, sombreros, rodapiés y sombras pueden alterar los puntos. El programa recomienda revisar incluso cuando consigue calcular; no garantiza precisión ni reconoce semánticamente el plano del patrón.

## Tu propia foto

También puedes configurar la referencia desde la ventana, en **Chessboard reference**:

1. En **Pattern**, elige un patrón de la lista o escribe otro, por ejemplo `9 x 6`. Son columnas × filas de cuadrados, no esquinas interiores.
2. En **Square side (mm)**, escribe el lado real del cuadrado impreso; admite `27.5` y `27,5`.
3. Pulsa **Apply pattern** o Intro. La línea inferior indica qué configuración está aplicada.

Cambiar el tamaño conserva los puntos y recalcula la altura. Cambiar las dimensiones vuelve a detectar el tablero; si falla, la foto permanece abierta para corregir la configuración. No se permite guardar con cambios pendientes ni con un tablero sin detectar. El tipo de referencia sigue siendo un tablero de ajedrez.

```powershell
.venv/Scripts/python.exe demo.py private_data/persona.jpg --squares 9 6 --square-mm 27 --manual
```

`--squares 9 6` significa 9 × 6 cuadrados, es decir, 8 × 5 esquinas interiores. `--square-mm` es el lado físico de un cuadrado impreso. Cambia esos valores para otro tablero; no uses sin comprobar la cifra escrita en el diseño si se imprimió ampliado.

1. Abre la imagen con **Open photo**. La demo debe encontrar el tablero completo.
2. Marca la parte más alta de la cabeza: punto verde.
3. Marca la base a la altura del talón, en el plano del patrón: punto rojo. En el montaje contra una puerta, usa la unión suelo–puerta bajo la persona; no la punta del zapato.
4. Se mostrarán la escala simple y la homografía. **Correct manually** permite repetir la selección.
5. **Save result** guarda el JSON y la imagen anotada en `outputs/`.

La escala simple suele ser una mejor base para una captura aproximadamente frontal. La homografía puede compensar perspectiva, pero es sensible si el tablero ocupa pocos píxeles. No se estima calibración intrínseca ni distorsión de lente con esta foto.

## Demo sin interfaz

```powershell
.venv/Scripts/python.exe measure.py examples/frontal.png --head 1100 230 --base 1100 2030 --output outputs/frontal.json
```

Este comando usa puntos conocidos de la escena sintética y funciona sin Tkinter. Para otra imagen, cambia los puntos. Puedes elegir `--method simple_scale`, `--method homography` o `--method both`.

## Resultados reales de desarrollo

En 11 fotos únicas, con alturas de referencia de 177 y 181 cm corregidas por el autor, los errores absolutos medios fueron 4,63 cm para escala simple y 6,28 cm para homografía. No es una validación independiente ni una promesa de precisión. Las fotos privadas no se publican.

El modo automático produjo puntos en 10 de las 11 fotos únicas y rechazó una por falta de apoyo claro para la línea del suelo. Comparando las mismas diez fotos, el error medio pasó de 4,76 a 5,91 cm en escala simple, y de 6,32 a 7,56 cm en homografía. Automatizar ahorra clics, pero todavía añade error. Estas fotos también se usaron durante el desarrollo de las heurísticas.

El cálculo supone coplanaridad, escala conocida y distorsión de lente despreciable. La validación en otras personas, cámaras y ángulos queda pendiente.

## Entorno y pruebas

En macOS y Linux, sustituye `.venv/Scripts/python.exe` por `.venv/bin/python`. La interfaz necesita Tkinter con Tcl/Tk; la versión por consola funciona sin ellos. Usa un entorno limpio y evita instalar varias distribuciones de OpenCV simultáneamente, porque comparten el módulo `cv2`.

Para ejecutar las pruebas y regenerar los ejemplos:

```powershell
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe generate_examples.py
```

Las pruebas de la interfaz se omiten cuando no hay Tkinter o pantalla disponible. La prueba de inferencia real se omite si falta MediaPipe o el modelo; ninguna prueba descarga el modelo automáticamente.

## Dependencias, licencia y privacidad

El código y los ejemplos sintéticos originales se distribuyen con [licencia MIT](LICENSE). OpenCV, NumPy, Pillow y MediaPipe mantienen sus propias licencias. El modelo preentrenado de MediaPipe es un recurso externo, se descarga por separado y no está cubierto por la licencia MIT de este proyecto. La URL y el SHA-256 del modelo están fijados en `download_model.py`; consulta la [documentación oficial](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker) y el [repositorio de MediaPipe](https://github.com/google-ai-edge/mediapipe).

Las imágenes se procesan en el ordenador. Guarda tus fotografías en `private_data/` y las medidas en `outputs/`; ambas carpetas están excluidas de Git, al igual que los pesos del modelo. Solo se incluyen las dos ilustraciones sintéticas de ejemplo.
