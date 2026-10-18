"""Prueba manual/automatizada con escritorio disponible: python tests/smoke_gui.py."""

import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from limpiacolor.gui import Application

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
finally:
    app.destroy()
