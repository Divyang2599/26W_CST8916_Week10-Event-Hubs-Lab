# CST8916 – Assignment 2: Real-time Stream Analytics Pipeline

**Student:** Divyang  
**Due:** March 30, 2026  
**YouTube Demo:** [ADD YOUR LINK HERE]

---

## Architecture

```
Browser (client.html)
   │  Enriched events: event_type, page, product_id,
   │  deviceType, browser, os, user_id, session_id
   ▼
Flask /track  (app.py — EventHubProducerClient)
   │
   ▼
Azure Event Hubs: clickstream  (2 partitions)
   │
   ├──► Raw Consumer Thread ──► _event_buffer ──► GET /api/events ──► Dashboard (live feed + bar chart)
   │
   └──► Azure Stream Analytics Job: shopstream-analytics
              │
              │  Query 1: Device type breakdown — TumblingWindow(second, 30)
              │  Query 2: Traffic spike detection — TumblingWindow(second, 30)
              │
              ▼
         Azure Event Hubs: analytics-output  (2 partitions)
              │
              └──► Analytics Consumer Thread ──► _analytics_buffer ──► GET /api/analytics
                                                                              │
                                                                              ▼
                                                                   Dashboard Analytics Panel
                                                                   (Device breakdown + Spike detection)
```

---

## Azure Resources

| Resource | Name |
|----------|------|
| Resource Group | `cst8916-week10-rg` |
| Event Hubs Namespace | `shopstream-divyang` |
| Event Hub (raw events) | `clickstream` (2 partitions) |
| Event Hub (analytics) | `analytics-output` (2 partitions) |
| Stream Analytics Job | `shopstream-analytics` |
| App Service | `shopstream-divyang` (Python 3.11, Free F1) |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `EVENT_HUB_CONNECTION_STR` | Primary connection string for Event Hubs namespace |
| `EVENT_HUB_NAME` | `clickstream` |
| `ANALYTICS_HUB_NAME` | `analytics-output` |

---

## Stream Analytics Queries

### Query 1 — Device Type Breakdown
Answers: *"Which device types are most active?"*
- Window: `TumblingWindow(second, 30)` — non-overlapping 30-second buckets
- Groups events by `deviceType` and counts them
- Output: `device_breakdown` records to `analytics-output` hub

### Query 2 — Traffic Spike Detection
Answers: *"Are there traffic spikes?"*
- Window: `TumblingWindow(second, 30)`
- Counts total events per window
- Classifies as `spike` (>10), `elevated` (>5), or `normal` (≤5)
- Output: `spike_detection` records to `analytics-output` hub

---

## Design Decisions

**Event Enrichment:** `deviceType`, `browser`, and `os` are detected client-side in JavaScript using `navigator.userAgent`. The browser has direct access to this information — no server-side lookup needed. This keeps the `/track` endpoint simple and fast.

**Stream Analytics Output → Second Event Hub:** Results are written to a second Event Hub (`analytics-output`) rather than Blob Storage or Azure SQL. This keeps the same real-time pattern as the raw event pipeline. Flask consumes both hubs using the same `EventHubConsumerClient` SDK — consistent, no extra services, no cost.

**Local Device Breakdown Fallback:** The raw event consumer also computes device breakdown locally in `_analytics_buffer` as each event arrives. This means the dashboard shows device data immediately, even before the first 30-second Stream Analytics window closes.

**TumblingWindow(second, 30):** Non-overlapping windows give clean, non-duplicate aggregations every 30 seconds. Suitable for a near-real-time marketing dashboard where fresh data every 30 seconds is acceptable.

**Spike Thresholds:** >10 events/30s = spike, >5 = elevated, ≤5 = normal. Adjustable for production traffic volumes.

**`TIMESTAMP BY EventEnqueuedUtcTime`:** Uses Event Hubs arrival time as the event timestamp. This is reliable because it comes from the infrastructure, not the client — client clocks can be wrong.

---

## Setup Instructions

### Prerequisites
- Python 3.11+
- Azure account
- Azure Event Hubs namespace with two hubs: `clickstream` and `analytics-output`
- Azure Stream Analytics job running with queries above

### Run Locally (Windows)

```powershell
git clone https://github.com/Divyang2599/26W_CST8916_Week10-Event-Hubs-Lab.git
cd 26W_CST8916_Week10-Event-Hubs-Lab
py -m pip install -r requirements.txt

$env:EVENT_HUB_CONNECTION_STR="Endpoint=sb://shopstream-divyang.servicebus.windows.net/;..."
$env:EVENT_HUB_NAME="clickstream"
$env:ANALYTICS_HUB_NAME="analytics-output"

py app.py
```

Open `http://localhost:8000` → store  
Open `http://localhost:8000/dashboard` → live dashboard

### Azure Deployment
Deployed via GitHub Actions CI/CD to Azure App Service.  
Every push to `main` triggers automatic redeployment.

**App Service environment variables:**
- `EVENT_HUB_CONNECTION_STR` — set in Azure Portal → App Service → Environment variables
- `EVENT_HUB_NAME` = `clickstream`
- `ANALYTICS_HUB_NAME` = `analytics-output`

**Startup command:** `gunicorn --bind 0.0.0.0:8000 app:app`

---

## AI Disclosure

GitHub Copilot and Claude (Anthropic) were used to assist with code structure, Stream Analytics query syntax, and JavaScript device detection logic. All code has been reviewed, understood, tested, and is fully explainable by the author.

---

## Cleanup

```bash
az group delete --name cst8916-week10-rg --yes --no-wait
```