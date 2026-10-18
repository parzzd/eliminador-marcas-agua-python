"""Interfaz Tkinter en español; los trabajos pesados se ejecutan fuera del hilo UI."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from .core import ColorTarget, ProcessingCancelled, Settings, mask_overlay, process_frame
from .media import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, export_image, export_video, read_image, read_video_frame, video_info

BG, PANEL, FIELD = "#10151E", "#19212D", "#222D3C"
TEXT, MUTED, ACCENT = "#EAF0F8", "#9BAABE", "#60E0BC"
METHODS = {"Color predominante": "dominant", "Máximo RGB": "maximum", "Reconstrucción suave": "telea"}


class ImageCanvas(tk.Canvas):
    def __init__(self, parent: tk.Widget, **kwargs: object) -> None:
        super().__init__(parent, bg="#0B1018", highlightthickness=0, **kwargs)
        self.array: np.ndarray | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.roi: tuple[int, int, int, int] | None = None
        self.scale_factor = 1.0
        self.offset = (0, 0)
        self.bind("<Configure>", lambda _event: self.redraw())

    def show(self, array: np.ndarray | None, roi: tuple[int, int, int, int] | None = None) -> None:
        self.array, self.roi = array, roi
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = max(1, self.winfo_width()), max(1, self.winfo_height())
        if self.array is None:
            self.create_text(width // 2, height // 2 - 18, text="+", font=("Segoe UI", 34), fill=ACCENT)
            self.create_text(width // 2, height // 2 + 27, text="Abre una imagen o un video", font=("Segoe UI", 12), fill=MUTED)
            return
        h, w = self.array.shape[:2]
        self.scale_factor = min(width / w, height / h)
        size = (max(1, int(w * self.scale_factor)), max(1, int(h * self.scale_factor)))
        left, top = (width - size[0]) // 2, (height - size[1]) // 2
        self.offset = (left, top)
        self.photo = ImageTk.PhotoImage(Image.fromarray(self.array).resize(size, Image.Resampling.LANCZOS))
        self.create_image(left, top, image=self.photo, anchor="nw")
        if self.roi:
            x0, y0, x1, y1 = self.roi
            self.create_rectangle(left + x0 * self.scale_factor, top + y0 * self.scale_factor,
                                  left + x1 * self.scale_factor, top + y1 * self.scale_factor,
                                  outline=ACCENT, width=2, dash=(6, 3))

    def image_point(self, x: int, y: int, clamp: bool = False) -> tuple[int, int] | None:
        if self.array is None:
            return None
        height, width = self.array.shape[:2]
        px = int((x - self.offset[0]) / self.scale_factor)
        py = int((y - self.offset[1]) / self.scale_factor)
        if clamp:
            return max(0, min(width - 1, px)), max(0, min(height - 1, py))
        # Verifica coordenadas flotantes: int(-0.5) también da 0.
        if x < self.offset[0] or y < self.offset[1] or not (0 <= px < width and 0 <= py < height):
            return None
        return px, py


class Application(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LimpiaColor · Imágenes y videos")
        self.geometry("1360x880")
        self.minsize(1100, 780)
        self.configure(bg=BG)
        self.source: Path | None = None
        self.source_image: np.ndarray | None = None
        self.is_video = False
        self.frame_count, self.fps, self.frame_index = 1, 1.0, 0
        self.colors: list[ColorTarget] = []
        self.roi: tuple[int, int, int, int] | None = None
        self.drag_start: tuple[int, int] | None = None
        self.preview_result: np.ndarray | None = None
        self.preview_mask: np.ndarray | None = None
        self.messages: queue.Queue = queue.Queue()
        self.cancel_export = threading.Event()
        self.cancel_preview = threading.Event()
        self.exporting = False
        self.preview_busy = False
        self.preview_valid = False
        self.generation = 0
        self.preview_timer: str | None = None
        self.closing = False
        self.mode = tk.StringVar(value="pick")
        self.method = tk.StringVar(value="Color predominante")
        self.tolerance = tk.IntVar(value=36)
        self.radius = tk.IntVar(value=3)
        self.expansion = tk.IntVar(value=1)
        self.show_mask = tk.BooleanVar(value=False)
        self.audio = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Abre un archivo o prueba el ejemplo para empezar.")
        self.mask_status = tk.StringVar(value="Sin máscara")
        self.file_status = tk.StringVar(value="Ningún archivo abierto")
        self.position = tk.StringVar(value="IMAGEN FIJA")
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Control-o>", lambda _event: self.open_file())
        self.after(80, self._poll)

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=PANEL, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=PANEL)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"), background=BG)
        style.configure("Section.TLabel", font=("Segoe UI", 10, "bold"), foreground=ACCENT)
        style.configure("TButton", background=FIELD, foreground=TEXT, padding=(12, 9), borderwidth=0)
        style.map("TButton", background=[("active", "#34465B"), ("disabled", "#1D2734")], foreground=[("disabled", "#617083")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#10251F", font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#8CECCF"), ("disabled", "#29483E")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT, padding=4)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("TRadiobutton", background=BG, foreground=TEXT, padding=6)
        style.map("TRadiobutton", background=[("active", FIELD)])
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=ACCENT, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)])
        style.configure("TSpinbox", fieldbackground=FIELD, background=FIELD, foreground=TEXT, arrowcolor=ACCENT, padding=5)
        style.configure("Treeview", background=FIELD, fieldbackground=FIELD, foreground=TEXT, rowheight=30, borderwidth=0)
        style.map("Treeview", background=[("selected", "#36564F")], foreground=[("selected", TEXT)])
        style.configure("Treeview.Heading", background=PANEL, foreground=MUTED, relief="flat")
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=FIELD, borderwidth=0)
        style.configure("Horizontal.TScale", background=BG, troughcolor=FIELD)

    def _build(self) -> None:
        header = ttk.Frame(self, padding=(24, 18, 24, 12))
        header.pack(fill="x")
        ttk.Label(header, text="LimpiaColor", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="MÁSCARAS MULTICOLOR  /  RELLENO LOCAL", foreground=MUTED, background=BG,
                  font=("Segoe UI", 9)).pack(side="left", padx=22, pady=(9, 0))
        self.open_button = ttk.Button(header, text="Abrir archivo", command=self.open_file, style="Accent.TButton")
        self.open_button.pack(side="right")
        self.demo_button = ttk.Button(header, text="Probar ejemplo", command=self.demo)
        self.demo_button.pack(side="right", padx=10)
        body = ttk.Frame(self, padding=(24, 0, 24, 8))
        body.pack(fill="both", expand=True)
        sidebar = ttk.Frame(body, style="Panel.TFrame", padding=18, width=292)
        sidebar.pack(side="left", fill="y", padx=(0, 18))
        sidebar.pack_propagate(False)
        self.sidebar = sidebar
        ttk.Label(sidebar, text="01  COLORES A EXTRAER", style="Section.TLabel").pack(anchor="w")
        ttk.Label(sidebar, text="Haz clic en el original para añadir\nvarios colores con el cuentagotas.",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(8, 10))
        self.color_list = ttk.Treeview(sidebar, columns=("color", "tolerance"), show="headings", height=4, selectmode="browse")
        self.color_list.heading("color", text="COLOR RGB")
        self.color_list.heading("tolerance", text="TOL.")
        self.color_list.column("color", width=150, stretch=True)
        self.color_list.column("tolerance", width=60, stretch=False, anchor="center")
        self.color_list.pack(fill="x")
        self.color_list.bind("<<TreeviewSelect>>", self._selected_color)
        color_actions = ttk.Frame(sidebar, style="Panel.TFrame")
        color_actions.pack(fill="x", pady=8)
        ttk.Button(color_actions, text="+ Manual", command=self._manual_color).pack(side="left", expand=True, fill="x")
        ttk.Button(color_actions, text="Quitar", command=self._remove_color).pack(side="left", expand=True, fill="x", padx=(8, 0))
        self._spin(sidebar, "Tolerancia del color (distancia RGB)", self.tolerance, 0, 255, self._update_tolerance)
        ttk.Label(sidebar, text="0 = coincidencia exacta. Aumenta para\nincluir sombras y compresión.", style="Muted.TLabel",
                  font=("Segoe UI", 9)).pack(anchor="w", pady=(2, 13))
        ttk.Separator(sidebar).pack(fill="x", pady=8)
        ttk.Label(sidebar, text="02  RELLENO", style="Section.TLabel").pack(anchor="w", pady=(5, 8))
        method_box = ttk.Combobox(sidebar, textvariable=self.method, values=list(METHODS), state="readonly")
        method_box.pack(fill="x")
        method_box.bind("<<ComboboxSelected>>", lambda _event: self.request_preview())
        self._spin(sidebar, "Radio de vecinos (px)", self.radius, 1, 15, self.request_preview)
        self._spin(sidebar, "Expandir máscara (px)", self.expansion, 0, 15, self.request_preview)
        ttk.Checkbutton(sidebar, text="Ver máscara en rosa", variable=self.show_mask, command=self._draw_result).pack(anchor="w", pady=8)
        ttk.Separator(sidebar).pack(fill="x", pady=8)
        ttk.Label(sidebar, text="03  EXPORTACIÓN", style="Section.TLabel").pack(anchor="w", pady=(5, 4))
        ttk.Checkbutton(sidebar, text="Conservar audio del video", variable=self.audio).pack(anchor="w")
        ttk.Label(sidebar, text="Imagen: PNG, JPG o WebP\nVideo: MP4 / H.264 / FPS constantes",
                  style="Muted.TLabel", font=("Segoe UI", 9)).pack(anchor="w", pady=(5, 12))
        self.export_button = ttk.Button(sidebar, text="Exportar resultado", style="Accent.TButton", command=self.export, state="disabled")
        self.export_button.pack(fill="x")
        self.cancel_button = ttk.Button(sidebar, text="Cancelar exportación", command=self.cancel_export.set, state="disabled")
        self.cancel_button.pack(fill="x", pady=(7, 0))
        ttk.Label(sidebar, text="Proceso local · Sin subir tus archivos",
                  style="Muted.TLabel", font=("Segoe UI", 8)).pack(side="bottom", pady=(12, 0))
        content = ttk.Frame(body)
        content.pack(side="left", fill="both", expand=True)
        ttk.Label(content, textvariable=self.file_status, background=BG, foreground=MUTED,
                  font=("Segoe UI", 10)).pack(anchor="w", pady=(7, 13))
        tools = ttk.Frame(content)
        tools.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(tools, text="Cuentagotas", variable=self.mode, value="pick", command=self._cursor).pack(side="left")
        ttk.Radiobutton(tools, text="Delimitar zona", variable=self.mode, value="roi", command=self._cursor).pack(side="left", padx=8)
        ttk.Button(tools, text="Quitar zona", command=self._clear_roi).pack(side="right")
        views = ttk.Frame(content)
        views.pack(fill="both", expand=True)
        views.columnconfigure((0, 1), weight=1, uniform="view")
        views.rowconfigure(1, weight=1)
        ttk.Label(views, text="ORIGINAL", foreground=MUTED, background=BG, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(views, text="RESULTADO", foreground=ACCENT, background=BG, font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 8))
        self.original = ImageCanvas(views, cursor="crosshair", width=1, height=1)
        self.result = ImageCanvas(views, width=1, height=1)
        self.original.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.result.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self.original.bind("<ButtonPress-1>", self._press)
        self.original.bind("<B1-Motion>", self._drag)
        self.original.bind("<ButtonRelease-1>", self._release)
        timeline = ttk.Frame(content)
        timeline.pack(fill="x", pady=(15, 0))
        ttk.Label(timeline, textvariable=self.position, background=BG, foreground=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        self.seek = ttk.Scale(timeline, from_=0, to=1, orient="horizontal", command=self._seek, state="disabled")
        self.seek.pack(fill="x", pady=8)
        ttk.Label(content, textvariable=self.mask_status, background=BG, foreground=ACCENT).pack(anchor="w")
        ttk.Label(content, text="En video, la selección de colores se aplica de nuevo en cada fotograma.",
                  background=BG, foreground=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0))
        footer = ttk.Frame(self, padding=(24, 4, 24, 16))
        footer.pack(fill="x")
        self.progress = ttk.Progressbar(footer, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 9))
        ttk.Label(footer, textvariable=self.status, background=BG, foreground=MUTED, wraplength=1250).pack(anchor="w")

    def _spin(self, parent: ttk.Frame, title: str, variable: tk.IntVar, low: int, high: int, command) -> None:
        row = ttk.Frame(parent, style="Panel.TFrame")
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=title, font=("Segoe UI", 9)).pack(anchor="w")
        box = ttk.Spinbox(row, from_=low, to=high, textvariable=variable, width=8, command=command)
        box.pack(fill="x", pady=(5, 0))
        box.bind("<Return>", lambda _event: command())
        box.bind("<FocusOut>", lambda _event: command())

    def settings(self) -> Settings:
        return Settings(tuple(self.colors), METHODS[self.method.get()], self.radius.get(), self.expansion.get(), self.roi)

    def open_file(self) -> None:
        if self.exporting:
            return
        chosen = filedialog.askopenfilename(title="Abrir imagen o video", filetypes=[
            ("Imágenes y videos", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.mp4 *.mov *.avi *.mkv *.webm *.m4v"),
            ("Todos los archivos", "*.*"),
        ])
        if chosen:
            self.load(Path(chosen))

    def load(self, path: Path) -> None:
        try:
            is_video = path.suffix.lower() in VIDEO_EXTENSIONS
            if is_video:
                width, height, fps, count = video_info(path)
                image = read_video_frame(path, 0)
                info = f"{path.name}  ·  {width} × {height}  ·  {fps:.3f} FPS"
            elif path.suffix.lower() in IMAGE_EXTENSIONS:
                image, _ = read_image(path)
                fps, count = 1.0, 1
                info = f"{path.name}  ·  {image.shape[1]} × {image.shape[0]} px"
            else:
                raise ValueError("Formato no compatible. Abre una imagen fija o un video.")
        except Exception as error:
            messagebox.showerror("No se pudo abrir el archivo", str(error), parent=self)
            return
        self.cancel_preview.set()
        self.source, self.source_image, self.is_video = path, image, is_video
        self.fps, self.frame_count, self.frame_index = fps, count, 0
        self.roi = None
        self.colors.clear()
        self._refresh_colors()
        self.preview_result, self.preview_mask = None, None
        self.original.show(image)
        self.result.show(image)
        self.file_status.set(info)
        self.seek.configure(to=max(1, count - 1), state="normal" if is_video and count > 1 else "disabled")
        self.seek.set(0)
        self._position()
        self.status.set("Añade colores con el cuentagotas. Arrastra una zona para limitar el área de limpieza.")
        if is_video:
            self.status.set("Video cargado. La salida usa FPS constantes; una fuente de FPS variables puede desincronizar el audio.")
        self.request_preview()

    def _cursor(self) -> None:
        self.original.configure(cursor="crosshair" if self.mode.get() == "pick" else "tcross")

    def _press(self, event) -> None:
        if self.exporting:
            return
        point = self.original.image_point(event.x, event.y)
        if point is None or self.source_image is None:
            return
        if self.mode.get() == "pick":
            x, y = point
            self._add_color(tuple(int(c) for c in self.source_image[y, x]))
        else:
            self.drag_start = point

    def _drag(self, event) -> None:
        if self.drag_start is None:
            return
        point = self.original.image_point(event.x, event.y, clamp=True)
        if point is None:
            return
        x0, y0 = self.drag_start
        x1, y1 = point
        self.original.roi = (min(x0, x1), min(y0, y1), max(x0, x1) + 1, max(y0, y1) + 1)
        self.original.redraw()

    def _release(self, event) -> None:
        if self.drag_start is not None:
            self._drag(event)
            self.roi = self.original.roi
            self.drag_start = None
            self.request_preview()

    def _clear_roi(self) -> None:
        if self.exporting:
            return
        self.roi = None
        self.original.roi = None
        self.original.redraw()
        self.request_preview()

    def _manual_color(self) -> None:
        if self.exporting:
            return
        chosen = colorchooser.askcolor(title="Añadir color a la máscara", parent=self)
        if chosen[0]:
            self._add_color(tuple(round(c) for c in chosen[0]))

    def _add_color(self, rgb: tuple[int, int, int]) -> None:
        try:
            target = ColorTarget(rgb, self.tolerance.get())
        except (ValueError, tk.TclError):
            self.status.set("Introduce una tolerancia válida entre 0 y 255.")
            return
        existing = next((i for i, color in enumerate(self.colors) if color.rgb == rgb), None)
        if existing is not None:
            self.color_list.selection_set(str(existing))
            return
        self.colors.append(target)
        self._refresh_colors(len(self.colors) - 1)
        self.request_preview()

    def _refresh_colors(self, selected: int | None = None) -> None:
        self.color_list.delete(*self.color_list.get_children())
        for index, color in enumerate(self.colors):
            tag = f"color-{index}"
            self.color_list.tag_configure(tag, foreground=color.hex)
            self.color_list.insert("", "end", iid=str(index), values=(f"●  {color.hex}", color.tolerance), tags=(tag,))
        if selected is not None:
            self.color_list.selection_set(str(selected))

    def _selected_color(self, _event=None) -> None:
        selection = self.color_list.selection()
        if selection:
            self.tolerance.set(self.colors[int(selection[0])].tolerance)

    def _update_tolerance(self) -> None:
        if self.exporting:
            return
        selection = self.color_list.selection()
        if not selection:
            return
        try:
            index = int(selection[0])
            self.colors[index] = replace(self.colors[index], tolerance=self.tolerance.get())
            self.color_list.set(str(index), "tolerance", self.colors[index].tolerance)
            self.request_preview()
        except (ValueError, tk.TclError):
            self.status.set("La tolerancia debe estar entre 0 y 255.")

    def _remove_color(self) -> None:
        if self.exporting:
            return
        selection = self.color_list.selection()
        if selection:
            self.colors.pop(int(selection[0]))
            self._refresh_colors()
            self.request_preview()

    def _seek(self, value: str) -> None:
        if self.source is None or not self.is_video or self.exporting:
            return
        index = int(round(float(value)))
        if index != self.frame_index:
            self.frame_index = index
            self._position()
            self.request_preview()

    def _position(self) -> None:
        if self.is_video:
            self.position.set(f"FOTOGRAMA {self.frame_index + 1:,} / {self.frame_count or '?'}  ·  {self.frame_index / self.fps:.2f} s")
        else:
            self.position.set("IMAGEN FIJA")

    def request_preview(self) -> None:
        if self.source is None or self.exporting or self.closing:
            return
        self.generation += 1
        self.preview_valid = False
        self.export_button.configure(state="disabled")
        self.cancel_preview.set()
        if self.preview_timer:
            self.after_cancel(self.preview_timer)
        self.preview_timer = self.after(200, self._start_preview)

    def _start_preview(self) -> None:
        self.preview_timer = None
        if self.preview_busy or self.source is None or self.exporting or self.closing:
            return
        try:
            settings = self.settings()
        except (ValueError, tk.TclError) as error:
            self.status.set(f"Revisa los ajustes: {error}")
            return
        generation, source, index = self.generation, self.source, self.frame_index
        image, is_video = self.source_image, self.is_video
        self.cancel_preview = threading.Event()
        cancel = self.cancel_preview
        self.preview_busy = True
        self.mask_status.set("Calculando vista previa…")

        def work() -> None:
            try:
                frame = read_video_frame(source, index) if is_video else image
                result, mask = process_frame(frame, settings, cancel)
                self.messages.put(("preview", generation, frame, result, mask, None))
            except Exception as error:
                self.messages.put(("preview", generation, None, None, None, error))
        threading.Thread(target=work, daemon=True).start()

    def _draw_result(self) -> None:
        if self.source_image is None:
            return
        if self.show_mask.get() and self.preview_mask is not None:
            self.result.show(mask_overlay(self.source_image, self.preview_mask))
        else:
            self.result.show(self.preview_result if self.preview_result is not None else self.source_image)

    def export(self) -> None:
        if self.source is None or self.exporting or not self.preview_valid:
            return
        try:
            settings = self.settings()
        except (ValueError, tk.TclError) as error:
            messagebox.showerror("Ajustes inválidos", str(error), parent=self)
            return
        if not settings.colors:
            messagebox.showinfo("Añade un color", "Selecciona al menos un color en la imagen original.", parent=self)
            return
        filetypes = [("Video MP4", "*.mp4")] if self.is_video else [("Imagen PNG", "*.png"), ("Imagen JPEG", "*.jpg"), ("Imagen WebP", "*.webp")]
        chosen = filedialog.asksaveasfilename(title="Exportar resultado", defaultextension=".mp4" if self.is_video else ".png",
            initialfile=f"{self.source.stem}_limpio", filetypes=filetypes)
        if not chosen:
            return
        source, destination, video, audio = self.source, Path(chosen), self.is_video, self.audio.get()
        if source.resolve() == destination.resolve():
            messagebox.showerror("Conserva el original", "Elige un nombre de salida diferente.", parent=self)
            return
        self.cancel_export.clear()
        self.exporting = True
        self._export_state()
        self.progress["value"] = 0
        self.status.set("Iniciando exportación…")

        def work() -> None:
            try:
                if video:
                    def progress(done: int, total: int, phase: str) -> None:
                        # Limita los mensajes sin perder el último estado.
                        if done % 5 == 0 or done == total or phase != "Procesando fotogramas":
                            self.messages.put(("progress", done, total, phase))
                    export_video(source, destination, settings, self.cancel_export, progress, audio)
                else:
                    export_image(source, destination, settings, self.cancel_export)
                self.messages.put(("export_done", destination, None))
            except Exception as error:
                self.messages.put(("export_done", destination, error))
        threading.Thread(target=work, daemon=False).start()

    def _export_state(self) -> None:
        self.export_button.configure(state="disabled" if self.exporting or not self.preview_valid else "normal")
        self.cancel_button.configure(state="normal" if self.exporting else "disabled")
        self.open_button.configure(state="disabled" if self.exporting else "normal")
        self.demo_button.configure(state="disabled" if self.exporting else "normal")
        self.seek.configure(state="normal" if not self.exporting and self.is_video and self.frame_count > 1 else "disabled")
        # La exportación usa una instantánea inmutable de los ajustes.
        def set_children(widget) -> None:
            for child in widget.winfo_children():
                if child not in (self.export_button, self.cancel_button):
                    if isinstance(child, (ttk.Button, ttk.Spinbox, ttk.Checkbutton, ttk.Combobox)):
                        if self.exporting:
                            child.state(["disabled"])
                        else:
                            child.state(["!disabled"])
                    set_children(child)
        set_children(self.sidebar)

    def _poll(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if message[0] == "preview":
                    _, generation, frame, result, mask, error = message
                    self.preview_busy = False
                    if generation != self.generation:
                        if not self.closing:
                            self._start_preview()
                        continue
                    if error:
                        if not isinstance(error, ProcessingCancelled):
                            self.status.set(str(error))
                            self.mask_status.set("Revisa la máscara o los ajustes")
                    else:
                        self.source_image, self.preview_result, self.preview_mask = frame, result, mask
                        self.original.show(frame, self.roi)
                        self._draw_result()
                        count = int(np.count_nonzero(mask))
                        self.mask_status.set(f"Máscara: {count:,} píxeles  ·  {100 * count / mask.size:.2f}% de la imagen")
                        self.preview_valid = True
                        self.export_button.configure(state="normal" if self.colors and not self.exporting else "disabled")
                        if self.colors:
                            self.status.set("Vista previa lista. Ajusta los colores o exporta el resultado.")
                elif message[0] == "progress":
                    _, done, total, phase = message
                    self.progress["value"] = min(99, 100 * done / max(1, total)) if total else 0
                    self.status.set(f"{phase}: {done:,}" + (f" / {total:,} fotogramas" if total else " fotogramas"))
                elif message[0] == "export_done":
                    _, destination, error = message
                    self.exporting = False
                    self._export_state()
                    if isinstance(error, ProcessingCancelled):
                        self.progress["value"] = 0
                        self.status.set("Exportación cancelada. No se guardó un archivo incompleto.")
                    elif error:
                        self.progress["value"] = 0
                        self.status.set(f"Error de exportación: {error}")
                        if not self.closing:
                            messagebox.showerror("No se pudo exportar", str(error), parent=self)
                    else:
                        self.progress["value"] = 100
                        self.status.set(f"Guardado: {destination}")
                        if not self.closing:
                            messagebox.showinfo("Exportación completa", f"Archivo guardado en:\n{destination}", parent=self)
        except queue.Empty:
            pass
        if self.closing and not self.exporting:
            self.destroy()
            return
        self.after(80, self._poll)

    def demo(self) -> None:
        if self.exporting:
            return
        # Ejemplo sintético propio que permite probar toda la interfaz sin archivos externos.
        folder = Path(__file__).resolve().parent.parent / "samples" / "generated"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "ejemplo.png"
        width, height = 1000, 700
        yy, xx = np.mgrid[:height, :width]
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        rgb[..., 0] = 28 + (xx * 32 // width)
        rgb[..., 1] = 67 + (yy * 65 // height)
        rgb[..., 2] = 89 + (xx * 45 // width)
        image = Image.fromarray(rgb)
        draw = ImageDraw.Draw(image)
        draw.ellipse((540, 55, 835, 350), fill="#E8BD78")
        draw.polygon([(0, 470), (290, 235), (620, 700), (0, 700)], fill="#284B56")
        draw.polygon([(300, 700), (710, 300), (1000, 580), (1000, 700)], fill="#1C3B48")
        try:
            font = ImageFont.truetype("arial.ttf", 48)
        except OSError:
            font = ImageFont.load_default(size=48)
        draw.text((620, 566), "DEMO", fill="#FFFFFF", font=font)
        draw.rectangle((621, 631, 800, 640), fill="#FF50B0")
        image.save(path)
        self.load(path)
        self.roi = (590, 540, 840, 665)
        self.colors = [ColorTarget((255, 255, 255), 12), ColorTarget((255, 80, 176), 12)]
        self._refresh_colors(0)
        self.request_preview()

    def _close(self) -> None:
        self.cancel_preview.set()
        self.closing = True
        if self.exporting:
            self.cancel_export.set()
            self.status.set("Cancelando exportación y limpiando archivos temporales…")
        else:
            self.destroy()


def main() -> None:
    Application().mainloop()


if __name__ == "__main__":
    main()
