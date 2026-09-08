import secrets
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DB_PATH = Path(__file__).parent / "annikse.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _hooaeg_aasta(mmdd_start: str, mmdd_end: str) -> tuple[str, str]:
    """Tagastab hooaja alguse ja lõpu käesolevale (või järgmisele) aastale."""
    today = date.today()
    y = today.year
    start, end = f"{y}-{mmdd_start}", f"{y}-{mmdd_end}"
    if today.isoformat() > end:
        y += 1
        start, end = f"{y}-{mmdd_start}", f"{y}-{mmdd_end}"
    return start, end


def _vaike_maja_ctx() -> dict:
    """Ehitab /ee/majutus/vaike-maja template konteksti põhiosa."""
    db = get_db()
    season_start, season_end = _hooaeg_aasta("04-01", "09-30")
    today_str = date.today().isoformat()
    saun = db.execute("SELECT id FROM accommodations WHERE slug='saun'").fetchone()
    saun_hind_euro = None
    if saun:
        rule = db.execute(
            "SELECT price_per_night FROM pricing_rules "
            "WHERE accommodation_id=? AND date_from<=? AND date_to>=? "
            "ORDER BY date_from DESC LIMIT 1",
            (saun["id"], today_str, today_str),
        ).fetchone()
        if rule:
            saun_hind_euro = rule["price_per_night"] // 100
    db.close()
    return {
        "season_start": season_start,
        "season_end": season_end,
        "saun_hind_euro": saun_hind_euro,
        "viga": None,
        "form_data": {},
    }


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


@app.get("/ee/majutus/vaike-maja")
def vaike_maja(request: Request, viga: str = None):
    ctx = _vaike_maja_ctx()
    ctx["viga"] = viga
    return templates.TemplateResponse(request, "et/majutus/vaike-maja.html", ctx)


@app.post("/api/hind")
async def arvuta_hind(request: Request):
    """HTMX endpoint: tagastab live hinna HTML fragmendina."""
    form = await request.form()
    saabub_str = form.get("saabub", "").strip()
    lahkub_str = form.get("lahkub", "").strip()
    saun = form.get("saun") == "1"
    accommodation_id = int(form.get("accommodation_id", "1"))

    if not saabub_str or not lahkub_str:
        return HTMLResponse("")

    try:
        saabub = date.fromisoformat(saabub_str)
        lahkub = date.fromisoformat(lahkub_str)
    except ValueError:
        return HTMLResponse("")

    if lahkub <= saabub:
        return HTMLResponse('<p class="hind-viga">Lahkumise kuupäev peab olema hiljem.</p>')

    oid = (lahkub - saabub).days
    db = get_db()

    rule = db.execute(
        "SELECT price_per_night FROM pricing_rules "
        "WHERE accommodation_id=? AND date_from<=? AND date_to>=? "
        "ORDER BY date_from DESC LIMIT 1",
        (accommodation_id, saabub_str, saabub_str),
    ).fetchone()

    if not rule:
        db.close()
        return HTMLResponse('<p class="hind-puudub">Hind selgub kinnitusel.</p>')

    majutus_sendid = rule["price_per_night"] * oid
    saun_sendid = 0

    if saun:
        saun_rule = db.execute(
            "SELECT pr.price_per_night FROM pricing_rules pr "
            "JOIN accommodations a ON a.id=pr.accommodation_id "
            "WHERE a.slug='saun' AND pr.date_from<=? AND pr.date_to>=? "
            "ORDER BY pr.date_from DESC LIMIT 1",
            (saabub_str, saabub_str),
        ).fetchone()
        if saun_rule:
            saun_sendid = saun_rule["price_per_night"]

    db.close()
    kokku = majutus_sendid + saun_sendid

    def e(s):
        return f"{s // 100} €"

    oo = "öö" if oid == 1 else "ööd"
    html = (
        '<div class="hind-breakdown">'
        f'<div class="hind-rida"><span>{e(rule["price_per_night"])} × {oid} {oo}</span>'
        f"<span>{e(majutus_sendid)}</span></div>"
    )
    if saun and saun_sendid:
        html += f'<div class="hind-rida"><span>Saun</span><span>{e(saun_sendid)}</span></div>'
    html += f'<div class="hind-kokku"><span>Kokku</span><span>{e(kokku)}</span></div></div>'
    return HTMLResponse(html)


@app.post("/ee/broneeri")
async def broneeri(request: Request):
    form = await request.form()
    accommodation_id = int(form.get("accommodation_id", "1"))
    saabub_str = form.get("saabub", "").strip()
    lahkub_str = form.get("lahkub", "").strip()
    guest_count_str = form.get("guest_count", "").strip()
    guest_name = form.get("guest_name", "").strip()
    guest_email = form.get("guest_email", "").strip()
    guest_phone = form.get("guest_phone", "").strip()
    saun = form.get("saun") == "1"

    # Valideeri sisend
    viga = None
    saabub = lahkub = None
    if not saabub_str or not lahkub_str:
        viga = "Palun vali saabumise ja lahkumise kuupäev."
    elif not guest_name or not guest_email or not guest_phone:
        viga = "Palun täida kõik kontaktiväljad."
    else:
        try:
            saabub = date.fromisoformat(saabub_str)
            lahkub = date.fromisoformat(lahkub_str)
            if lahkub <= saabub:
                viga = "Lahkumise kuupäev peab olema hiljem kui saabumise kuupäev."
        except ValueError:
            viga = "Vigased kuupäevad."

    if viga:
        ctx = _vaike_maja_ctx()
        ctx.update({"viga": viga, "form_data": dict(form)})
        return templates.TemplateResponse(
            request, "et/majutus/vaike-maja.html", ctx, status_code=422
        )

    # Saadavuse kontroll (vt annikse-broneerimine.md p 4)
    db = get_db()
    conflict = db.execute(
        "SELECT 1 FROM bookings "
        "WHERE accommodation_id=? AND status IN ('ootel','kinnitatud','makstud') "
        "AND start_date < ? AND end_date > ?",
        (accommodation_id, lahkub_str, saabub_str),
    ).fetchone()
    if conflict:
        db.close()
        return RedirectResponse(
            f"/ee/majutus/vaike-maja?viga={quote('Need kuupäevad on juba broneeritud.')}",
            status_code=303,
        )

    # Arvuta koguhind
    oid = (lahkub - saabub).days
    rule = db.execute(
        "SELECT price_per_night FROM pricing_rules "
        "WHERE accommodation_id=? AND date_from<=? AND date_to>=? "
        "ORDER BY date_from DESC LIMIT 1",
        (accommodation_id, saabub_str, saabub_str),
    ).fetchone()
    majutus_sendid = (rule["price_per_night"] * oid) if rule else 0

    saun_id = None
    saun_sendid = 0
    if saun:
        saun_row = db.execute("SELECT id FROM accommodations WHERE slug='saun'").fetchone()
        if saun_row:
            saun_id = saun_row["id"]
            saun_rule = db.execute(
                "SELECT price_per_night FROM pricing_rules "
                "WHERE accommodation_id=? AND date_from<=? AND date_to>=? "
                "ORDER BY date_from DESC LIMIT 1",
                (saun_id, saabub_str, saabub_str),
            ).fetchone()
            if saun_rule:
                saun_sendid = saun_rule["price_per_night"]

    total_price = majutus_sendid + saun_sendid
    guest_count = int(guest_count_str) if guest_count_str.isdigit() else None
    token = secrets.token_urlsafe(8)

    cursor = db.execute(
        "INSERT INTO bookings "
        "(accommodation_id, start_date, end_date, guest_count, "
        " guest_name, guest_email, guest_phone, status, source, total_price, access_token) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'ootel', 'sait', ?, ?)",
        (
            accommodation_id, saabub_str, lahkub_str, guest_count,
            guest_name, guest_email, guest_phone, total_price, token,
        ),
    )
    if saun and saun_id:
        db.execute(
            "INSERT INTO booking_addons (booking_id, accommodation_id) VALUES (?, ?)",
            (cursor.lastrowid, saun_id),
        )
    db.commit()
    db.close()

    return RedirectResponse(f"/ee/broneering/{token}", status_code=303)


@app.get("/ee/broneering/{token}")
def broneering_kinnitus(request: Request, token: str):
    db = get_db()
    b = db.execute(
        "SELECT b.*, a.name_et FROM bookings b "
        "JOIN accommodations a ON a.id=b.accommodation_id "
        "WHERE b.access_token=?",
        (token,),
    ).fetchone()
    db.close()
    if not b:
        return RedirectResponse("/ee", status_code=303)
    return templates.TemplateResponse(request, "et/taname.html", {"b": b})
