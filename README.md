# LimpiaColor

Aplicación de escritorio en **Python**, con interfaz en español, para limpiar marcas de agua de imágenes y videos mediante una máscara de varios colores y relleno con los píxeles vecinos. Los archivos se procesan localmente.

## Instalación y ejecución

Requiere Python **3.10 o superior** con Tkinter. En Windows instala Python desde [python.org](https://www.python.org/downloads/windows/) incluyendo Tcl/Tk y el lanzador `py`.

**Windows:** ejecuta `instalar.bat` una vez y luego abre `iniciar.bat`. En esta carpeta ya está preparado el entorno `.venv`.

También puedes usar la terminal:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

En Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

En Debian/Ubuntu, si falta Tkinter, instala `python3-tk` con el gestor de paquetes del sistema. FFmpeg viene incluido en la dependencia `imageio-ffmpeg` para las plataformas compatibles; no requiere una instalación manual en Windows.

## Uso

1. Pulsa **Abrir archivo** para cargar una imagen o un video. **Probar ejemplo** genera una imagen de prueba propia con dos colores ya seleccionados.
2. Usa **Cuentagotas** y haz clic en los colores de la marca en la imagen original. Puedes añadir varios colores, introducirlos manualmente o quitar los que no necesites.
3. Selecciona un color de la lista y ajusta su **tolerancia**. Es una distancia RGB: 0 busca el color exacto; valores mayores incluyen variaciones por sombras o compresión. Confirma los valores escritos con Enter o al salir del campo.
4. Selecciona **Delimitar zona** y arrastra sobre el original para restringir la limpieza. La selección se mantiene en la misma posición en todos los fotogramas. **Quitar zona** vuelve a usar toda la imagen.
5. Elige el método, el radio de vecinos y la expansión. **Ver máscara en rosa** muestra exactamente qué píxeles se van a modificar.
6. En videos, desplaza la barra para revisar otros fotogramas. La máscara se vuelve a calcular en **cada fotograma** a partir de los colores elegidos.
7. Pulsa **Exportar resultado**, elige un archivo diferente del original y espera a que termine. Puedes cancelar; la salida se publica únicamente al completar y verificar el proceso. Si eliges un destino existente, el diálogo del sistema permite confirmar su reemplazo.

`Ctrl+O` abre un archivo. El editor mantiene la interfaz activa durante las vistas previas y exportaciones.

## Métodos de relleno

| Método | Operación |
| --- | --- |
| **Color predominante** | Para cada píxel seleccionado, busca el grupo RGB más frecuente entre sus vecinos válidos y usa el promedio de ese grupo. Agrupa canales en intervalos de 16 para tolerar ruido. Propaga el relleno desde el borde hacia el centro. Es el método predeterminado. |
| **Máximo RGB** | Usa el máximo de cada canal de los vecinos válidos. Puede generar colores más claros; permite interpretar literalmente “valor mayor de los píxeles alrededor”. |
| **Reconstrucción suave** | Usa el algoritmo Telea de OpenCV para reconstruir las zonas a partir del borde. Puede resultar más natural en fondos con gradientes. |

La máscara combina los colores mediante una unión de coincidencias por distancia RGB. **Expandir máscara** cubre bordes suavizados y halos de compresión; comienza con 1–2 px. El radio controla cuántos vecinos se consultan. Los píxeles fuera de la máscara permanecen iguales en el procesamiento; una exportación JPEG o MP4 añade la compresión propia del formato.

## Formatos y límites

- Entrada de imagen: PNG, JPG/JPEG, WebP estático, BMP y TIFF. Se aplica la orientación EXIF. La interfaz muestra RGB; las exportaciones PNG/WebP/TIFF conservan el canal alfa original.
- Entrada de video: MP4, MOV, AVI, MKV, WebM y M4V, siempre que el códec pueda decodificarse en OpenCV.
- Exportación desde la interfaz: PNG, JPG o WebP para imagen; **MP4 H.264** para video. Si se conserva audio, las pistas de audio se codifican como AAC.
- La exportación procesa un fotograma a la vez. Los tamaños impares se completan con hasta una fila/columna de borde para compatibilidad H.264; no se recorta la imagen.
- La salida de video usa FPS constantes. Fuentes de FPS variables pueden perder sincronización con el audio. No se conservan subtítulos, HDR, profundidad de color ni todas las propiedades del contenedor original.
- Una zona fija ayuda a proteger otros objetos del mismo color. No hay seguimiento automático de objetos: si la marca se mueve fuera de la zona, amplíala o quítala.
- El relleno estima el fondo oculto. No recupera información original ni garantiza una eliminación perfecta en marcas transparentes, fondos complejos o regiones grandes. En video puede aparecer parpadeo al procesar fotogramas de forma independiente.
- Para marcas translúcidas, toma varias muestras en distintos fondos/fotogramas. Si la máscara cubre toda la imagen, el programa pide reducir la tolerancia o delimitar una zona.

## Desarrollo y verificación

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe tests/smoke_gui.py
```

La prueba de interfaz requiere un escritorio disponible. Las pruebas de procesamiento cubren selección multicolor, tolerancia, zona y expansión, moda local, máximo RGB, Telea, píxeles fuera de la máscara, orientación, transparencia, rutas Unicode, video con marca móvil, audio, dimensiones impares y cancelación con conservación del destino existente.

GitHub Actions ejecuta las pruebas de procesamiento en Windows y Linux, con Python 3.10 y 3.12.

```text
app.py                 Entrada de la aplicación
limpiacolor/core.py     Detección de colores y relleno
limpiacolor/media.py    Lectura y exportación de imágenes/videos
limpiacolor/gui.py      Interfaz Tkinter y trabajos en segundo plano
tests/                 Pruebas unitarias, integración y arranque de interfaz
```

Referencia del método suave: [OpenCV — Inpainting](https://docs.opencv.org/4.x/d7/d8b/group__photo__inpaint.html).
