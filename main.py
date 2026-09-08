from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
def root(request: Request):
    lang = request.headers.get("accept-language", "")
    if lang.startswith("et"):
        return RedirectResponse("/ee")
    return RedirectResponse("/en")

@app.get("/ee")
def eesti(request: Request):
    return templates.TemplateResponse(request, "et/index.html", {})

@app.get("/en")
def inglise(request: Request):
    return templates.TemplateResponse(request, "en/index.html", {})