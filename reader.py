import argparse
import threading
from time import sleep

import serial


class SerialValueReader:
    def __init__(self, port="COM11", baudrate=9600, timeout=1, default_value=0.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.default_value = float(default_value)

        self._serial = None
        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_values = (self.default_value, self.default_value)
        self._latest_text = ""

    def start(self):
        if self._thread and self._thread.is_alive():
            return self

        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
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

    def get_latest_upper_value(self):
        with self._lock:
            return self._latest_values[0]

    def get_latest_lower_value(self):
        with self._lock:
            return self._latest_values[1]

    def get_latest_text(self):
        with self._lock:
            return self._latest_text

    def _read_loop(self):
        while not self._stop_event.is_set():
            try:
                raw = self._serial.readline()
            except serial.SerialException:
                break

            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue

            try:
                left_text, right_text = text.split(",", 1)
                values = (float(left_text), float(right_text))
            except ValueError:
                continue

            with self._lock:
                self._latest_text = text
                self._latest_values = values


def main():
    parser = argparse.ArgumentParser(description="Read numeric values from a serial port.")
    parser.add_argument("--port", default="COM11")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--timeout", type=float, default=1)
    parser.add_argument("--rate", type=float, default=20.0, help="Print rate in Hz.")
    args = parser.parse_args()

    reader = SerialValueReader(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
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
