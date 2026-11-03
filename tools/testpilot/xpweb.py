"""Client for X-Plane 12's local web API (measurement tool, not the plugin).

Reference: https://developer.x-plane.com/article/x-plane-web-api/ and
https://developer.x-plane.com/article/flight-initialization-api/ (read
2026-11-02). X-Plane 12.4.3 serves v1-v3 on localhost:8086.

Two channels, as Laminar recommends:

- REST (`XPlaneWebAPI`) for lookups, one-off reads and writes, commands, and
  starting a flight (`POST /api/v3/flight`, v3 only). REST requests take
  ~50 ms each in practice (X-Plane appears to serve them once per frame), so
  they are not for control loops.
- WebSocket (`XPlaneStream`) for control: subscribed datarefs are pushed at
  ~10 Hz (only changed values), and writes are fire-and-forget messages. A
  background thread keeps the latest value of every subscribed dataref.

Dataref and command ids change between X-Plane sessions; they are looked up by
name every run. Requires the `websockets` package (development only).

License: GPL-3.0-or-later.
"""

import http.client
import itertools
import json
import threading
import time
import urllib.parse

HOST = "127.0.0.1"  # "localhost" may try IPv6 first; X-Plane listens on IPv4
PORT = 8086


class XPlaneWebAPI:
    """REST client with one persistent connection."""

    def __init__(self, host=HOST, port=PORT, timeout=5.0):
        self._conn = http.client.HTTPConnection(host, port, timeout=timeout)
        self._ids = {}

    def _request(self, method, path, body=None):
        payload = None if body is None else json.dumps(body)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        for attempt in (0, 1):
            try:
                self._conn.request(method, path, body=payload, headers=headers)
                resp = self._conn.getresponse()
                data = resp.read()
                break
            except (http.client.HTTPException, OSError):
                # X-Plane closes idle connections now and then: reconnect once.
                self._conn.close()
                if attempt:
                    raise
        if resp.status >= 400:
            raise RuntimeError(f"{method} {path} -> HTTP {resp.status}: {data[:300]!r}")
        return json.loads(data) if data else None

    def _lookup(self, kind, name):
        key = (kind, name)
        if key not in self._ids:
            query = urllib.parse.quote("filter[name]") + "=" + urllib.parse.quote(name, safe="")
            found = self._request("GET", f"/api/v3/{kind}?{query}")["data"]
            if not found:
                raise KeyError(f"{kind[:-1]} not found: {name}")
            self._ids[key] = found[0]["id"]
        return self._ids[key]

    def dataref_id(self, name):
        return self._lookup("datarefs", name)

    def command_id(self, name):
        return self._lookup("commands", name)

    def get(self, name):
        return self._request("GET", f"/api/v3/datarefs/{self.dataref_id(name)}/value")["data"]

    def set(self, name, value):
        self._request("PATCH", f"/api/v3/datarefs/{self.dataref_id(name)}/value", {"data": value})

    def command(self, name, duration=0.0):
        """Fire a command once (REST allows durations up to 10 s)."""
        self._request("POST", f"/api/v3/command/{self.command_id(name)}/activate",
                      {"duration": duration})

    def start_flight(self, init):
        """Start a new flight from a Flight Initialization API structure."""
        return self._request("POST", "/api/v3/flight", {"data": init})

    def update_flight(self, changes):
        """Change time or weather of the current flight (not aircraft or position)."""
        return self._request("PATCH", "/api/v3/flight", {"data": changes})


class XPlaneStream:
    """WebSocket session: subscribe to datarefs, read latest values, write values."""

    def __init__(self, api, names, host=HOST, port=PORT):
        from websockets.sync.client import connect  # development-only dependency

        self.api = api
        self._ws = connect(f"ws://{host}:{port}/api/v3", open_timeout=5)
        self._req = itertools.count(1)
        self._lock = threading.Lock()
        self._values = {}
        self._errors = []
        self.last_update = 0.0
        self.updates = 0
        self._name_of = {}
        ids = []
        for name in names:
            i = api.dataref_id(name)
            self._name_of[str(i)] = name
            ids.append({"id": i})
        self._closed = False
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._send("dataref_subscribe_values", {"datarefs": ids})

    def _send(self, kind, params):
        self._ws.send(json.dumps({"req_id": next(self._req), "type": kind, "params": params}))

    def _read_loop(self):
        while not self._closed:
            try:
                msg = json.loads(self._ws.recv())
            except Exception:  # connection closed or broken
                break
            if msg.get("type") == "dataref_update_values":
                with self._lock:
                    for key, value in msg["data"].items():
                        name = self._name_of.get(key.strip())
                        if name is not None:
                            self._values[name] = value
                    self.last_update = time.monotonic()
                    self.updates += 1
            elif msg.get("type") == "result" and not msg.get("success", True):
                with self._lock:
                    self._errors.append(msg)

    def wait_for(self, names, timeout=5.0):
        """Block until every name has a value (the first push sends them all)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            with self._lock:
                if all(n in self._values for n in names):
                    return
            time.sleep(0.01)
        raise TimeoutError("no values from X-Plane; is a flight loaded?")

    def snapshot(self):
        with self._lock:
            return dict(self._values), self.last_update

    def errors(self):
        with self._lock:
            errs, self._errors = self._errors, []
            return errs

    def set_many(self, values):
        """Write {name: value} in one message (fire-and-forget; errors via errors())."""
        self._send("dataref_set_values", {"datarefs": [
            {"id": self.api.dataref_id(name), "value": value} for name, value in values.items()]})

    def close(self):
        self._closed = True
        try:
            self._ws.close()
        except Exception:
            pass
