import math
import time

from collections import deque

from kivy.properties import NumericProperty, BooleanProperty, ListProperty, ColorProperty
from kivy.core.text import Label as CoreLabel
from kivy.graphics import Rectangle
from kivy.graphics import Color, Line, StencilPush, StencilUse, StencilUnUse, StencilPop
from kivy.uix.widget import Widget

class Waveform(Widget):
    ymin = NumericProperty(-20)
    ymax = NumericProperty(20)
    fps = NumericProperty(30)

    time_window_sec = NumericProperty(4.0)   # e.g. 4 seconds visible
    major_y_ticks = NumericProperty(4)
    major_x_ticks = NumericProperty(4)

    horizontalGrid_lineWidth = NumericProperty(1)
    verticalGrid_lineWidth = NumericProperty(1)

    gap_size = NumericProperty(5)

    graph_sweep_old_color = ListProperty()

    auto_scale = BooleanProperty(True)

    max_ymax = NumericProperty(float('inf'))   # hard ceiling for ymax
    min_ymin = NumericProperty(float('-inf'))   # hard floor for ymin

    autoscale_interval = NumericProperty(2)   # seconds
    autoscale_margin = NumericProperty(0.15)    # 15% headroom
    autoscale_alpha = NumericProperty(0.7)      # smoothing factor
    autoscale_quantum = NumericProperty(10)  # snap to multiples of 10
    autoscale_window_sec = NumericProperty(0)  # 0 means use full visible window

    graph_color = ListProperty([0, 1, 0, 1])

    def __init__(self, data_source=None, line_width=1.3, **kwargs):
        super().__init__(**kwargs)

        self.WINDOW = int(self.time_window_sec * self.fps)
        self.buffer_size = int(self.WINDOW * 1.5) # E.g. 60fps. 0.0167ms. Lowest interval can be 0.013 meaning fps + fps / 2. Safe margin.
        self.buffer = deque(((0.0, 0) for i in range(self.buffer_size)), maxlen=self.buffer_size)     # For Scrolling type graph.
        self.head = 0

        self.sample_index = 0  # "current position" as you described
        self.data_source = data_source
        self.graph_sweep_old_color = self.graph_color[:-1] + [0.5,]

        self.freeze_graph = False

        self.sweep_mode = False
        self.sweep_buffer = [(0, 0)] * self.buffer_size      # For Sweeping type graph.
        self.sweep_pos = 0               # current X index
        self.last_sweep_position = self.WINDOW # The sweep position at which wrapping occured at last cycle.
        self._left_segment_done = False
        self._right_segment_done = False

        self._minimum_timeWindow = 1    # Hard coded. Not flexible.
        self._maximum_timeWindow = 20

        # Storage of min / max during update.
        self.dataMin = 0
        self.dataMax = 0

        with self.canvas:
            StencilPush()

            self._stencil_rect = Rectangle(pos=self.pos, size=self.size)
            StencilUse()

            self._line_color = Color(*self.graph_color)
            self.line = Line(points=[], width=line_width)
            self.line_left = Line(points=[], width=line_width)

            self._line_right_color = Color(*self.graph_sweep_old_color)
            self.line_right = Line(points=[], width=line_width)

            StencilUnUse()
            self._stencil_rect_unuse = Rectangle(pos=self.pos, size=self.size)

            StencilPop()

        self.bind(pos=self._update_clip, size=self._update_clip)
        self.bind(size=self.redraw, pos=self.redraw)
        self.bind(size=self.draw_grid,
                    ymin=self.draw_grid,
                    ymax=self.draw_grid)
        self.bind(ymin=self.redraw,
                    ymax=self.redraw)
        self.bind(max_ymax=self._apply_y_bounds,
                    min_ymin=self._apply_y_bounds)
        self.bind(time_window_sec=self._rebuild_window,
                    fps=self._rebuild_window)
        self.bind(graph_color=self._update_graph_colors)

        self._apply_y_bounds()
        self._update_graph_colors()
        
    def freeze(self):
        self.freeze_graph = True
    
    def resume(self):
        self.freeze_graph = False

    def set_scroll_mode(self):
        if self.sweep_mode == False: # prevent repeated calls as it consists resetting.
            return
        
        self.sweep_mode = False

        w, h = self.size
        x0, y0 = self.pos

        ymin = self.ymin
        ymax = self.ymax

        scale = h / (ymax - ymin)

        # Read the line plot lines. they contain the right data.
        # put the left line at the latest, right line points at the last.
        # THIS HAS POINTS, NOT TIME MAPPINGS.
    
        self.buffer = deque(((0, 0) for i in range(self.buffer_size)), maxlen=self.buffer_size)

        # x is from 0 to widget's size.
        # it is calculated after getting the current 't', subtracting t_start and then dividign by the window.size 

        latest_t = time.monotonic()
        t_start = latest_t - self.time_window_sec

        pts = self.line_left.points
        for i in range(0, len(pts), 2):
            self.buffer.append((t_start + (pts[i] - x0) * self.time_window_sec / w, round(ymin + (pts[i + 1] - y0) / scale)))  # round float to int as they are values.

        latest_t = time.monotonic()
        t_start = latest_t - self.time_window_sec

        pts = self.line_right.points
        for i in range(0, len(pts), 2):
            self.buffer.append((t_start + (pts[i] - x0) * self.time_window_sec / w, round(ymin + (pts[i + 1] - y0) / scale)))    # Scaling of 'y' is reverse of what is done in redraw.

        self.line_left.points = []
        self.line_right.points = []

    def set_sweep_mode(self):
        if self.sweep_mode == True: # prevent repeated calls as it consists resetting.
            return
        
        self.sweep_mode = True
        self.sweep_start_time = time.monotonic()
        self.sweep_pos = 0
        self.head = 0

        # Initialize sweep buffer again. Syncs with refresh mode too.
        self.sweep_buffer = [(0, 0)] * self.buffer_size

        # below, calculating offsets of each timestamp against start v/s WINDOWSIZE to map it to a point in WINDOWSIZE.
        latest_t = self.buffer[-1][0]
        t_start = latest_t - self.time_window_sec

        # Does not work when self.buffer is empty initially.
        # overwrites the entire buffer, thereby clearing it and overwriting with new values.
        for i, (t, v) in enumerate(self.buffer):
            self.sweep_buffer[i] = (((t - t_start) / self.time_window_sec) * self.WINDOW), v

        self.line.points = []   # clear the visible line.

    def _update_clip(self, *args):
        self._stencil_rect.pos = self.pos
        self._stencil_rect.size = self.size

        self._stencil_rect_unuse.pos = self.pos
        self._stencil_rect_unuse.size = self.size

    def _update_graph_colors(self, *args):
        faded_color = self.graph_color[:-1] + [0.5]
        if self.graph_sweep_old_color != faded_color:
            self.graph_sweep_old_color = faded_color
        self._line_color.rgba = self.graph_color
        self._line_right_color.rgba = self.graph_sweep_old_color

    def upscale_graph(self, delta=1):
        if self.time_window_sec >= self._maximum_timeWindow:
            return
        
        self.major_x_ticks += delta
        self.time_window_sec += delta

    def downscale_graph(self, delta=1):
        if self.time_window_sec <= self._minimum_timeWindow:
            return
        
        self.major_x_ticks -= delta
        self.time_window_sec -= delta

    def get_last_seconds(self, seconds: float):
        portion = seconds / self.time_window_sec
        return self.get_plot_points(portion=portion)

    def get_plot_points(
        self,
        *,
        portion: float | None = None,
        start: float = 0.0,
        end: float = 1.0,
        mode: str = "visible"
    ):
        if portion is not None:
            if not (0.0 < portion <= 1.0):
                raise ValueError("portion must be in (0, 1]")
            start = 1.0 - portion
            end = 1.0

        start = max(0.0, min(1.0, start))
        end   = max(0.0, min(1.0, end))

        if start >= end:
            return []

        points = []

        if self.sweep_mode:
            x0 = start * self.WINDOW
            x1 = end   * self.WINDOW

            for x, v in self.sweep_buffer:
                if x0 <= x <= x1:
                    points.append((x, v))
        else:
            now = time.monotonic()
            t_start = now - self.time_window_sec
            t0 = t_start + start * self.time_window_sec
            t1 = t_start + end   * self.time_window_sec

            for t, v in self.buffer:
                if t0 <= t <= t1:
                    points.append((t, v))

        return points

    def _rebuild_window(self, *args):
        '''
        This function works for both upscale and downscale.
        '''
        old_window = self.WINDOW
        new_window = max(2, int(self.time_window_sec * self.fps))
        
        old_buffer_size = self.buffer_size
        new_buffer_size = int(new_window * 1.5)

        # Copy most recent samples
        samples_to_copy = min(old_buffer_size, new_buffer_size)

        if new_window == old_window:
            return

        if self.sweep_mode:
            old_buffer = self.sweep_buffer
            self.sweep_buffer = [(0, 0)] * new_buffer_size

            # in case of upscale, discard previous values. for this, create an offset and during appending, use that.
            if new_buffer_size < old_buffer_size: # DOWNSCALING.        could have used window-size based comparison too.
                offset = old_buffer_size - new_buffer_size

                if self.sweep_pos < (old_window * 0.9):
                    # then just simply discard near-end values.
                    samples_to_copy = samples_to_copy - offset

                # requires repositioning of points and then scaling to our new window size.
                for i in range(samples_to_copy):
                    p, v = old_buffer[i]

                    # convert this new position against new window to get new pos.
                    perc = p / new_window

                    p = (perc * new_window)

                    self.sweep_buffer[i] = (p, v)
            else:   # UPSCALING.
                # only needs scaling from, from e.g., pos = (0, 420) to pos = (0, 520)
                for i in range(samples_to_copy):
                    p, v = old_buffer[i]

                    if p >= self.last_sweep_position:   # if position is found to be more than last swept position, stop - to avoid further garbage from copying.
                        break

                    perc = p / new_window   # calculation point progression for new window.

                    p = (perc * new_window) # convert this directly to new pos, valid against new window. reduces logically.

                    self.sweep_buffer[i] = (p, v)       

            perc = self.sweep_pos / new_window

            self.sweep_pos = perc * new_window
            self.last_sweep_position = new_window

            # map head to where it might have been, if it was to run in the new window.
            perc = self.head / new_buffer_size
            self.head = int(perc * new_buffer_size)

            if self.head >= new_buffer_size:
                self.head = 0
        else:
            # in this graph, everything is time-based.
            old_buffer = self.buffer
            self.buffer = deque(((0, 0) for i in range(new_buffer_size)), maxlen=new_buffer_size)

            # in case of upscale, discard previous values. for this, create an offset and during appending, use that.
            if new_buffer_size < old_buffer_size: # DOWNSCALING.        could have used window-size based comparison too.
                offset = old_buffer_size - new_buffer_size

                for i in range(samples_to_copy):
                    p, v = old_buffer[offset + i]
                    self.buffer.append((p, v))

            else:   # UPSCALING.
                offset = new_buffer_size - old_buffer_size

                for t, v in old_buffer: # Simple copying 
                    self.buffer.append((t, v))    

        self.WINDOW = new_window
        self.buffer_size = new_buffer_size  # finally, update new buffer's size. could have been updated and used directly, but for simplicty kept like this.

        self.draw_grid()
        self.redraw()

    def draw_grid(self, *args):
        self.canvas.before.clear()

        w, h = self.size
        x0, y0 = self.pos

        with self.canvas.before:
            Color(0.25, 0.25, 0.25)

            # ---- Horizontal (Y) grid ----
            for i in range(self.major_y_ticks + 1):
                y = y0 + i * h / self.major_y_ticks
                Line(points=[x0, y, x0 + w, y], width=self.horizontalGrid_lineWidth)

            Color(1, 1, 1)
            for i in range(self.major_y_ticks + 1):
                value = self.ymin + i * (self.ymax - self.ymin) / self.major_y_ticks
                y = y0 + i * h / self.major_y_ticks

                lbl = CoreLabel(
                    text=f"{value:.0f}",
                    font_size=12,
                    color=(1, 1, 1, 1)
                )
                lbl.refresh()

                px = int(x0 - lbl.texture.size[0] - 5)
                py = int(y - lbl.texture.size[1] / 2)

                Rectangle(
                    texture=lbl.texture,
                    pos=(px, py),
                    size=lbl.texture.size
                )

            Color(0.25, 0.25, 0.25)
            # ---- Vertical (Time) grid ----
            for i in range(self.major_x_ticks + 1):
                x = x0 + i * w / self.major_x_ticks
                Line(points=[x, y0, x, y0 + h], width=self.verticalGrid_lineWidth)

            # ---- Time (X-axis) labels ----
            for i in range(self.major_x_ticks + 1):
                x = x0 + i * w / self.major_x_ticks

                time_sec = i * (self.time_window_sec / self.major_x_ticks)

                lbl = CoreLabel(
                    text=f"{time_sec:.1f}s",
                    font_size=12,
                    color=(1, 1, 1, 1)
                )
                lbl.refresh()

                Color(1, 1, 1, 1)
                Rectangle(
                    texture=lbl.texture,
                    pos=(x - lbl.texture.size[0] / 2, y0 - lbl.texture.size[1] - 4),
                    size=lbl.texture.size
                )

    def snap_down(self, value, quantum):
        return math.floor(value / quantum) * quantum

    def snap_up(self, value, quantum):
        return math.ceil(value / quantum) * quantum

    def _apply_y_bounds(self, *args):
        clamped_ymin = max(self.ymin, self.min_ymin)
        clamped_ymax = min(self.ymax, self.max_ymax)

        if clamped_ymin > clamped_ymax:
            if self.min_ymin <= self.max_ymax:
                clamped_ymin = self.min_ymin
                clamped_ymax = self.max_ymax
            else:
                clamped_ymin = clamped_ymax = self.ymin

        if clamped_ymin == clamped_ymax:
            clamped_ymax = clamped_ymin + 1

        if self.ymin != clamped_ymin:
            self.ymin = clamped_ymin
        if self.ymax != clamped_ymax:
            self.ymax = clamped_ymax
    
    def update_autoscale(self, *args):
        if self.freeze_graph:
            return
        if not self.auto_scale:
            return

        now = time.monotonic()
        autoscale_window = self.autoscale_window_sec if self.autoscale_window_sec > 0 else self.time_window_sec
        t_start = now - min(autoscale_window, self.time_window_sec)

        vmin = None
        vmax = None

        if self.sweep_mode:
            # Only consider valid sweep data [0 .. head-1]
            for i in range(self.head):
                _, value = self.sweep_buffer[i]
                if vmin is None:
                    vmin = vmax = value
                else:
                    if value < vmin:
                        vmin = value
                    elif value > vmax:
                        vmax = value
        else:
            for t, value in self.buffer:
                if t < t_start: # Skip considering out-of-bound points which may be in the buffer.
                    continue

                if vmin is None:
                    vmin = vmax = value
                else:
                    if value < vmin:
                        vmin = value
                    elif value > vmax:
                        vmax = value

        if vmin is None or vmin == vmax:
            return
        
        self.dataMin = vmin
        self.dataMax = vmax

        span = vmax - vmin
        target_min = vmin - span * self.autoscale_margin
        target_max = vmax + span * self.autoscale_margin

        q = self.autoscale_quantum
        target_min = self.snap_down(target_min, q)
        target_max = self.snap_up(target_max, q)

        self.ymin = (1 - self.autoscale_alpha) * self.ymin + self.autoscale_alpha * target_min
        self.ymax = (1 - self.autoscale_alpha) * self.ymax + self.autoscale_alpha * target_max
        self._apply_y_bounds()

        # Hard clamps — prevent autoscale from exceeding bounds
        if self.ymax > self.max_ymax:
            self.ymax = self.max_ymax
        if self.ymin < self.min_ymin:
            self.ymin = self.min_ymin

    # -----------------------------------
    def update_from_source(self, *args):
        if not self.data_source:
            return
        
        value = round(self.data_source())
        now = time.monotonic()

        if self.sweep_mode:
            elapsed = now - self.sweep_start_time
            pos = (elapsed / self.time_window_sec) * self.WINDOW    # --- time-synchronised sweep position ---

            if pos != self.sweep_buffer[self.head - 1][0]:  # Avoid duplicate time samples even if with different readings.
                # wrap
                if elapsed >= self.time_window_sec:
                    self.last_sweep_position = self.sweep_pos  # stores the last sample's position for purpose of proper right-line rendering.
                    self.sweep_buffer[self.head] = (pos, value) # Store the last record value in the last spot only.
                    self.sweep_start_time = now
                    pos = 0
                    self.head = 0

                self.sweep_pos = pos

                self.sweep_buffer[self.head] = (pos, value)     # Only storage of points. Not direct mapping to X axis.
                self.head = (self.head + 1)       # Sometimes the buffer fills with too many minutely displaced values.

        else:
            if self.buffer[-1][0] != now:
                self.buffer.append((now, value))

        if not self.freeze_graph:
            self.redraw()

    def redraw(self, *args):
        if self.sweep_mode:
            self._redraw_sweep()
        else:
            self._redraw_scroll()

    def _redraw_scroll(self):
        w, h = self.size
        x0, y0 = self.pos

        ymin = self.ymin
        ymax = self.ymax

        scale = h / (ymax - ymin)
        points = []

        latest_t = self.buffer[-1][0]
        t_start = latest_t - self.time_window_sec

        for t, v in self.buffer:      
            x = x0 + ((t - t_start) / self.time_window_sec) * w
            y = y0 + (v - ymin) * scale
            points.extend([x, y])

        self.line.points = points

    def _redraw_sweep(self):
        w, h = self.size
        x0, y0 = self.pos

        ymin = self.ymin
        ymax = self.ymax
        if ymax == ymin:
            return

        scale = h / (ymax - ymin)

        pts_left = []
        pts_right = []

        self._left_segment_done = False # Reset
        self._right_segment_done = False

        break_index = 0

        for i in range(self.buffer_size):
            t, v = self.sweep_buffer[i]
            if t >= self.sweep_pos:
                break_index = i
                break

            x = x0 + (t / self.WINDOW) * w
            y = y0 + (v - ymin) * scale
            pts_left.extend([x, y])

        for i in range(break_index, self.buffer_size):
            t, v = self.sweep_buffer[i]
            if t > self.WINDOW:     # let only left line draw. ignore right line.
                continue
            if t < self.sweep_buffer[break_index][0] + self.gap_size:   # do not draw any "before" point from remanent data + gap size.
                continue
            if t >= self.last_sweep_position:
                break
            
            x = x0 + (t / self.WINDOW) * w
            y = y0 + (v - ymin) * scale
            pts_right.extend([x, y])

        self.line_left.points = pts_left
        self.line_right.points = pts_right
        
