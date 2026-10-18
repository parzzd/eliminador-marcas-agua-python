"""Prueba manual/automatizada con escritorio disponible: python tests/smoke_gui.py."""

import sys
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limpiacolor.gui import Application
from limpiacolor.core import ColorTarget
from limpiacolor.media import export_image, read_image


def pump(app, seconds=0.1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.update()
        time.sleep(0.005)


def wait_preview(app):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        app.update()
        if app.preview_valid and not app.preview_busy:
            return
        time.sleep(0.01)
    raise AssertionError(app.status.get())


def screen_point(canvas, x, y):
    return tuple(round(value) for value in canvas.viewport.canvas_point(x + 0.5, y + 0.5))

app = Application()
try:
    app.demo()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        app.update()
        if app.preview_valid and not app.preview_busy:
            break
        time.sleep(0.02)
    assert app.preview_valid, app.status.get()
    assert len(app.colors) == 2
    assert app.preview_mask is not None and app.preview_mask.any()
    assert str(app.export_button["state"]) == "normal"
    assert app.cancel_button.winfo_rooty() + app.cancel_button.winfo_height() < app.sidebar.winfo_rooty() + app.sidebar.winfo_height()
    print("GUI OK:", app.file_status.get(), "|", app.mask_status.get())
    app.method.set("Máximo RGB")
    app.request_preview()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        app.update()
        if app.preview_valid and not app.preview_busy:
            break
        time.sleep(0.02)
    assert app.preview_valid
    print("Cambio de método y vista previa: OK")

    # Pruebas de entrada real de Tk: rueda, botones de herramienta y arrastre.
    with tempfile.TemporaryDirectory() as folder:
        source, output = Path(folder) / "source.png", Path(folder) / "output.png"
        image = np.full((400, 600, 3), (32, 64, 96), np.uint8)
        image[50:75, 50:85] = 255
        image[280:310, 450:490] = 255
        Image.fromarray(image).save(source)
        app.load(source)
        app.colors = [ColorTarget((255, 255, 255), 0)]
        app._refresh_colors(0)
        app.request_preview()
        wait_preview(app)

        canvas = app.original
        center = (canvas.winfo_width() // 2, canvas.winfo_height() // 2)
        canvas.event_generate("<MouseWheel>", x=center[0], y=center[1], delta=120)
        assert canvas.viewport.zoom == 1.0, "La rueda debe animar, no saltar inmediatamente"
        assert abs(canvas.zoom_target - 1.08) < 1e-8
        deadline = time.monotonic() + 2
        while canvas.viewport.zoom == 1 and time.monotonic() < deadline:
            pump(app, 0.01)
        assert 1 < canvas.viewport.zoom < canvas.zoom_target, "Debe haber pasos intermedios de zoom"
        pump(app, 0.7)
        assert abs(canvas.viewport.zoom - 1.08) < 1e-6
        assert abs(app.result.viewport.zoom - canvas.viewport.zoom) < 1e-6
        canvas.event_generate("<MouseWheel>", x=center[0], y=center[1], delta=15)
        assert abs(canvas.zoom_target - 1.08 ** 1.125) < 1e-8, "Conservar desplazamientos pequeños de rueda"
        pump(app, 0.7)

        # La rueda debe funcionar sobre la imagen aunque otro control tenga
        # el foco del teclado (ruta habitual de MouseWheel en Windows).
        previous_target = canvas.zoom_target
        # Solo simula qué widget hay bajo el puntero: el escritorio de pruebas
        # puede estar oculto por otra ventana o ejecutarse sin pantalla física.
        with patch.object(app, "winfo_containing", return_value=canvas):
            app.event_generate("<MouseWheel>", delta=120,
                rootx=canvas.winfo_rootx() + center[0], rooty=canvas.winfo_rooty() + center[1])
        assert abs(canvas.zoom_target - previous_target * 1.08) < 1e-8
        pump(app, 0.7)

        # Precisión del cuentagotas tras ampliar y desplazar; la vista previa
        # siguiente conserva la posición y el nivel de zoom de ambas imágenes.
        canvas.viewport.zoom_at(4, *center)
        canvas.viewport.pan(-45, -25)
        canvas.redraw()
        canvas._notify_view()
        app.colors.clear()
        app._refresh_colors()
        app.pick_button.invoke()
        pixel = screen_point(canvas, 320, 230)
        expected = image[canvas.image_point(*pixel)[1], canvas.image_point(*pixel)[0]]
        canvas.event_generate("<ButtonPress-1>", x=pixel[0], y=pixel[1])
        canvas.event_generate("<ButtonRelease-1>", x=pixel[0], y=pixel[1])
        assert app.colors[0].rgb == tuple(expected)
        wait_preview(app)
        assert canvas.viewport.zoom == 4
        assert app.result.viewport.zoom == 4
        app.show_mask.set(True)
        app._draw_result()
        assert app.result.viewport.zoom == 4
        app.show_mask.set(False)
        app._draw_result()
        canvas.fit()
        assert app.result.viewport.zoom == 1
        print("Zoom suave, rueda de precisión, vistas sincronizadas y cuentagotas ampliado: OK")

        # Selección inversa desde RESULTADO. Una respuesta atrasada de la vista
        # previa no debe borrar el rectángulo en curso ni habilitar exportación.
        app.colors = [ColorTarget((255, 255, 255), 0)]
        app._refresh_colors(0)
        app.request_preview()
        wait_preview(app)
        previous_generation = app.generation
        app.roi_button.invoke()
        assert app.mode.get() == "roi"
        canvas = app.result
        start, end = screen_point(canvas, 100, 95), screen_point(canvas, 35, 35)
        start_pixel = canvas.image_point(*start, clamp=True)
        end_pixel = canvas.image_point(*end, clamp=True)
        expected_roi = (end_pixel[0], end_pixel[1], start_pixel[0] + 1, start_pixel[1] + 1)
        canvas.event_generate("<ButtonPress-1>", x=start[0], y=start[1])
        canvas.event_generate("<B1-Motion>", x=end[0], y=end[1])
        app.messages.put(("preview", previous_generation, image, image.copy(), np.zeros(image.shape[:2], np.uint8), None))
        pump(app, 0.15)
        assert app.roi == expected_roi
        assert app.original.roi == app.result.roi == expected_roi
        assert app.original.find_withtag("selection")
        assert app.result.find_withtag("selection")
        assert not app.preview_valid
        canvas.event_generate("<ButtonRelease-1>", x=end[0], y=end[1])
        wait_preview(app)
        assert app.roi == expected_roi
        assert app.preview_mask[60, 60] == 255
        assert app.preview_mask[290, 460] == 0
        export_image(source, output, app.settings())
        result, _ = read_image(output)
        np.testing.assert_array_equal(result[60, 60], [32, 64, 96])
        np.testing.assert_array_equal(result[290, 460], [255, 255, 255])
        print("Delimitar desde resultado, arrastre inverso y exportación limitada a la zona: OK")

        # El margen vacío puede iniciar una selección, y la misma conversión
        # se mantiene después de hacer zoom o soltar fuera del lienzo.
        app._clear_roi()
        wait_preview(app)
        canvas = app.original
        assert canvas.offset[1] > 0, "La prueba requiere margen vertical"
        start = (0, 0)
        end = screen_point(canvas, 100, 100)
        canvas.event_generate("<ButtonPress-1>", x=0, y=0)
        canvas.event_generate("<B1-Motion>", x=end[0], y=end[1])
        canvas.event_generate("<ButtonRelease-1>", x=end[0], y=end[1])
        wait_preview(app)
        assert app.roi[:2] == (0, 0)
        canvas.viewport.zoom_at(4, canvas.winfo_width() / 2, canvas.winfo_height() / 2)
        canvas.redraw()
        canvas._notify_view()
        start, end = screen_point(canvas, 260, 180), screen_point(canvas, 330, 240)
        first, last = canvas.image_point(*start), canvas.image_point(*end)
        canvas.event_generate("<ButtonPress-1>", x=start[0], y=start[1])
        canvas.event_generate("<B1-Motion>", x=end[0], y=end[1])
        canvas.event_generate("<ButtonRelease-1>", x=end[0], y=end[1])
        wait_preview(app)
        assert app.roi == (first[0], first[1], last[0] + 1, last[1] + 1)
        assert canvas.viewport.zoom == app.result.viewport.zoom == 4
        before_pan = canvas.viewport.center_x
        canvas.event_generate("<ButtonPress-3>", x=200, y=200)
        canvas.event_generate("<B3-Motion>", x=220, y=200)
        canvas.event_generate("<ButtonRelease-3>", x=220, y=200)
        assert canvas.viewport.center_x < before_pan
        assert canvas.viewport.center_x == app.result.viewport.center_x
        app._clear_roi()
        wait_preview(app)
        assert app.roi is None
        assert not canvas.find_withtag("selection")
        print("Selección desde margen, coordenadas con zoom y desplazamiento: OK")
finally:
    app.cancel_preview.set()
    app.original.stop_zoom()
    app.result.stop_zoom()
    app.destroy()
