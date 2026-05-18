#!/usr/bin/env python3
import argparse
import json
import random
from http.server import BaseHTTPRequestHandler, HTTPServer


class DecisionHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/decide":
            self.send_error(404, "Not found")
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            actions = payload.get("playable_actions", [])
            action_index = random.randrange(len(actions)) if actions else 0
            response = {
                "action_index": action_index,
                "reason": "random local adapter",
            }
            self._send_json(response)
        except Exception as exc:
            self._send_json({"action_index": 0, "error": str(exc)}, status=200)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Local random Catanatron webhook adapter")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), DecisionHandler)
    print(f"Listening on http://{args.host}:{args.port}/decide")
    server.serve_forever()


if __name__ == "__main__":
    main()
