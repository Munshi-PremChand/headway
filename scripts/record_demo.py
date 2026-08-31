#!/usr/bin/env python3
"""Drive the live demo through a scripted choreography and record it. NO NARRATION.

WHAT THIS IS FOR. Driving a web page smoothly with a mouse while also talking is
the hardest part of recording a demo, and it is the part a machine can do better
than a person. This produces clean, repeatable B-roll of the interface — boxes
animating in, the withheld service being revealed, the two feed cards — as an
MP4 with no audio, at a steady frame rate.

WHAT THIS IS NOT. It has no voice. A narrated take is more persuasive than
captions, so the intended use is: record this, then talk over it. `--captions`
burns the beat text in if you would rather ship it silent, which the rules
permit ("English or English-subtitled").

HOW IT WORKS. Chrome is launched headless with the DevTools Protocol open,
`Page.startScreencast` streams JPEG frames as the page is scrolled and clicked,
and ffmpeg assembles them at a fixed rate. Frames arrive only when the page
changes, so each is stamped with its arrival time and held for the right
duration — otherwise fast sections would race and still sections would vanish.

    python3 scripts/record_demo.py --out out/headway_demo.mp4
    python3 scripts/record_demo.py --captions --fps 24
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LIVE = "https://headway-606499459461.asia-south1.run.app"
CHROME = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
WIDTH, HEIGHT = 1600, 1000


class Chrome:
    """A minimal DevTools Protocol client. No browser-automation dependency."""

    # ONE task reads the socket. An earlier version had `send()` drain messages
    # while waiting for its own reply, which silently ate every
    # `Page.screencastFrame` event and produced a recording with no frames in
    # it. A protocol with interleaved responses and events needs a single
    # reader that dispatches, not two consumers racing.

    def __init__(self, port: int = 9333) -> None:
        self.port = port
        self.proc: subprocess.Popen | None = None
        self.ws = None
        self._id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None
        self.on_frame = None

    def launch(self, profile: Path) -> None:
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--window-size={WIDTH},{HEIGHT}", "--hide-scrollbars",
             "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    async def connect(self) -> None:
        import websockets
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{self.port}/json/list", timeout=2) as r:
                    tabs = json.loads(r.read())
                page = next(t for t in tabs if t.get("type") == "page")
                self.ws = await websockets.connect(
                    page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
                self._reader = asyncio.create_task(self._read_loop())
                return
            except Exception:
                await asyncio.sleep(0.5)
        raise RuntimeError("could not attach to Chrome")

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid is not None:
                    fut = self._pending.pop(mid, None)
                    if fut and not fut.done():
                        fut.set_result(msg)
                elif msg.get("method") == "Page.screencastFrame":
                    p = msg["params"]
                    if self.on_frame:
                        self.on_frame(base64.b64decode(p["data"]))
                    self._id += 1
                    await self.ws.send(json.dumps(
                        {"id": self._id, "method": "Page.screencastAck",
                         "params": {"sessionId": p["sessionId"]}}))
        except Exception:
            return

    async def send(self, method: str, **params):
        self._id += 1
        mid = self._id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method,
                                       "params": params}))
        msg = await asyncio.wait_for(fut, timeout=30)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def js(self, expr: str):
        r = await self.send("Runtime.evaluate", expression=expr,
                            awaitPromise=True, returnByValue=True)
        return (r.get("result") or {}).get("value")

    def close(self) -> None:
        if self.proc:
            self.proc.terminate()


# --------------------------------------------------------------- choreography
#
# (seconds_to_hold, caption, javascript). The javascript runs, then the frame
# stream is held for that long. Timings mirror VIDEO_SCRIPT.md so a narrated
# take lines up with the beats.
SCENES: list[tuple[float, str, str]] = [
    (4.0, "A bus timetable is not data until someone types it in.",
     "window.scrollTo({top:0,behavior:'instant'})"),
    (5.0, "India: 9 active transit feeds. One per 161 million people.",
     "window.scrollTo({top:0,behavior:'smooth'})"),
    (6.0, "Every claim is boxed on the page it came from.",
     "document.querySelector('#jump').scrollIntoView({behavior:'smooth',block:'start'})"),
    (4.0, "The model is asked two things: what a cell says, and where it is.",
     "document.querySelectorAll('.bx')[14].dispatchEvent(new MouseEvent('mouseenter'))"),
    (6.0, "Service 3 runs off the page. Its last row still departs, "
          "so the bus does not stop there.",
     "[...document.querySelectorAll('#jump button')].find(b=>b.textContent"
     ".includes('withheld')).click()"),
    (5.0, "It is withheld, and the reason is on screen.",
     "document.querySelectorAll('.bx.withheld')[3]"
     ".dispatchEvent(new MouseEvent('mouseenter'))"),
    # unplaced[1] is Jagiroad (unplaced[0] is Laluk, whose story is weaker) —
    # the caption names Jagiroad, so the detail panel must show Jagiroad.
    (5.0, "Two stops got no coordinates. The best match for Jagiroad is a "
          "hardware shop 60 km away.",
     "[...document.querySelectorAll('#jump button')].find(b=>b.textContent"
     ".includes('Show all')).click();"
     "document.querySelectorAll('.bx.unplaced')[1]"
     ".dispatchEvent(new MouseEvent('mouseenter'))"),
    (6.0, "One model stage. Five deterministic stages.",
     "document.querySelector('#stages').scrollIntoView({behavior:'smooth',block:'center'})"),
    (5.0, "The timetable audits its own geocoding against the printed km column.",
     "document.querySelector('#refusals').scrollIntoView({behavior:'smooth',block:'center'})"),
    (7.0, "The same page, run two ways. Both feeds pass. Both report zero errors.",
     "document.querySelector('#duel').scrollIntoView({behavior:'smooth',block:'center'})"),
    (7.0, "But one publishes a 409 km service as terminating halfway along. "
          "Zero errors proves conformance, not correctness.",
     "document.querySelector('.punch').scrollIntoView({behavior:'smooth',block:'center'})"),
    (7.0, "Take the text layer away. The baseline reads zero rows. "
          "We read 70 of 70.",
     "document.querySelector('.copytest').scrollIntoView({behavior:'smooth',block:'start'})"),
    (7.0, "And where we break: 4 departures bound one row high — so the "
          "structural rule withholds the service rather than publishing them.",
     "document.querySelectorAll('.crow')[2].scrollIntoView({behavior:'smooth',block:'center'})"),
    (5.0, "Honest limits, on the page.",
     "document.querySelector('footer').scrollIntoView({behavior:'smooth',block:'start'})"),
    # The live run is the Cloud evidence the rules require, so it belongs in the
    # recording rather than being left for a separate take. It sits LAST because
    # the page reloads a couple of seconds after it finishes — as the closing
    # shot that reload is a clean ending; anywhere earlier it would interrupt.
    (4.0, "Now run it live. Nothing below is cached.",
     "document.querySelector('.live').scrollIntoView({behavior:'smooth',block:'center'})"),
    # The log output appears and grows as the run proceeds, which changes the
    # page height and scrolls the panel out of shot. Re-centre it every second
    # so the counter and the log tail stay on camera for the whole run.
    (95.0, "Running on Cloud Run: fetch the PDF, render it, two Gemini models on "
           "Vertex, bind, geocode, compose, and re-run gtfs-validator.",
     "document.querySelector('#gobtn').click();"
     "window.__pin=setInterval(()=>{const l=document.querySelector('.live');"
     "if(l)l.scrollIntoView({block:'center'})},700)"),
]


async def record(args) -> int:
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    frames_dir = ROOT / ".tmp" / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True)

    profile = ROOT / ".tmp" / "chrome-profile"
    if profile.exists():
        shutil.rmtree(profile)
    profile.mkdir(parents=True)

    br = Chrome()
    br.launch(profile)
    try:
        await br.connect()
        await br.send("Page.enable")
        await br.send("Runtime.enable")
        await br.send("Emulation.setDeviceMetricsOverride", width=WIDTH,
                      height=HEIGHT, deviceScaleFactor=1, mobile=False)

        print(f"  loading {args.url}")
        await br.send("Page.navigate", url=args.url)
        await asyncio.sleep(args.settle)

        # Poll `Page.captureScreenshot` rather than subscribe to the screencast.
        # MEASURED: `Page.startScreencast` in headless emits only on compositor
        # commits, and a smooth-scrolled page produced THREE frames in eighty
        # seconds. A screenshot request always returns a frame, so the capture
        # rate is ours to choose instead of the compositor's.
        collected: list[tuple[float, bytes]] = []
        grabbing = asyncio.Event()
        grabbing.set()

        async def grab():
            interval = 1.0 / args.fps
            while grabbing.is_set():
                t0 = time.time()
                try:
                    r = await br.send("Page.captureScreenshot", format="jpeg",
                                      quality=80, optimizeForSpeed=True)
                    collected.append((time.time(),
                                      base64.b64decode(r["data"])))
                except Exception:
                    pass
                await asyncio.sleep(max(0.0, interval - (time.time() - t0)))

        task = asyncio.create_task(grab())
        t_start = time.time()

        for i, (hold, caption, script) in enumerate(SCENES, 1):
            print(f"  scene {i:>2}/{len(SCENES)}  {hold:>4.1f}s  {caption[:58]}")
            try:
                await br.js(script)
            except Exception as exc:                            # noqa: BLE001
                print(f"     (scene script failed: {exc})")
            if i == len(SCENES):
                # The live run finishes in 62-76s but the hold is a 95s cap.
                # End 1.2s after the button reads "Completed" — still inside
                # the 2.2s window before the page reloads and wipes the log —
                # so the video closes on the open publish gate, not a freeze.
                t0 = time.time()
                while time.time() - t0 < hold:
                    try:
                        txt = await br.js(
                            "(document.querySelector('#gobtn')||{})"
                            ".textContent || ''")
                    except Exception:                           # noqa: BLE001
                        txt = ""
                    if str(txt).lower().startswith(("completed", "failed")):
                        print(f"     live run done in {time.time() - t0:.0f}s"
                              f" — {txt}")
                        await asyncio.sleep(1.2)
                        break
                    await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(hold)

        grabbing.clear()
        await asyncio.sleep(0.2)
        task.cancel()
        total = time.time() - t_start
    finally:
        br.close()

    if not collected:
        print("  no frames captured")
        return 1

    # Hold each frame until the next one arrives, so a still section does not
    # collapse to one frame and a busy one does not race past.
    print(f"\n  {len(collected)} raw frames over {total:.1f}s "
          f"— resampling to {args.fps} fps")
    n = int(total * args.fps)
    base = collected[0][0]
    times = [t - base for t, _ in collected]
    idx, out_n = 0, 0
    for k in range(n):
        want = k / args.fps
        while idx + 1 < len(times) and times[idx + 1] <= want:
            idx += 1
        (frames_dir / f"f{k:06d}.jpg").write_bytes(collected[idx][1])
        out_n += 1

    # Every recording triggers the live run, and the live run REWRITES the
    # server's demo data — so a second take films a poisoned page (that is how
    # the first captioned cut got zero-width claim boxes). Encoding both cuts
    # from the one set of frames means there is never a second take.
    plain = ROOT / args.out
    outputs = [(plain, args.captions)]
    if args.both:
        outputs = [(plain, False),
                   (plain.with_name(plain.stem + "_captioned" + plain.suffix),
                    True)]
    for out, cap in outputs:
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-framerate", str(args.fps),
               "-i", str(frames_dir / "f%06d.jpg")]
        if cap:
            cmd += ["-vf", _caption_filter(args.fps)]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
                "-movflags", "+faststart", str(out)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stderr[-1500:])
            return 1
        size = out.stat().st_size
        print(f"\n  wrote {out.relative_to(ROOT)}  "
              f"{size / 1_000_000:.1f} MB  {out_n / args.fps:.1f}s  "
              f"{WIDTH}x{HEIGHT} @ {args.fps}fps"
              + ("  [captions burned in]" if cap else "  [no captions]"))
    print("  NO AUDIO — narrate over the plain cut, or ship the captioned one.")
    return 0


# ffmpeg's drawtext has no font fallback and macOS ships no family called
# "Sans", so the filter must name a real file or it fails the whole encode.
CAPTION_FONTS = ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/Library/Fonts/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc")


def _font_file() -> str | None:
    for f in CAPTION_FONTS:
        if Path(f).exists():
            return f
    return None


def _caption_filter(fps: int) -> str:
    """Burn each scene's caption in over its own interval."""
    font = _font_file()
    fontspec = f"fontfile='{font}':" if font else ""
    parts, t = [], 0.0
    for hold, caption, _ in SCENES:
        text = (caption.replace("\\", "").replace(":", "\\:")
                .replace("'", "").replace(",", "\\,"))
        parts.append(
            f"drawtext={fontspec}text='{text}':fontcolor=white:fontsize=26:"
            f"box=1:boxcolor=black@0.72:boxborderw=14:"
            f"x=(w-text_w)/2:y=h-90:"
            f"enable='between(t,{t:.2f},{t + hold:.2f})'")
        t += hold
    return ",".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=LIVE)
    ap.add_argument("--out", default="out/headway_demo.mp4")
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--settle", type=float, default=4.0,
                    help="seconds to let the page load and animate before recording")
    ap.add_argument("--captions", action="store_true",
                    help="burn the beat text in (for a silent upload)")
    ap.add_argument("--both", action="store_true",
                    help="write the plain AND captioned cut from one take")
    args = ap.parse_args()
    if not Path(CHROME).exists():
        print(f"Chrome not found at {CHROME}")
        return 1
    return asyncio.run(record(args))


if __name__ == "__main__":
    raise SystemExit(main())
