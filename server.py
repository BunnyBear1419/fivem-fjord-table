from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8080"))

if __name__ == "__main__":
    print(f"FiveM Crafting Directory serving on {HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), SimpleHTTPRequestHandler).serve_forever()
