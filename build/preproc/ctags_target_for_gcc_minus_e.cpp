# 1 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino"
# 2 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino" 2
# 3 "c:\\Users\\aryan\\Documents\\All Projects\\Academic\\PICT\\PBL\\spo2sensor.ino" 2

Adafruit_ADS1115 ads;

int16_t red_levels = 0;
int16_t ir_levels = 0;
char serial_buffer[32];

void setup() {
  pinMode(3, 0x1);
  pinMode(4, 0x1);

  Serial.begin(9600);
  ads.begin();
  ads.setGain(GAIN_SIXTEEN);

  delay(5000);
}

void loop() {
  digitalWrite(3, 0x1);
  delay(7);
  red_levels = ads.readADC_SingleEnded(0);
  digitalWrite(3, 0x0);

  digitalWrite(4, 0x1);
  delay(5);
  ir_levels = ads.readADC_SingleEnded(0);
  digitalWrite(4, 0x0);

  sprintf(serial_buffer, "%d,%d", red_levels, ir_levels);
  Serial.println(serial_buffer);
  delay(3);

  // 60Hz capture rate.
}
