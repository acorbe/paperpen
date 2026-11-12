"""Just enough of the Chrome DevTools Protocol to film a page.

The alternative, `--screenshot=<file>` per frame, reloads the page for every
frame and so can only film states that a URL can reach. The reader's note sheet
is not one of those, and the note sheet is the point of the reader, so the demo
drives a live page instead: one browser, one connection, the real JavaScript
called the way the tablet calls it.
"""

from __future__ import annotations

import base64
import json
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import websocket  # websocket-client

CHROME = shutil.which("google-chrome") or shutil.which("chromium") \
    or shutil.which("chromium-browser")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chrome:
    def __init__(self, width: int = 1100, height: int = 760):
        if not CHROME:
            raise SystemExit("no chrome on this machine; the demo needs one to film the page")
        self.width, self.height = width, height
        self.port = free_port()
        self.proc = None
        self.ws = None
        self._id = 0
        self.at = (width / 2, height - 40)   # where the pointer is, and starts

    def __enter__(self) -> "Chrome":
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--hide-scrollbars", "--force-device-scale-factor=1",
             "--disable-lcd-text", "--font-render-hinting=none",
             f"--remote-debugging-port={self.port}", "--remote-allow-origins=*",
             f"--window-size={self.width},{self.height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = self._wait_for_target()
        self.ws = websocket.create_connection(target, timeout=30,
                                              max_size=200 * 1024 * 1024)
        self.call("Page.enable")
        self.call("Runtime.enable")
        # --window-size is the window, and what is left for the page after the
        # window's own furniture is not the number you asked for: 760 came back
        # as 617. The viewport is set outright so every frame is the same size.
        self.call("Emulation.setDeviceMetricsOverride", width=self.width,
                  height=self.height, deviceScaleFactor=1, mobile=False)
        return self

    def __exit__(self, *_) -> None:
        try:
            if self.ws:
                self.ws.close()
        finally:
            if self.proc:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()

    def _wait_for_target(self, timeout: float = 25.0) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list") as r:
                    for t in json.load(r):
                        if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                            return t["webSocketDebuggerUrl"]
            except (urllib.error.URLError, OSError, ValueError):
                pass
            time.sleep(0.2)
        raise SystemExit("chrome never offered a page to drive")

    def call(self, method: str, **params):
        self._id += 1
        mine = self._id
        self.ws.send(json.dumps({"id": mine, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            # A confirm() stops the page dead, and the call that opened it never
            # comes back: the answer has to be given from out here. The reader
            # asks before sending a round and before letting go of something
            # written but not kept, and in the film the answer to both is yes.
            if message.get("method") == "Page.javascriptDialogOpening":
                self._id += 1
                self.ws.send(json.dumps({"id": self._id,
                                         "method": "Page.handleJavaScriptDialog",
                                         "params": {"accept": True}}))
                continue
            if message.get("id") != mine:
                continue  # an event, or the answer to the dialog
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error'].get('message')}")
            return message.get("result", {})

    def js(self, expression: str):
        """Evaluate in the page and hand back a plain value."""
        result = self.call("Runtime.evaluate", expression=expression,
                           returnByValue=True, awaitPromise=True)
        if result.get("exceptionDetails"):
            raise RuntimeError(f"{expression[:60]}: "
                               f"{result['exceptionDetails'].get('text')}")
        return result["result"].get("value")

    def goto(self, url: str, ready: str = "true", timeout: float = 30.0) -> None:
        self.call("Page.navigate", url=url)
        self.until(f"document.readyState === 'complete' && ({ready})", timeout)

    def until(self, expression: str, timeout: float = 20.0, every: float = 0.15) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(f"!!({expression})"):
                    return
            except RuntimeError:
                pass  # the page may still be swapping documents
            time.sleep(every)
        raise SystemExit(f"gave up waiting for: {expression}")

    def settle(self, seconds: float = 0.35) -> None:
        """Let a transition finish before the shutter."""
        time.sleep(seconds)

    def shot(self) -> bytes:
        return base64.b64decode(self.call("Page.captureScreenshot")["data"])

    # --- the mouse --------------------------------------------------------
    #
    # The pointer is real: every position below is dispatched to the page, so
    # the page hovers, highlights and clicks the way it does under a hand. What
    # the film draws on top of the frame is only a picture of where the pointer
    # already was, which is why `at` is worth keeping.

    def move(self, x: float, y: float) -> tuple[float, float]:
        self.call("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y,
                  button="none", buttons=0, pointerType="mouse")
        self.at = (x, y)
        return self.at

    def glide(self, to: tuple[float, float], steps: int = 6):
        """Travel to a point, reporting where the pointer is at each step.

        Eased at both ends, because a hand does not start and stop at speed,
        and a cursor that crosses the screen at a constant rate is the one
        thing on it that looks drawn.
        """
        x0, y0 = self.at
        x1, y1 = to
        for i in range(1, steps + 1):
            t = i / steps
            ease = 3 * t * t - 2 * t * t * t
            yield self.move(x0 + (x1 - x0) * ease, y0 + (y1 - y0) * ease)

    def click(self, x: float | None = None, y: float | None = None) -> None:
        x, y = (self.at if x is None else (x, y))
        self.move(x, y)
        for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
            self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                      button="left", buttons=buttons, clickCount=1,
                      pointerType="mouse")

    def dblclick(self, x: float | None = None, y: float | None = None) -> None:
        """Two clicks where a double click is what the page listens for: the
        second press carries clickCount 2, which is what makes Chrome send a
        dblclick rather than two clicks."""
        x, y = (self.at if x is None else (x, y))
        self.move(x, y)
        for count in (1, 2):
            for kind, buttons in (("mousePressed", 1), ("mouseReleased", 0)):
                self.call("Input.dispatchMouseEvent", type=kind, x=x, y=y,
                          button="left", buttons=buttons, clickCount=count,
                          pointerType="mouse")

    def type(self, text: str) -> None:
        """Type into whatever has the focus, as a keyboard would: the page sees
        an input event per piece, so an editor repaints as it is typed in."""
        self.call("Input.insertText", text=text)

    def where(self, selector: str) -> tuple[float, float]:
        """The middle of an element, in the page's own coordinates."""
        box = self.js("(() => { const e = document.querySelector(%s);"
                      " if (!e) return null; const b = e.getBoundingClientRect();"
                      " return [b.left + b.width / 2, b.top + b.height / 2]; })()"
                      % json.dumps(selector))
        if not box:
            raise SystemExit(f"nothing to point at: {selector}")
        return (box[0], box[1])

    # --- the pen ----------------------------------------------------------

    def pen(self, strokes, at=(0.0, 0.0)) -> int:
        """Write `strokes` with a stylus, one pen-down to pen-up per stroke.

        The page is told `pointerType: "pen"`, which is what a stylus sends and
        what the reader keys its whole pen behaviour on: a finger moves the
        paper and only a pen writes on it. So the handwriting in the film is
        made the way handwriting is made, by a pen moving over the glass, and
        the strokes the note keeps are the ones the page worked out from these
        events rather than a drawing handed to it.
        """
        points = 0
        for stroke in strokes:
            if not stroke:
                continue
            moves = [("mousePressed", 1)] + [("mouseMoved", 1)] * (len(stroke) - 1)
            for (kind, buttons), (x, y) in zip(moves, stroke):
                self.call("Input.dispatchMouseEvent", type=kind,
                          x=at[0] + x, y=at[1] + y, button="left", buttons=buttons,
                          clickCount=1, pointerType="pen", force=0.55)
                points += 1
            self.call("Input.dispatchMouseEvent", type="mouseReleased",
                      x=at[0] + stroke[-1][0], y=at[1] + stroke[-1][1],
                      button="left", buttons=0, clickCount=1, pointerType="pen")
        return points
