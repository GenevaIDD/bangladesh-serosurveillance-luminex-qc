"""Entry point for the Uvira Luminex QC tool."""

import socket
import threading
import time
import webbrowser

from .app import create_app


def _find_free_port() -> int:
    """Find a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def main():
    port = _find_free_port()
    app = create_app()

    def open_browser():
        time.sleep(1.0)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"Uvira Luminex QC Tool running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to quit.\n")

    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    main()
