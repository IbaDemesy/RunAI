"""FastAPI : GET /recap/{id}.pdf | .ics | .html, POST /recap/{id}/send, POST /webhooks/resend.
Lancer : uvicorn api:app --port 8009   (PDF_ENGINE=playwright|weasyprint|chrome_cli)"""

import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

import ics_export
import render
import resend_mail
import samples

STATE: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    pw = None
    if os.environ.get("PDF_ENGINE", "playwright") == "playwright":
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        STATE["browser"] = await pw.chromium.launch(executable_path=render.chrome_path() or None)
    yield
    if pw:
        await STATE.pop("browser").close()
        await pw.stop()


app = FastAPI(title="RunAI recap spike", lifespan=lifespan)


def _recap(recap_id: str):
    r = samples.get_recap(recap_id)
    if r is None:
        raise HTTPException(404, f"recap {recap_id} inconnu")
    return r


async def _pdf(r, engine: str) -> tuple[bytes, float]:
    t = time.perf_counter()
    html = render.render_html(r)
    if engine == "playwright":
        pdf = await render.pdf_playwright_async(html, STATE.get("browser"))
    elif engine in render.ENGINES:
        pdf = render.ENGINES[engine](html)
    else:
        raise HTTPException(400, "engine inconnu")
    return pdf, (time.perf_counter() - t) * 1000


@app.get("/recap/{recap_id}.pdf")
async def recap_pdf(recap_id: str, engine: str = Query(default=os.environ.get("PDF_ENGINE", "playwright"))):
    pdf, ms = await _pdf(_recap(recap_id), engine)
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="RunAI_recap_{recap_id}.pdf"', "X-Gen-Ms": f"{ms:.1f}", "X-Engine": engine})


@app.get("/recap/{recap_id}.ics")
def recap_ics(recap_id: str):
    t = time.perf_counter()
    data = ics_export.build_ics(_recap(recap_id))
    ms = (time.perf_counter() - t) * 1000
    return Response(data, media_type="text/calendar; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="RunAI_{recap_id}.ics"', "X-Gen-Ms": f"{ms:.1f}"})


@app.get("/recap/{recap_id}.html", response_class=HTMLResponse)
def recap_html(recap_id: str):
    return render.render_html(_recap(recap_id))


@app.post("/recap/{recap_id}/send")
async def recap_send(recap_id: str, to: str):
    r = _recap(recap_id)
    pdf, _ = await _pdf(r, os.environ.get("PDF_ENGINE", "playwright"))
    return resend_mail.send_recap(r, pdf, ics_export.build_ics(r), to)


@app.post("/webhooks/resend")
async def resend_webhook(request: Request):
    body = await request.body()
    try:
        resend_mail.verify_webhook(body, dict(request.headers))
    except PermissionError as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    return resend_mail.handle_inbound(json.loads(body), samples.get_recap)
