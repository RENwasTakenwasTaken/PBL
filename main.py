from pathlib import Path
import subprocess
import traceback
import time

import numpy as np
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.factory import Factory
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty
from kivy.uix.textinput import TextInput
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.modalview import ModalView
from kivy.uix.label import Label

from reader import SerialValueReader
from waveform import Waveform
from waveform import FFTGraph

KV_PATH = Path(__file__).with_name("main.kv")
LOG_PATH = Path(__file__).with_name("app_error.log")
HEART_DARK = (0.2, 0.2, 0.22, 1)
HEART_BRIGHT = (1, 0.2, 0.2, 1)
SERIAL_BAUDRATE = 115200

class SectionTitle(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

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
        self._update_modal_content = None
        self._log_modal = None
        self._log_modal_content = None
        self._top_waveform = None
        self._bottom_waveform = None
        self._red_label = None
        self._ir_label = None
        self._pleth_label = None
        self._pleth_waveform = None
        self._ir_delta_waveform = None
        self._fft_graph = None

        self.top_waveform = Waveform(
            size_hint_y=1,
            ymin=-200,
            ymax=200,
            fps=60,
            time_window_sec=20,
            autoscale_window_sec=10,
            major_x_ticks=5,
            major_y_ticks=5,
            auto_scale=True,
            max_ymax=35000,
            min_ymin=-35000,
            graph_color=(1, 0.3, 0.3, 1)
        )

        self.bottom_waveform = Waveform(
            size_hint_y=1,
            ymin=-200,
            ymax=200,
            fps=60,
            time_window_sec=20,
            autoscale_window_sec=10,
            major_x_ticks=5,
            major_y_ticks=5,
            auto_scale=True,
            max_ymax=35000,
            min_ymin=-35000,
            graph_color=(1, 0.3, 1, 1)
        )

        self.pleth_waveform = Waveform(
            size_hint_y=1,
            ymin=0,
            ymax=100,
            fps=60,
            time_window_sec=20,
            autoscale_window_sec=10,
            major_x_ticks=5,
            major_y_ticks=5,
            auto_scale=True,
            max_ymax=1200,
            min_ymin=0,
            graph_color=(0, 1, 1, 1)
        )

        self.IR_delta_waveform = Waveform(
            size_hint_y=1,
            ymin=-200,
            ymax=200,
            fps=60,
            time_window_sec=20,
            autoscale_window_sec=10,
            major_x_ticks=5,
            major_y_ticks=5,
            auto_scale=True,
            max_ymax=35000,
            min_ymin=-35000,
            graph_color=(1, 0.8, 0.4, 1)
        )

        self.IR_FFT_waveform = FFTGraph(
            size_hint_y=1,
            max_frequency=25,
            major_x_ticks=4,
            major_y_ticks=4,
            graph_color=(1, 0.8, 0.2, 1)
        )

        self.red_label = SectionTitle(
            text="RED LED (RAW) Readings",
            color=(1, 0, 0, 1)
        )
        self.ir_label = SectionTitle(
            text="IR LED (RAW) Readings",
            color=(1, 0, 1, 1)
        )
        self.pleth_label = SectionTitle(
            text="Plethysmograph (Pleth)",
            color=(0, 1, 1, 1)
        )

        self.IR_delta_label = SectionTitle(
            text="IR (d / dt) Rate-Of-Change Waveform",
            color=(1, 0.8, 0.4, 1)
        )

        self.IR_FFT_Label = SectionTitle(
            text="IR FFT (Harmonics present out of 25Hz)",
            color=(1, 0.8, 0.2, 1)
        )

    def start(self):
        self.ir_delta = 0
        self.prev_ir = 0
        self.extra_waveforms_enabled = False


        self.reader = SerialValueReader(baudrate=SERIAL_BAUDRATE, timeout=1).start()
        self.top_waveform.data_source = self.reader.get_latest_upper_value
        self.bottom_waveform.data_source = self.reader.get_latest_lower_value
        self.pleth_waveform.data_source = self.get_latest_pleth_value
        self.IR_delta_waveform.data_source = self.get_ir_delta_value
        self.status_text = "Searching for serial device..."

        self._events = [
            Clock.schedule_interval(self._guard_callback(self.graph_fps, "graph_fps"), 1 / self.top_waveform.fps),
            Clock.schedule_interval(self._guard_callback(self.graph_updation, "graph_updation"), 1),
            Clock.schedule_interval(self._guard_callback(self.refresh_status, "refresh_status"), 0.2),
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
        if self.extra_waveforms_enabled:
            self.bottom_waveform.update_autoscale()
            self.IR_delta_waveform.update_autoscale()
            self.update_fft_graph()
        else:
            self.top_waveform.update_autoscale()
            self.bottom_waveform.update_autoscale()
            self.pleth_waveform.update_autoscale()
            
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
        
        if not self.extra_waveforms_enabled:
            points = self.pleth_waveform.get_plot_points(portion=1)
            self.spo2 = str(round(self.calculate_array_average_absolute(points)))
            if int(self.spo2) > 100:
                self.spo2 = "100"  # Since spo2 is now a string being assigned to a text label.

    def graph_fps(self, *_args):
        self.top_waveform.update_from_source()
        self.bottom_waveform.update_from_source()
        self.pleth_waveform.update_from_source()
    
        # Activate only when the extra waveform are activated.
        if self.extra_waveforms_enabled:
            self.IR_delta_waveform.update_from_source()

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
                self.IR_FFT_waveform.clear_spectrum()
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
            self.IR_FFT_waveform.clear_spectrum()
            return

        timestamps = np.array([sample_time for sample_time, _ in points], dtype=float)
        values = np.array([value for _, value in points], dtype=float)

        intervals = np.diff(timestamps)
        valid_intervals = intervals[intervals > 0]
        if valid_intervals.size == 0:
            self.IR_FFT_waveform.clear_spectrum()
            return

        sample_rate = 1.0 / float(valid_intervals.mean())
        if sample_rate <= 0:
            self.IR_FFT_waveform.clear_spectrum()
            return

        detrended = values - values.mean()
        if np.allclose(detrended, 0):
            self.IR_FFT_waveform.clear_spectrum()
            return

        window = np.hanning(len(detrended))
        spectrum = np.fft.rfft(detrended * window)
        frequencies = np.fft.rfftfreq(len(detrended), d=1.0 / sample_rate)
        magnitudes = np.abs(spectrum)

        visible_points = [
            (float(frequency), float(magnitude))
            for frequency, magnitude in zip(frequencies, magnitudes)
            if 0.0 <= frequency <= self.IR_FFT_waveform.max_frequency
        ]
        self.IR_FFT_waveform.set_spectrum(visible_points)

    def updateSoftware(self):
        if self._update_modal is not None:
            self._update_modal.dismiss()
        subprocess.run(["git", "pull"])
        App.get_running_app().stop()

    def open_update_modal(self):
        if self._update_modal is None:
            self._update_modal_content = Factory.UpdateModalContent()
            self._update_modal = ModalView(size_hint=(None, None), size=(420, 220), auto_dismiss=True)
            self._update_modal.add_widget(self._update_modal_content)

        self._update_modal.open()

    def close_update_modal(self):
        if self._update_modal is not None:
            self._update_modal.dismiss()

    def open_log_modal(self):
        if self._log_modal is None:
            self._log_modal_content = Factory.LogModalContent()
            self._log_modal = ModalView(size_hint=(0.85, 0.85), auto_dismiss=True)
            self._log_modal.add_widget(self._log_modal_content)

        self._log_modal_content.ids.log_text.text = self.read_log_text()
        self._log_modal.open()

    def close_log_modal(self):
        if self._log_modal is not None:
            self._log_modal.dismiss()

    def remove_fromGraphContainer(self, widget):
        self.ids.graph_container.remove_widget(widget)

    def add_toGraphContainer(self, widget):
        self.ids.graph_container.add_widget(widget)

    def show_normalWaveforms(self):
        self.ids.graph_container.clear_widgets()

        self.add_toGraphContainer(self.red_label)
        self.add_toGraphContainer(self.top_waveform)
        self.add_toGraphContainer(self.ir_label)
        self.add_toGraphContainer(self.bottom_waveform)
        self.add_toGraphContainer(self.pleth_label)
        self.add_toGraphContainer(self.pleth_waveform)

    def show_extraWaveforms(self):
        self.ids.graph_container.clear_widgets()

        self.add_toGraphContainer(self.ir_label)
        self.add_toGraphContainer(self.bottom_waveform)
        self.add_toGraphContainer(self.IR_delta_label)
        self.add_toGraphContainer(self.IR_delta_waveform)
        self.add_toGraphContainer(self.IR_FFT_Label)
        self.add_toGraphContainer(self.IR_FFT_waveform)

    def toggle_extra_waveforms(self):
        self.extra_waveforms_enabled = not self.extra_waveforms_enabled
        if not self.extra_waveforms_enabled:
            self.show_normalWaveforms()
        else:        
            self.show_extraWaveforms()

    def _guard_callback(self, callback, callback_name):
        def guarded(*args, **kwargs):
            try:
                return callback(*args, **kwargs)
            except Exception:
                self.log_exception(f"Unhandled exception in {callback_name}")
                raise

        return guarded

    def log_exception(self, context_message):
        traceback_text = traceback.format_exc()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"\n[{timestamp}] {context_message}\n{traceback_text}\n"
        print(log_entry)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(log_entry)

    def read_log_text(self):
        if not LOG_PATH.exists():
            return "No log entries yet."

        text = LOG_PATH.read_text(encoding="utf-8")
        return text if text.strip() else "No log entries yet."

class WaveformTestApp(App):
    def build(self):
        Window.clearcolor = (0.07, 0.08, 0.1, 1)
        return Builder.load_file(str(KV_PATH))

    def on_start(self):
        self.root.start()

    def on_stop(self):
        if self.root:
            self.root.stop()

    def on_exception(self, exception):
        if self.root:
            self.root.log_exception(f"Kivy exception: {exception}")
        else:
            traceback_text = traceback.format_exc()
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"\n[{timestamp}] Kivy exception before root init: {exception}\n{traceback_text}\n"
            print(log_entry)
            with LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(log_entry)
        return False


if __name__ == "__main__":
    try:
        WaveformTestApp().run()
    except Exception:
        traceback_text = traceback.format_exc()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"\n[{timestamp}] Unhandled application exception\n{traceback_text}\n"
        print(log_entry)
        with LOG_PATH.open("a", encoding="utf-8") as log_file:
            log_file.write(log_entry)
        raise
