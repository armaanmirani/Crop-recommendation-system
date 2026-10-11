"""Start the local app and open a browser only after the server is ready."""
import json
import os
import threading
import time
import urllib.request
import webbrowser
from app import app, bundle


def open_when_ready(url):
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                health = json.load(response)
            if health.get("status") == "ready" and set(health.get("models", [])) == {"random_forest", "xgboost"}:
                webbrowser.open(url)
                return
        except (OSError, ValueError):
            pass
        time.sleep(.5)


if __name__ == "__main__":
    bundle()
    port = int(os.environ.get("PORT", "5000"))
    url = f"http://localhost:{port}"
    print(f"Terra is starting. Open {url} and keep this window open.")
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    app.run(host="127.0.0.1", port=port, debug=False)
