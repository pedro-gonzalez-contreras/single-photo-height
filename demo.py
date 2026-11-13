"""Open a photo, automatically propose endpoints, compare two height estimates."""
import argparse
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk
from height_estimation import Chessboard, load_image, detect_chessboard, measure
from measure import save_result
from download_model import DEFAULT_MODEL


def board_from_fields(pattern, square_mm):
    match = re.fullmatch(r'\s*(\d+)\s*[xX×]\s*(\d+)\s*', pattern)
    if match is None:
        raise ValueError('Enter the pattern as columns x rows of squares, for example 9 x 6.')
    columns, rows = map(int, match.groups())
    if max(columns, rows) > 100:
        raise ValueError('Use no more than 100 squares per side.')
    try:
        size = float(square_mm.strip().replace(',', '.'))
    except ValueError as exc:
        raise ValueError('Enter the physical square side in millimeters, for example 27 or 27.5.') from exc
    return Chessboard(columns, rows, size)


class HeightDemo:
    def __init__(self, root, board, automatic=True, model=DEFAULT_MODEL):
        self.root, self.board = root, board
        self.automatic, self.model = automatic, model
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.generation = 0
        self.auto_details = None
        self.image = self.path = self.result = None
        self.corners, self.world = [], None
        self.points = []
        self.scale = 1.
        root.title('Single Photo Height — scale & homography')
        root.geometry('1120x850')
        root.minsize(700, 600)
        controls = ttk.Frame(root, padding=10)
        controls.pack(fill='x')
        ttk.Button(controls, text='Open photo', command=self.open_photo).pack(side='left')
        ttk.Button(controls, text='Correct manually', command=self.reset).pack(side='left', padx=8)
        ttk.Button(controls, text='Detect automatically', command=self.start_auto).pack(side='left', padx=8)
        self.save = ttk.Button(controls, text='Save result', command=self.save_output, state='disabled')
        self.save.pack(side='left')
        settings = ttk.LabelFrame(root, text='Chessboard reference', padding=10)
        settings.pack(fill='x', padx=10, pady=(0, 5))
        self.pattern_text = tk.StringVar(value=f'{board.columns} x {board.rows}')
        self.square_text = tk.StringVar(value=f'{board.square_mm:g}')
        ttk.Label(settings, text='Pattern (columns x rows of squares)').grid(row=0, column=0, sticky='w')
        pattern = ttk.Combobox(settings, textvariable=self.pattern_text, width=13,
                               values=['9 x 6', '10 x 7', '8 x 6', '8 x 5', '7 x 5'])
        pattern.grid(row=1, column=0, sticky='w', pady=(4, 0))
        ttk.Label(settings, text='Square side (mm)').grid(row=0, column=1, sticky='w', padx=15)
        size = ttk.Spinbox(settings, textvariable=self.square_text, from_=0.1, to=1000,
                           increment=1, width=12)
        size.grid(row=1, column=1, sticky='w', padx=15, pady=(4, 0))
        ttk.Button(settings, text='Apply pattern', command=self.apply_board).grid(row=1, column=2, padx=8)
        self.board_status = tk.StringVar()
        ttk.Label(settings, textvariable=self.board_status, wraplength=650).grid(
            row=2, column=0, columnspan=3, sticky='w', pady=(8, 0))
        pattern.bind('<Return>', lambda _: self.apply_board())
        size.bind('<Return>', lambda _: self.apply_board())
        self.instruction = tk.StringVar(value='Open a photo containing the complete chessboard and person.')
        ttk.Label(root, textvariable=self.instruction, padding=(12, 5), wraplength=1000).pack(fill='x')
        self.readout = tk.StringVar(value='Simple scale: —     Homography: —')
        ttk.Label(root, textvariable=self.readout, font=('Segoe UI', 16, 'bold'), padding=12).pack(fill='x')
        self.canvas = tk.Canvas(root, background='#17212d', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=10)
        self.canvas.bind('<Configure>', lambda _: self.redraw())
        self.canvas.bind('<Button-1>', self.click)
        ttk.Label(root, text='One plane for person and board. Use the heel / floor-at-wall base, not the forward toe. '
                  'Simple scale: near-frontal views. Both estimates are experimental.',
                  padding=12, wraplength=1000).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.pattern_text.trace_add('write', self.settings_changed)
        self.square_text.trace_add('write', self.settings_changed)
        self.settings_changed()

    def settings_pending(self):
        try:
            return board_from_fields(self.pattern_text.get(), self.square_text.get()) != self.board
        except ValueError:
            return True

    def settings_changed(self, *_):
        board = self.board
        pending = self.settings_pending()
        prefix = 'Changes pending — click Apply pattern. ' if pending else ''
        self.board_status.set(prefix + f'Applied: {board.columns} x {board.rows} squares '
                              f'({board.inner_corners[0]} x {board.inner_corners[1]} inner corners), '
                              f'{board.square_mm:g} mm. You can type another pattern.')
        self.save.config(state='normal' if self.result is not None and not pending else 'disabled')

    def apply_board(self):
        try:
            board = board_from_fields(self.pattern_text.get(), self.square_text.get())
        except ValueError as exc:
            messagebox.showerror('Invalid chessboard settings', str(exc))
            return
        previous = self.board
        self.board = board
        self.settings_changed()
        if self.image is None:
            self.instruction.set('Reference updated. Open a photo to measure.')
            return
        self.generation += 1  # Ignore inference from the previous configuration.
        self.result = None
        self.save.config(state='disabled')
        self.readout.set('Simple scale: —     Homography: —')
        if self.world is not None and previous.inner_corners == board.inner_corners:
            self.world = board.metric_points()
        elif not self.detect_reference():
            return
        # Endpoints belong to the image, so changing reference size preserves them.
        if len(self.points) == 2:
            self.update_measurement()
            self.instruction.set('Reference updated and height recalculated using the existing points.')
        elif self.points:
            self.instruction.set('Reference updated. Click the floor base to complete the measurement.')
        elif self.automatic:
            self.start_auto()
        else:
            self.instruction.set('Reference updated. Click the top of the head, then the floor base.')
        self.redraw()

    def detect_reference(self):
        self.corners, self.world = [], None
        try:
            self.corners, self.world = detect_chessboard(self.image, self.board)
        except ValueError as exc:
            self.instruction.set(str(exc) + ' Change the pattern and click Apply pattern to retry this photo.')
            self.redraw()
            return False
        return True

    def close(self):
        self.generation += 1
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()

    def open_photo(self):
        name = filedialog.askopenfilename(title='Select photo', filetypes=[('Images', '*.png *.jpg *.jpeg *.webp *.bmp'), ('All files', '*.*')])
        if name:
            self.load(Path(name))

    def load(self, path):
        try:
            self.board = board_from_fields(self.pattern_text.get(), self.square_text.get())
        except ValueError as exc:
            messagebox.showerror('Invalid chessboard settings', str(exc))
            return
        self.generation += 1
        self.image = self.path = self.result = None
        self.corners, self.world = [], None
        self.auto_details = None
        self.points = []
        self.settings_changed()
        self.save.config(state='disabled')
        self.readout.set('Simple scale: —     Homography: —')
        self.canvas.delete('all')
        try:
            image = load_image(path)
        except (OSError, ValueError) as exc:
            self.instruction.set('No measurement available. Check the image and board configuration.')
            messagebox.showerror('Cannot measure this photo', str(exc))
            return
        self.image, self.path = image, path
        if not self.detect_reference():
            return
        self.reset()
        if self.automatic:
            self.start_auto()

    def reset(self):
        self.generation += 1
        self.auto_details = None
        self.points, self.result = [], None
        self.save.config(state='disabled')
        self.readout.set('Simple scale: —     Homography: —')
        self.instruction.set(f'{len(self.corners)} board corners detected. Click 1/2: top of the head (green).'
                             if self.world is not None else 'Open a photo and apply the matching chessboard pattern.')
        self.redraw()

    def start_auto(self):
        if self.image is None or self.world is None or self.settings_pending():
            return
        self.reset()
        token = self.generation
        self.instruction.set('Detecting person, crown and floor boundary locally…')
        from auto_endpoints import detect_endpoints
        future = self.executor.submit(detect_endpoints, self.image.copy(), self.model)
        self.root.after(100, lambda: self.finish_auto(future, token))

    def finish_auto(self, future, token):
        if token != self.generation:
            return  # A different photo or manual correction superseded this job.
        if not future.done():
            self.root.after(100, lambda: self.finish_auto(future, token))
            return
        try:
            points, details = future.result()
            self.points, self.auto_details = points, details
            self.update_measurement()
            self.instruction.set('Automatic estimate. Review green crown, red base and cyan floor line. '
                                 'Use Correct manually if needed, or Save result.')
        except Exception as exc:
            self.points, self.auto_details, self.result = [], None, None
            self.save.config(state='disabled')
            self.instruction.set(f'Automatic points unavailable: {exc} Click head, then floor base to continue manually.')
        self.redraw()

    def update_measurement(self):
        self.result = measure(self.corners, self.world, self.points, self.board, self.image.shape)
        if self.auto_details is not None:
            self.result['endpoint_source'] = 'Automatic crown segmentation and floor/wall boundary; unreviewed.'
            self.result['automatic_endpoints'] = self.auto_details
        labels = {'simple_scale': 'Simple scale', 'homography': 'Homography'}
        self.readout.set('     |     '.join(f"{labels[k]}: {v['height_cm']:.1f} cm" if v['status']=='ok' else f'{labels[k]}: failed'
                                           for k, v in self.result['measurements'].items()))
        self.settings_changed()

    def redraw(self):
        self.canvas.delete('all')
        if self.image is None:
            return
        h, w = self.image.shape[:2]
        cw, ch = max(self.canvas.winfo_width(), 1), max(self.canvas.winfo_height(), 1)
        self.scale = min(cw/w, ch/h)
        dw, dh = max(1, round(w*self.scale)), max(1, round(h*self.scale))
        self.offset = ((cw-dw)/2, (ch-dh)/2)
        self.display_size = (dw, dh)
        self.tk_image = ImageTk.PhotoImage(Image.fromarray(self.image).resize((dw, dh), Image.Resampling.LANCZOS))
        ox, oy = self.offset
        self.canvas.create_image(ox, oy, image=self.tk_image, anchor='nw')
        if self.auto_details is not None:
            line = self.auto_details['floor_line']
            segments = line['visible_segments']
            left, right = min(s[0] for s in segments), max(s[2] for s in segments)
            self.canvas.create_line(ox+left*dw/w, oy+(line['slope']*left+line['intercept'])*dh/h,
                                    ox+right*dw/w, oy+(line['slope']*right+line['intercept'])*dh/h,
                                    fill='#00d5ff', width=2)
        for x, y in self.corners:
            sx, sy = ox+x*dw/w, oy+y*dh/h
            self.canvas.create_oval(sx-2, sy-2, sx+2, sy+2, outline='#00d5ff')
        for (x, y), color in zip(self.points, ['#00ff7f', '#ff4545']):
            sx, sy = ox+x*dw/w, oy+y*dh/h
            self.canvas.create_oval(sx-7, sy-7, sx+7, sy+7, outline=color, width=2)
            self.canvas.create_line(sx-12, sy, sx+12, sy, fill=color, width=2)
            self.canvas.create_line(sx, sy-12, sx, sy+12, fill=color, width=2)

    def click(self, event):
        if self.image is None or self.world is None or self.settings_pending() or len(self.points) == 2:
            return
        ox, oy = self.offset
        dw, dh = self.display_size
        if not (ox <= event.x < ox+dw and oy <= event.y < oy+dh):
            return
        h, w = self.image.shape[:2]
        self.generation += 1  # A manual click cancels any pending automatic proposal.
        self.points.append([(event.x-ox)*w/dw, (event.y-oy)*h/dh])
        if len(self.points) == 1:
            self.instruction.set('Click 2/2: heel / floor base at the reference plane (red).')
        else:
            try:
                self.update_measurement()
                self.instruction.set('Two manual points selected. Reset to adjust them, or save JSON and an annotated image.')
                self.settings_changed()
            except ValueError as exc:
                self.points.pop()
                self.instruction.set(str(exc)+' Select the base again.')
        self.redraw()

    def save_output(self):
        if self.result is None or self.settings_pending():
            return
        output = Path('outputs')/(self.path.stem+'_measurement.json')
        overlay = output.with_name(output.stem+'_annotated.png')
        if self.path.resolve() in (output.resolve(), overlay.resolve()):
            messagebox.showerror('Cannot save', 'Input and output paths must differ.')
            return
        try:
            save_result(self.image, self.result, output)
        except OSError as exc:
            messagebox.showerror('Cannot save', str(exc))
            return
        self.instruction.set(f'Saved {output} and {overlay}. Source photo unchanged.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', type=Path)
    parser.add_argument('--squares', type=int, nargs=2, default=[9, 6], metavar=('COLS', 'ROWS'))
    parser.add_argument('--square-mm', type=float, default=27.)
    parser.add_argument('--manual', action='store_true', help='Skip automatic detection and mark two points.')
    parser.add_argument('--model', type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    try:
        board = Chessboard(*args.squares, args.square_mm)
    except ValueError as exc:
        parser.error(str(exc))
    root = tk.Tk()
    app = HeightDemo(root, board, automatic=not args.manual, model=args.model)
    if args.image:
        root.after(100, lambda: app.load(args.image))
    root.mainloop()


if __name__ == '__main__':
    main()
