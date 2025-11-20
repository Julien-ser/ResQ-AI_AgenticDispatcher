/* ============================================================================
 * ResQ-AI Dispatch Terminal (ESP32 + TFT + XPT2046 Touch)
 * NEW VERSION — 3 PAGE NAVIGATION (RADAR, EMERGENCY, HISTORY)
 *
 * - Page bar at top for navigation
 * - Emergency page ONLY appears when an active incident exists
 * - Cleaned WiFi, fixed URLs, improved JSON detection
 * - History screen lists SEND/HOLD results
 * - Radar → force poll on tap
 * - TFT uses HSPI, Touch uses VSPI
 * ============================================================================
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <ArduinoJson.h>
#include "secrets.h"

#ifndef BACKEND_URL
#define BACKEND_URL "http://localhost:8000"
#endif

// Touchscreen pins (ESP32-2432S028)
#define XPT2046_IRQ 36
#define XPT2046_CS  33
#define TFT_CLK     25
#define TFT_MISO    39
#define TFT_MOSI    32

SPIClass mySPI(VSPI);   // Touchscreen
XPT2046_Touchscreen ts(XPT2046_CS, XPT2046_IRQ);
TFT_eSPI tft = TFT_eSPI();

// Touch calibration
const int16_t TS_MINX = 200, TS_MAXX = 3900;
const int16_t TS_MINY = 200, TS_MAXY = 3900;

int mapTouchX(int16_t x) { return map(x, TS_MINX, TS_MAXX, 0, tft.width()); }
int mapTouchY(int16_t y) { return map(y, TS_MINY, TS_MAXY, 0, tft.height()); }

// Incident object
struct Incident {
  String summary = "";
  String recommendation = "";
  String urgency = "";
  bool active = false;
};
Incident currentIncident;

// History
#define MAX_HISTORY 10
struct DecisionEntry {
  String action;
  String status;
  String message;
  String timestamp;
  String summary;
  String urgency;
  String recommendation;
};
DecisionEntry decisionHistory[MAX_HISTORY];
int decisionHistoryCount = 0;

String lastDecisionStatus = "";

// Pages
enum Page { PAGE_RADAR, PAGE_EMERGENCY, PAGE_HISTORY };
Page currentPage = PAGE_RADAR;

// Top menu button hitboxes
int navRadarX = 0,   navRadarW = 80;
int navEmerX = 80,   navEmerW = 120;
int navHistX = 200,  navHistW = 120;

// Poll timing
unsigned long lastIncidentPoll = 0;
const unsigned long incidentPollInterval = 3000;

bool pointInRect(int tx, int ty, int x, int y, int w, int h) {
  return (tx >= x && tx <= x + w && ty >= y && ty <= y + h);
}

uint16_t getUrgencyColor(String urgency) {
  urgency.toUpperCase();
  if (urgency.indexOf("CRITICAL") >= 0) return TFT_RED;
  if (urgency.indexOf("HIGH") >= 0) return TFT_ORANGE;
  if (urgency.indexOf("MED") >= 0) return TFT_YELLOW;
  if (urgency.indexOf("LOW") >= 0) return TFT_GREEN;
  return TFT_DARKGREY;
}

int drawWrappedText(const String& text, int x, int y, int width, uint8_t textSize, uint16_t color, int maxY = -1) {
  if (text.length() == 0) return y;
  int charWidth = 6 * textSize;
  int lineHeight = 8 * textSize + 2;
  int maxChars = max(1, width / charWidth);
  int start = 0;
  while (start < text.length()) {
    int end = min((int)text.length(), start + maxChars);
    if (end < text.length()) {
      int space = text.lastIndexOf(' ', end);
      if (space > start) end = space;
    }
    String line = text.substring(start, end);
    line.trim();
    tft.setCursor(x, y);
    tft.setTextSize(textSize);
    tft.setTextColor(color, TFT_BLACK);
    tft.print(line);
    y += lineHeight;
    if (maxY > 0 && y > maxY) {
      tft.setCursor(x, y - lineHeight);
      tft.print("...");
      return maxY;
    }
    start = end;
    while (start < text.length() && text.charAt(start) == ' ') start++;
  }
  return y;
}

/* ============================================================================
 * PAGE DRAWING
 * ============================================================================
*/

// Draw top navigation bar
void drawNavBar() {
  tft.fillRect(0, 0, tft.width(), 30, TFT_DARKGREY);

  tft.setTextSize(2);
  tft.setTextColor(TFT_WHITE, TFT_DARKGREY);

  tft.setCursor(10, 6);
  tft.print("RAD");

  tft.setCursor(95, 6);
  tft.print("EMR");

  tft.setCursor(215, 6);
  tft.print("HIS");

  // Highlight active page
  uint16_t highlightColor = TFT_GREEN;
  int hx = (currentPage == PAGE_RADAR ? navRadarX :
           currentPage == PAGE_EMERGENCY ? navEmerX :
           navHistX);

  int hw = (currentPage == PAGE_RADAR ? navRadarW :
           currentPage == PAGE_EMERGENCY ? navEmerW :
           navHistW);

  tft.drawRect(hx, 0, hw, 30, highlightColor);
}

// Radar page
void drawRadarUI() {
  tft.fillScreen(TFT_BLACK);
  drawNavBar();

  tft.setTextColor(TFT_GREEN, TFT_BLACK);
  tft.setTextSize(3);

  tft.setCursor(40, 60);
  tft.print("MONITORING");

  tft.setCursor(40, 100);
  tft.print("CHANNELS...");

  tft.drawCircle(tft.width()/2, tft.height()/2 + 20, 70, TFT_DARKGREEN);
  tft.drawLine(tft.width()/2, tft.height()/2 + 20,
               tft.width()/2 + 70, tft.height()/2 + 20, TFT_DARKGREEN);
}

// Emergency page
void drawEmergencyUI() {
  tft.fillScreen(TFT_BLACK);
  drawNavBar();

  bool hasIncident = currentIncident.active && currentIncident.summary.length() > 0;
  int contentX = 10;
  int contentWidth = tft.width() - 20;
  int cursorY = 40;

  if (hasIncident) {
    uint16_t urgencyColor = getUrgencyColor(currentIncident.urgency);
    tft.fillRoundRect(contentX, cursorY, contentWidth, 34, 6, urgencyColor);
    tft.setTextColor(TFT_BLACK, urgencyColor);
    tft.setTextSize(2);
    tft.setCursor(contentX + 6, cursorY + 8);
    tft.printf("URG: %s", currentIncident.urgency.c_str());
    cursorY += 44;

    tft.setTextSize(1);
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    tft.setCursor(contentX, cursorY);
    tft.print("Summary");
    cursorY += 12;
    cursorY = drawWrappedText(currentIncident.summary, contentX, cursorY, contentWidth, 1, TFT_WHITE, tft.height() - 110);
    cursorY += 4;

    tft.setTextColor(TFT_ORANGE, TFT_BLACK);
    tft.setCursor(contentX, cursorY);
    tft.print("Recommendation");
    cursorY += 12;
    cursorY = drawWrappedText(currentIncident.recommendation, contentX, cursorY, contentWidth, 1, TFT_WHITE, tft.height() - 90);
  } else {
    tft.setTextColor(TFT_CYAN, TFT_BLACK);
    tft.setTextSize(2);
    tft.setCursor(contentX, cursorY + 20);
    tft.print("No active emergencies");
    tft.setCursor(contentX, cursorY + 50);
    tft.setTextSize(1);
    tft.print("Radar will alert when an incident is detected.");
  }

  uint16_t sendColor = hasIncident ? TFT_RED : TFT_DARKGREY;
  uint16_t holdColor = hasIncident ? TFT_BLUE : TFT_DARKGREY;
  uint16_t textColor = hasIncident ? TFT_WHITE : TFT_LIGHTGREY;

  // SEND button
  tft.fillRoundRect(20, tft.height()-60, 100, 40, 6, sendColor);
  tft.setTextColor(textColor, sendColor);
  tft.setCursor(40, tft.height()-48);
  tft.print(hasIncident ? "SEND" : "DISABLED");

  // HOLD button
  tft.fillRoundRect(tft.width()-120, tft.height()-60, 100, 40, 6, holdColor);
  tft.setTextColor(textColor, holdColor);
  tft.setCursor(tft.width()-105, tft.height()-48);
  tft.print(hasIncident ? "HOLD" : "DISABLED");
}

// History page
void drawHistoryUI() {
  tft.fillScreen(TFT_BLACK);
  drawNavBar();

  tft.setTextSize(2);
  tft.setTextColor(TFT_YELLOW);
  tft.setCursor(10, 40);
  tft.print("DECISION HISTORY");

  tft.setTextSize(1);
  tft.setTextColor(TFT_WHITE);

  int y = 70;
  for (int i = decisionHistoryCount - 1; i >= 0; --i) {
    if (y > tft.height() - 20) break; // stop
    tft.setCursor(10, y);
    tft.printf("%s [%s] %s",
      decisionHistory[i].action.c_str(),
      decisionHistory[i].status.c_str(),
      decisionHistory[i].timestamp.substring(11,19).c_str()
    );
    y += 12;

    String summaryLine = decisionHistory[i].summary.length() > 0 ?
                         decisionHistory[i].summary : String("(no summary)");
    int summaryLen = min(30, (int)summaryLine.length());
    summaryLine = summaryLine.substring(0, summaryLen);
    tft.setCursor(12, y);
    tft.printf("• %s", summaryLine.c_str());
    y += 12;

    if (decisionHistory[i].urgency.length() > 0) {
      tft.setCursor(12, y);
      tft.printf("  Urg: %s", decisionHistory[i].urgency.c_str());
      y += 12;
    }

    if (decisionHistory[i].recommendation.length() > 0) {
      int recLen = min(30, (int)decisionHistory[i].recommendation.length());
      String rec = decisionHistory[i].recommendation.substring(0, recLen);
      tft.setCursor(12, y);
      tft.printf("  Rec: %s", rec.c_str());
      y += 12;
    }

    if (decisionHistory[i].message.length() > 0) {
      int msgLen = min(30, (int)decisionHistory[i].message.length());
      String msg = decisionHistory[i].message.substring(0, msgLen);
      tft.setCursor(12, y);
      tft.printf("  Msg: %s", msg.c_str());
      y += 12;
    }

    y += 4;
  }
}

/* ============================================================================
 * BACKEND — INCIDENT POLLING
 * ============================================================================
*/

bool pollIncident() {
  if (WiFi.status() != WL_CONNECTED) return false;

  HTTPClient http;
  String url = String(BACKEND_URL) + "/incident/latest";

  if (!http.begin(url.c_str())) return false;

  int code = http.GET();
  if (code != 200) { http.end(); return false; }

  String payload = http.getString();
  http.end();

  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, payload)) return false;

  String displaySummary = doc["display_summary"].as<String>();

  // Reject null, empty, or Gemini error data
  String normalizedSummary = displaySummary;
  normalizedSummary.toLowerCase();

  if (displaySummary.length() == 0 ||
      normalizedSummary == "null" ||
      normalizedSummary == "none" ||
      normalizedSummary == "undefined" ||
      displaySummary.startsWith("[Gemini error") ||
      displaySummary == "[Gemini API key not set]") {
    currentIncident.active = false;
    return false;
  }

  // Valid incident
  currentIncident.summary        = displaySummary;
  currentIncident.recommendation = doc["recommendation"].as<String>();
  currentIncident.urgency        = doc["urgency"].as<String>();
  currentIncident.active         = true;

  return true;
}

/* ============================================================================
 * DECISION POST
 * ============================================================================
*/

void sendDecision(const char* action) {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(BACKEND_URL) + "/incident/decision";

  if (!http.begin(url.c_str())) return;

  http.addHeader("Content-Type", "application/json");

  String body = "{\"action\":\"" + String(action) + "\"}";
  int code = http.POST(body);
  String resp = http.getString();
  http.end();

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, resp)) return;

  String status = doc["decision_status"].as<String>();
  if (status.length() == 0) {
    status = doc["status"].as<String>();
  }

  String message = doc["decision_message"].as<String>();
  if (message.length() == 0) {
    message = doc["message"].as<String>();
  }

  String timestamp = doc["timestamp"].as<String>();
  if (timestamp.length() == 0) {
    JsonArray trace = doc["trace"].as<JsonArray>();
    if (!trace.isNull() && trace.size() > 0) {
      JsonObject last = trace[trace.size() - 1].as<JsonObject>();
      JsonObject traceMsg = last["message"].as<JsonObject>();
      if (!traceMsg.isNull()) {
        timestamp = traceMsg["timestamp"].as<String>();
      }
    }
  }
  if (timestamp.length() == 0) {
    timestamp = String("1970-01-01T00:00:00");
  }

  String incidentSummary = currentIncident.summary;
  String incidentUrgency = currentIncident.urgency;
  String incidentRecommendation = currentIncident.recommendation;

  DecisionEntry entry;
  entry.action = action;
  entry.status = status;
  entry.message = message;
  entry.timestamp = timestamp;
  entry.summary = incidentSummary;
  entry.urgency = incidentUrgency;
  entry.recommendation = incidentRecommendation;

  if (decisionHistoryCount < MAX_HISTORY) {
    decisionHistory[decisionHistoryCount++] = entry;
  } else {
    for (int i = 1; i < MAX_HISTORY; i++) decisionHistory[i-1] = decisionHistory[i];
    decisionHistory[MAX_HISTORY-1] = entry;
  }
}

/* ============================================================================
 * SETUP
 * ============================================================================
*/

void setup() {
  Serial.begin(115200);

  // Touch
  mySPI.begin(TFT_CLK, TFT_MISO, TFT_MOSI, XPT2046_CS);
  ts.begin(mySPI);
  ts.setRotation(1);

  // Display
  tft.init();
  tft.setRotation(1);

  // WiFi
  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(150);
  WiFi.begin(ssid, password);

  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries < 50) {
    delay(200);
    tries++;
  }

  drawRadarUI();
}

/* ============================================================================
 * LOOP
 * ============================================================================
*/

void loop() {

  // Poll incidents
  if (millis() - lastIncidentPoll > incidentPollInterval) {
    lastIncidentPoll = millis();

    if (pollIncident()) {
      currentPage = PAGE_EMERGENCY;
      drawEmergencyUI();
    }
  }

  // Touch
  if ((ts.tirqTouched() && ts.touched()) || ts.touched()) {
    TS_Point p = ts.getPoint();
    int tx = mapTouchX(p.x);
    int ty = mapTouchY(p.y);

    delay(50);
    while (ts.touched()) delay(5);

    // Navigation bar (always active)
    if (ty < 30) {
      if (pointInRect(tx, ty, navRadarX, 0, navRadarW, 30)) {
        currentPage = PAGE_RADAR;
        drawRadarUI();
      }
      if (pointInRect(tx, ty, navEmerX, 0, navEmerW, 30) && currentIncident.active) {
        currentPage = PAGE_EMERGENCY;
        drawEmergencyUI();
      }
      if (pointInRect(tx, ty, navHistX, 0, navHistW, 30)) {
        currentPage = PAGE_HISTORY;
        drawHistoryUI();
      }
      return;
    }

    // Emergency buttons
    if (currentPage == PAGE_EMERGENCY && currentIncident.active && currentIncident.summary.length() > 0) {
      if (pointInRect(tx, ty, 20, tft.height()-60, 100, 40)) {
        sendDecision("SEND");
        currentIncident.active = false;
        currentPage = PAGE_RADAR;
        drawRadarUI();
      }
      if (pointInRect(tx, ty, tft.width()-120, tft.height()-60, 100, 40)) {
        sendDecision("HOLD");
        currentIncident.active = false;
        currentPage = PAGE_RADAR;
        drawRadarUI();
      }
    }

    // Radar tap = force poll
    if (currentPage == PAGE_RADAR) {
      if (pollIncident()) {
        currentPage = PAGE_EMERGENCY;
        drawEmergencyUI();
      }
    }
  }

  delay(20);
}
