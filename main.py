from pathlib import Path
import subprocess

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, ColorProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from reader import SerialValueReader


KV_PATH = Path(__file__).with_name("main.kv")
HEART_DARK = (0.2, 0.2, 0.22, 1)
HEART_BRIGHT = (1, 0.2, 0.2, 1)


class MainLayout(BoxLayout):
    heartbeat_detected = BooleanProperty(False)
    heart_icon_color = ColorProperty(HEART_DARK)
    title_text = StringProperty("SpO2 Waveform Monitor")
    status_text = StringProperty("Connecting to COM11 @ 9600 baud")
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

    @property
    def top_waveform(self):
        return self.ids.top_waveform

    @property
    def bottom_waveform(self):
        return self.ids.bottom_waveform

    @property
    def pleth_waveform(self):
        return self.ids.pleth_waveform

    def start(self):
        try:
            self.reader = SerialValueReader(port="COM11", baudrate=9600, timeout=1).start()
            self.top_waveform.data_source = self.reader.get_latest_upper_value
            self.bottom_waveform.data_source = self.reader.get_latest_lower_value
            self.pleth_waveform.data_source = self.get_latest_pleth_value
            self.status_text = "Reading live data from COM11"
        except Exception as exc:
            self.status_text = f"Serial connection failed: {exc}"
            self.top_waveform.data_source = lambda: 0
            self.bottom_waveform.data_source = lambda: 0
            self.pleth_waveform.data_source = lambda: 0

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
        self.top_waveform.update_autoscale()
        self.bottom_waveform.update_autoscale()
        self.pleth_waveform.update_autoscale()

        # --- Heart Rate Detection. ---
        # - Determine heartrate detection threshold.
        points = self.bottom_waveform.get_plot_points(portion=0.25)
        self.heartrate_threshold_lower = self.calculate_array_average_absolute(points)
        self.heartrate_threshold_upper = self.heartrate_threshold_lower * 1.5

        # - Heart Rate Counter using a counting variable.
        if self.heartBeat_timer < self.heartBeat_timer_limit:
            self.heartBeat_timer += 1
        else:
            # Calculate heartbeats for 1 minute from counts measured in 10 seconds.
            self.heartrate = str(self.heartBeat_count * 6)
            self.heartBeat_count = 0
            self.heartBeat_timer = 0

        # --- Plethysmograph Averaging for SpO2. ---
        points = self.pleth_waveform.get_plot_points(portion=1)
        self.spo2 = str(round(self.calculate_array_average_absolute(points)))

    def graph_fps(self, *_args):
        self.top_waveform.update_from_source()
        self.bottom_waveform.update_from_source()
        self.pleth_waveform.update_from_source()

        if not self.reader:
            return

        ir_value = self.reader.get_latest_values()[1]
        if ir_value < self.heartrate_threshold_lower:
            if not self.heartbeat_detected:
                self.heartbeat_detected = True
                self.heart_icon_color = HEART_BRIGHT

                self.heartBeat_count += 1
        else:
            if self.heartbeat_detected:
                self.heartbeat_detected = False
                self.heart_icon_color = HEART_DARK

    def refresh_status(self, _dt):
        if not self.reader:
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

    def updateSoftware(self):
        subprocess.run(["git", "pull"])
        App.get_running_app().stop()

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
