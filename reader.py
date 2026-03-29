import argparse
import threading
from time import sleep

import serial
from serial.tools import list_ports


class SerialValueReader:
    def __init__(
        self,
        port=None,
        baudrate=115200,
        timeout=1,
        default_value=0.0,
        reconnect_delay=5.0,
        smoothing_alpha=0.15,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.default_value = float(default_value)
        self.reconnect_delay = float(reconnect_delay)
        self.smoothing_alpha = max(0.0, min(1.0, float(smoothing_alpha)))

        self._serial = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_values = (self.default_value, self.default_value)
        self._raw_values = (self.default_value, self.default_value)
        self._latest_text = ""
        self._last_error = ""
        self._has_signal = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return self

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        if self._serial and self._serial.is_open:
            self._serial.close()

        self._thread = None
        self._serial = None

    def get_latest_value(self):
        with self._lock:
            return self._latest_values[0]

    def get_latest_values(self):
        with self._lock:
            return self._latest_values

    def get_raw_values(self):
        with self._lock:
            return self._raw_values

    def get_latest_upper_value(self):
        with self._lock:
            return self._latest_values[0]

    def get_latest_lower_value(self):
        with self._lock:
            return self._latest_values[1]

    def get_latest_text(self):
        with self._lock:
            return self._latest_text

    def is_connected(self):
        return bool(self._serial and self._serial.is_open)

    def get_last_error(self):
        with self._lock:
            return self._last_error

    def _detect_port(self):
        first_com_port = None
        first_acm_port = None

        for port_info in list_ports.comports():
            device = (port_info.device or "").strip()
            device_upper = device.upper()

            if not first_com_port and device_upper.startswith("COM"):
                first_com_port = device

            if not first_acm_port and "ACM" in device_upper:
                first_acm_port = device

        if first_com_port:
            return first_com_port

        if first_acm_port:
            return first_acm_port

        raise serial.SerialException("No matching serial port found (expected COM* or *ACM*).")

    def _connect(self):
        port = self.port or self._detect_port()
        self._serial = serial.Serial(port, self.baudrate, timeout=self.timeout)
        self.port = port

        with self._lock:
            self._last_error = ""

    def _disconnect(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def _smooth_values(self, values):
        if self.smoothing_alpha <= 0:
            return values

        if not self._has_signal:
            return values

        previous_left, previous_right = self._latest_values
        current_left, current_right = values
        alpha = self.smoothing_alpha

        return (
            previous_left + alpha * (current_left - previous_left),
            previous_right + alpha * (current_right - previous_right),
        )

    def _read_loop(self):
        while not self._stop_event.is_set():
            if not self.is_connected():
                try:
                    self._connect()
                except serial.SerialException as exc:
                    with self._lock:
                        self._last_error = str(exc)
                    self._disconnect()
                    if self._stop_event.wait(self.reconnect_delay):
                        break
                    continue

            try:
                raw = self._serial.readline()
            except serial.SerialException as exc:
                with self._lock:
                    self._last_error = str(exc)
                self._disconnect()
                if self._stop_event.wait(self.reconnect_delay):
                    break
                continue

            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue

            try:
                left_text, right_text = text.split(",", 1)
                values = (float(left_text), float(right_text))
            except ValueError:
                continue

            smoothed_values = self._smooth_values(values)

            with self._lock:
                self._latest_text = text
                self._raw_values = values
                self._latest_values = smoothed_values
                self._has_signal = True

        self._disconnect()


def main():
    parser = argparse.ArgumentParser(description="Read numeric values from a serial port.")
    parser.add_argument("--port", default=None)
    parser.add_argument("--baudrate", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=1)
    parser.add_argument("--rate", type=float, default=20.0, help="Print rate in Hz.")
    parser.add_argument("--smoothing-alpha", type=float, default=0.15)
    args = parser.parse_args()

    reader = SerialValueReader(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        smoothing_alpha=args.smoothing_alpha,
    ).start()

    try:
        delay = 1 / args.rate if args.rate > 0 else 0
        while True:
            print(reader.get_latest_text())
            if delay > 0:
                sleep(delay)
    except KeyboardInterrupt:
        print("Exiting program gracefully")
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
