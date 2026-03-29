from pathlib import Path
import subprocess
import time

import numpy as np
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView

from reader import SerialValueReader


KV_PATH = Path(__file__).with_name("main.kv")
HEART_DARK = (0.2, 0.2, 0.22, 1)
HEART_BRIGHT = (1, 0.2, 0.2, 1)
SERIAL_BAUDRATE = 115200


class MainLayout(BoxLayout):
    heartbeat_detected = BooleanProperty(False)
    extra_waveforms_enabled = BooleanProperty(False)
    heart_icon_color = ColorProperty(HEART_DARK)
    status_text = StringProperty(f"Connecting to serial port @ {SERIAL_BAUDRATE} baud")
    heartrate_threshold_lower = NumericProperty(0)
    heartrate_threshold_upper = NumericProperty(0)

    spo2 = StringProperty("")
    heartrate = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reader = None
        self._events = []

        self.heartBeat_timer = 0
        self.heartBeat_timer_limit = 10
        self.heartBeat_count = 0
        self.heartbeat_detected_count = 0

        self.ir_delta = 0
        self.prev_ir = 0

        self.ir_delta_successive = 0
        self.ir_delta_successive_count = 0

        self.last_heartbeat_time = 0
        self._extra_waveforms_panel = None
        self._update_modal = None

    @property
    def top_waveform(self):
        return self.ids.top_waveform

    @property
    def bottom_waveform(self):
        return self.ids.bottom_waveform

    @property
    def red_label(self):
        return self.ids.red_label

    @property
    def ir_label(self):
        return self.ids.ir_label

    @property
    def pleth_label(self):
        return self.ids.pleth_label

    @property
    def pleth_waveform(self):
        return self.ids.pleth_waveform

    @property
    def graph_container(self):
        return self.ids.graph_container

    @property
    def ir_delta_waveform(self):
        return self._extra_waveforms_panel.ids.ir_delta_waveform

    @property
    def fft_graph(self):
        return self._extra_waveforms_panel.ids.fft_graph

    def start(self):
        self.ir_delta = 0
        self.prev_ir = 0
        self._ensure_extra_waveforms_panel()
        self.extra_waveforms_enabled = False
        if self._extra_waveforms_panel.parent is not None:
            self._extra_waveforms_panel.parent.remove_widget(self._extra_waveforms_panel)
        self._sync_graph_layout()
        self.reader = SerialValueReader(baudrate=SERIAL_BAUDRATE, timeout=1).start()
        self.top_waveform.data_source = self.reader.get_latest_upper_value
        self.bottom_waveform.data_source = self.reader.get_latest_lower_value
        self.pleth_waveform.data_source = self.get_latest_pleth_value
        self.ir_delta_waveform.data_source = self.get_ir_delta_value
        self.status_text = "Searching for serial device..."

        self._events = [
            Clock.schedule_interval(self.graph_fps, 1 / self.top_waveform.fps),
            Clock.schedule_interval(self.graph_updation, 1),
            Clock.schedule_interval(self.refresh_status, 0.2),
        ]

    def stop(self):
        for event in self._events:
            event.cancel()
        self._events.clear()

        if self.reader:
            self.reader.stop()
            self.reader = None

    def calculate_array_average_absolute(self, points):
        if not points:
            return 0
        return sum(point[1] for point in points) / len(points)

    def graph_updation(self, *_args):
        if self.top_waveform.parent is not None:
            self.top_waveform.update_autoscale()
        self.bottom_waveform.update_autoscale()
        if self.pleth_waveform.parent is not None:
            self.pleth_waveform.update_autoscale()
        if self.extra_waveforms_enabled:
            self.ir_delta_waveform.update_autoscale()
            self.update_fft_graph()

        # --- Heart Rate Detection. ---
        points = self.bottom_waveform.get_plot_points(portion=0.1)
        self.heartrate_threshold_lower = self.calculate_array_average_absolute(points)
        self.heartrate_threshold_upper = self.heartrate_threshold_lower * 1.1

        if self.heartBeat_timer < self.heartBeat_timer_limit:
            self.heartBeat_timer += 1
        else:
            self.heartrate = str(self.heartBeat_count * 6)
            self.heartBeat_count = 0
            self.heartBeat_timer = 0

        # --- Plethysmograph Averaging for SpO2. ---
        if self.pleth_waveform.parent is not None:
            points = self.pleth_waveform.get_plot_points(portion=1)
            self.spo2 = str(round(self.calculate_array_average_absolute(points)))
            if self.spo2 > 100:
                self.spo2 = 100

    def graph_fps(self, *_args):
        if self.top_waveform.parent is not None:
            self.top_waveform.update_from_source()
        self.bottom_waveform.update_from_source()
        if self.pleth_waveform.parent is not None:
            self.pleth_waveform.update_from_source()
        if self.extra_waveforms_enabled:
            self.ir_delta_waveform.update_from_source()

        if not self.reader:
            return

        ir_value = self.reader.get_latest_values()[1]  # Gets the first reading of IR/RED values.

        if self.ir_delta_successive_count < 5:
            
            self.ir_delta += ir_value - self.prev_ir

            self.ir_delta_successive_count += 1

        else:
            self.ir_delta = 0
            self.ir_delta_successive_count = 0

        if self.last_heartbeat_time == 0:
            self.last_heartbeat_time = time.monotonic()

        if self.ir_delta < -10 and time.monotonic() - self.last_heartbeat_time > 0.3:     # Hardcoded as per observation of (d IR / dt waveform).
            if not self.heartbeat_detected:
                self.heartbeat_detected = True
                self.heart_icon_color = HEART_BRIGHT
                self.heartBeat_count += 1
            
            self.ir_delta_successive_count = 5
        else:
            if self.heartbeat_detected:
                self.heartbeat_detected = False
                self.heart_icon_color = HEART_DARK

                self.last_heartbeat_time = time.monotonic()

        self.prev_ir = ir_value

    def refresh_status(self, _dt):
        if not self.reader:
            return

        if not self.reader.is_connected():
            error_text = self.reader.get_last_error() or "No matching serial device found"
            self.status_text = f"{error_text}. Retrying in 5 seconds..."
            self.heartbeat_detected = False
            self.heart_icon_color = HEART_DARK
            if self.extra_waveforms_enabled:
                self.fft_graph.clear_spectrum()
            return

        upper, lower = self.reader.get_latest_values()
        pleth = self.get_latest_pleth_value()
        self.status_text = (
            f"Reading live data from {self.reader.port}: "
            f"top={upper:.0f}, bottom={lower:.0f}, pleth={pleth:.2f}"
        )

    def get_latest_pleth_value(self):
        if not self.reader:
            return 0.0

        red, ir = self.reader.get_latest_values()
        if ir == 0:
            return 0.0

        return (red / ir) * 100

    def get_ir_delta_value(self):
        return self.ir_delta

    def update_fft_graph(self):
        points = self.bottom_waveform.get_last_seconds(4.0)
        if len(points) < 16:
            self.fft_graph.clear_spectrum()
            return

        timestamps = np.array([sample_time for sample_time, _ in points], dtype=float)
        values = np.array([value for _, value in points], dtype=float)

        intervals = np.diff(timestamps)
        valid_intervals = intervals[intervals > 0]
        if valid_intervals.size == 0:
            self.fft_graph.clear_spectrum()
            return

        sample_rate = 1.0 / float(valid_intervals.mean())
        if sample_rate <= 0:
            self.fft_graph.clear_spectrum()
            return

        detrended = values - values.mean()
        if np.allclose(detrended, 0):
            self.fft_graph.clear_spectrum()
            return

        window = np.hanning(len(detrended))
        spectrum = np.fft.rfft(detrended * window)
        frequencies = np.fft.rfftfreq(len(detrended), d=1.0 / sample_rate)
        magnitudes = np.abs(spectrum)

        visible_points = [
            (float(frequency), float(magnitude))
            for frequency, magnitude in zip(frequencies, magnitudes)
            if 0.0 <= frequency <= self.fft_graph.max_frequency
        ]
        self.fft_graph.set_spectrum(visible_points)

    def updateSoftware(self):
        if self._update_modal is not None:
            self._update_modal.dismiss()
        subprocess.run(["git", "pull"])
        App.get_running_app().stop()

    def open_update_modal(self):
        if self._update_modal is None:
            content = Factory.UpdateModalContent()
            self._update_modal = ModalView(size_hint=(None, None), size=(420, 220), auto_dismiss=True)
            self._update_modal.add_widget(content)

        self._update_modal.open()

    def close_update_modal(self):
        if self._update_modal is not None:
            self._update_modal.dismiss()

    def toggle_extra_waveforms(self):
        self._ensure_extra_waveforms_panel()
        self.extra_waveforms_enabled = not self.extra_waveforms_enabled
        if not self.extra_waveforms_enabled:
            self.fft_graph.clear_spectrum()
        self._sync_graph_layout()

    def _ensure_extra_waveforms_panel(self):
        if self._extra_waveforms_panel is None:
            self._extra_waveforms_panel = Factory.ExtraWaveformsPanel()

    def _sync_graph_layout(self):
        widgets = [
            self.red_label,
            self.top_waveform,
            self.ir_label,
            self.bottom_waveform,
            self.pleth_label,
            self.pleth_waveform,
        ]

        for widget in widgets:
            if widget.parent is not None:
                widget.parent.remove_widget(widget)

        if self._extra_waveforms_panel is not None and self._extra_waveforms_panel.parent is not None:
            self._extra_waveforms_panel.parent.remove_widget(self._extra_waveforms_panel)

        ordered_widgets = [
            self.ir_label,
            self.bottom_waveform,
        ]

        if self.extra_waveforms_enabled:
            ordered_widgets.append(self._extra_waveforms_panel)
        else:
            ordered_widgets = [
                self.red_label,
                self.top_waveform,
                self.ir_label,
                self.bottom_waveform,
                self.pleth_label,
                self.pleth_waveform,
            ]

        for widget in ordered_widgets:
            self.graph_container.add_widget(widget, index=0)

class WaveformTestApp(App):
    def build(self):
        Window.clearcolor = (0.07, 0.08, 0.1, 1)
        return Builder.load_file(str(KV_PATH))

    def on_start(self):
        self.root.start()

    def on_stop(self):
        if self.root:
            self.root.stop()


if __name__ == "__main__":
    WaveformTestApp().run()
