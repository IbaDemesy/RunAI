"""python -m runai.recap [directory]: write the demo HTML, PDF and .ics recap and print timings."""

import sys
import time
from pathlib import Path

from . import demo_recap, render_html, render_ics, render_pdf


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out/recap")
    out.mkdir(parents=True, exist_ok=True)
    recap = demo_recap()
    for ext, render in (("html", lambda r: render_html(r).encode()), ("ics", render_ics), ("pdf", render_pdf)):
        t0 = time.perf_counter()
        data = render(recap)
        ms = (time.perf_counter() - t0) * 1000
        path = out / f"{recap.id}.{ext}"
        path.write_bytes(data)
        print(f"{path}  {len(data) / 1024:.1f} KB  {ms:.1f} ms")


if __name__ == "__main__":
    main()
