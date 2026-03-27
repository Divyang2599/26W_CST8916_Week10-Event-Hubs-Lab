
# CST8916 – Week 10 Lab + Assignment 2: Clickstream Analytics with Azure Event Hubs
#
# PRODUCER  – receives click events from browser and sends them to Azure Event Hubs
# CONSUMER  – reads raw events from Event Hubs (clickstream hub)
# ANALYTICS – reads Stream Analytics output from Event Hubs (analytics-output hub)
#
# Routes:
#   GET  /              → serves the demo e-commerce store (client.html)
#   POST /track         → receives a click event and publishes it to Event Hubs
#   GET  /dashboard     → serves the live analytics dashboard (dashboard.html)
#   GET  /api/events    → returns recent raw events as JSON
#   GET  /api/analytics → returns Stream Analytics results as JSON

import os
import json
import threading
from datetime import datetime, timezone
from collections import defaultdict

from flask import Flask, jsonify, request, send_from_directory, abort
from flask_cors import CORS

from azure.eventhub import EventHubProducerClient, EventHubConsumerClient, EventData

app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# ---------------------------------------------------------------------------
# Configuration – read from environment variables
# ---------------------------------------------------------------------------
CONNECTION_STR    = os.environ.get("EVENT_HUB_CONNECTION_STR", "")
EVENT_HUB_NAME    = os.environ.get("EVENT_HUB_NAME", "clickstream")
ANALYTICS_HUB_NAME = os.environ.get("ANALYTICS_HUB_NAME", "analytics-output")

# ---------------------------------------------------------------------------
# Raw event buffer – stores last 50 click events
# ---------------------------------------------------------------------------
_event_buffer = []
_buffer_lock  = threading.Lock()
MAX_BUFFER    = 50

# ---------------------------------------------------------------------------
# Analytics buffer – stores Stream Analytics output
# Device breakdown computed locally as fallback + from Stream Analytics
# ---------------------------------------------------------------------------
_analytics_buffer = {
    "device_breakdown": {},
    "spike_detection": {
        "traffic_level": "normal",
        "total_events":  0,
        "window_end":    ""
    }
}
_analytics_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helper – send a single event dict to Azure Event Hubs
# ---------------------------------------------------------------------------
def send_to_event_hubs(event_dict: dict):
    if not CONNECTION_STR:
        app.logger.warning("EVENT_HUB_CONNECTION_STR not set – skipping publish")
        return

    producer = EventHubProducerClient.from_connection_string(
        conn_str=CONNECTION_STR,
        eventhub_name=EVENT_HUB_NAME,
    )
    with producer:
        event_batch = producer.create_batch()
        event_batch.add(EventData(json.dumps(event_dict)))
        producer.send_batch(event_batch)


# ---------------------------------------------------------------------------
# Raw event consumer callback
# ---------------------------------------------------------------------------
def _on_event(partition_context, event):
    """Called for each raw click event from the clickstream hub."""
    body = event.body_as_str(encoding="UTF-8")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body}

    with _buffer_lock:
        _event_buffer.append(data)
        if len(_event_buffer) > MAX_BUFFER:
            _event_buffer.pop(0)

        # Update device breakdown locally from raw events as fallback
        # This ensures device breakdown works even before Stream Analytics window closes
        device = data.get("deviceType", "unknown")
        with _analytics_lock:
            _analytics_buffer["device_breakdown"][device] = \
                _analytics_buffer["device_breakdown"].get(device, 0) + 1

    partition_context.update_checkpoint(event)


# ---------------------------------------------------------------------------
# Stream Analytics output consumer callback
# ---------------------------------------------------------------------------
def _on_analytics_event(partition_context, event):
    """Called for each Stream Analytics result from the analytics-output hub."""
    body = event.body_as_str(encoding="UTF-8")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return

    query_type = data.get("query_type")

    with _analytics_lock:
        if query_type == "device_breakdown":
            device = data.get("deviceType", "unknown")
            _analytics_buffer["device_breakdown"][device] = data.get("event_count", 0)

        elif query_type == "spike_detection":
            _analytics_buffer["spike_detection"] = {
                "traffic_level": data.get("traffic_level", "normal"),
                "total_events":  data.get("total_events", 0),
                "window_end":    data.get("window_end", "")
            }

    partition_context.update_checkpoint(event)


# ---------------------------------------------------------------------------
# Start raw event consumer thread
# ---------------------------------------------------------------------------
def start_consumer():
    if not CONNECTION_STR:
        app.logger.warning("EVENT_HUB_CONNECTION_STR not set – consumer not started")
        return

    consumer = EventHubConsumerClient.from_connection_string(
        conn_str=CONNECTION_STR,
        consumer_group="$Default",
        eventhub_name=EVENT_HUB_NAME,
    )

    def run():
        with consumer:
            consumer.receive(
                on_event=_on_event,
                starting_position="-1",
            )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    app.logger.info("Raw event consumer thread started")


# ---------------------------------------------------------------------------
# Start Stream Analytics output consumer thread
# ---------------------------------------------------------------------------
def start_analytics_consumer():
    if not CONNECTION_STR:
        app.logger.warning("EVENT_HUB_CONNECTION_STR not set – analytics consumer not started")
        return

    consumer = EventHubConsumerClient.from_connection_string(
        conn_str=CONNECTION_STR,
        consumer_group="$Default",
        eventhub_name=ANALYTICS_HUB_NAME,
    )

    def run():
        with consumer:
            consumer.receive(
                on_event=_on_analytics_event,
                starting_position="-1",
            )

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    app.logger.info("Analytics consumer thread started")


# ---------------------------------------------------------------------------
# Start both consumers immediately (works under both Gunicorn and python app.py)
# ---------------------------------------------------------------------------
start_consumer()
start_analytics_consumer()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("templates", "client.html")


@app.route("/dashboard")
def dashboard():
    return send_from_directory("templates", "dashboard.html")


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route("/track", methods=["POST"])
def track():
    """Receive enriched click event from browser and publish to Event Hubs."""
    if not request.json:
        abort(400)

    event = {
        "event_type": request.json.get("event_type", "unknown"),
        "page":       request.json.get("page", "/"),
        "product_id": request.json.get("product_id"),
        "user_id":    request.json.get("user_id", "anonymous"),
        "session_id": request.json.get("session_id", ""),
        "deviceType": request.json.get("deviceType", "unknown"),
        "browser":    request.json.get("browser", "unknown"),
        "os":         request.json.get("os", "unknown"),
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }

    send_to_event_hubs(event)

    # Also buffer locally so dashboard works immediately
    with _buffer_lock:
        _event_buffer.append(event)
        if len(_event_buffer) > MAX_BUFFER:
            _event_buffer.pop(0)

    return jsonify({"status": "ok", "event": event}), 201


@app.route("/api/events", methods=["GET"])
def get_events():
    """Return recent raw events as JSON. Polled by dashboard every 2 seconds."""
    try:
        limit = min(int(request.args.get("limit", 20)), MAX_BUFFER)
    except ValueError:
        limit = 20

    with _buffer_lock:
        recent = list(_event_buffer[-limit:])

    summary = {}
    for e in recent:
        et = e.get("event_type", "unknown")
        summary[et] = summary.get(et, 0) + 1

    return jsonify({"events": recent, "summary": summary, "total": len(recent)}), 200


@app.route("/api/analytics", methods=["GET"])
def get_analytics():
    """Return Stream Analytics results to the dashboard."""
    with _analytics_lock:
        data = {
            "device_breakdown": dict(_analytics_buffer["device_breakdown"]),
            "spike_detection":  dict(_analytics_buffer["spike_detection"])
        }
    return jsonify(data), 200


# ---------------------------------------------------------------------------
# Entry point (local development only — Gunicorn uses start_consumer above)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8000)