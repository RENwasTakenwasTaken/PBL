#include <Arduino.h>
#line 1 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino"
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

Adafruit_ADS1115 ads;

int16_t red_levels = 0;
int16_t ir_levels = 0;
char serial_buffer[32];

#line 10 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino"
void setup();
#line 19 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino"
void loop();
#line 10 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino"
void setup() {
  pinMode(3, OUTPUT);
  pinMode(4, OUTPUT);

  Serial.begin(115200);
  ads.begin();
  ads.setGain(GAIN_TWO);
}

void loop() {
  digitalWrite(3, HIGH);
  delay(2);
  red_levels = ads.readADC_SingleEnded(0);
  digitalWrite(3, LOW);

  digitalWrite(4, HIGH);
  delay(2);
  ir_levels = ads.readADC_SingleEnded(0);
  digitalWrite(4, LOW);

  sprintf(serial_buffer, "%d,%d", red_levels, ir_levels);
  Serial.println(serial_buffer);
}

