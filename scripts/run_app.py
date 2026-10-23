import threading
import webview
from gui_server import app

HOST, PORT = "127.0.0.1", 5151


def start_server():
    # use_reloader=False is already required here -- the reloader spawns a
    # second process, which would break both the in-memory job-runner state
    # (jobs.py) and this single-process launch model entirely.
    app.run(host=HOST, port=PORT, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    webview.create_window("Pattern Research", f"http://{HOST}:{PORT}", width=1800, height=900)
    webview.start(debug=True)   # debug=True keeps the right-click Inspect option available