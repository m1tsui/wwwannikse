import secrets
import sqlite3
from datetime import date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, ValidationError, field_validator, model_validator

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
    today = date.today()
    y = today.year
    start, end = f"{y}-{mmdd_start}", f"{y}-{mmdd_end}"
    if today.isoformat() > end:
        y += 1
        start, end = f"{y}-{mmdd_start}", f"{y}-{mmdd_end}"
    return start, end


# ---------------------------------------------------------------------------
# Pydantic mudel broneerimisvormi valideerimiseks
# ---------------------------------------------------------------------------

class BroneerimisVorm(BaseModel):
    accommodation_id: int = 1
    saabub: date
    lahkub: date
    guest_count: Optional[int] = None
    guest_name: str
    guest_email: EmailStr
    guest_phone: str
    saun_valik: Optional[str] = None   # "ise" / "meie" / None
    grillsysi: bool = False
    tekk_kogus: int = 0

    @model_validator(mode="after")
    def lahkub_peab_olema_hiljem(self):
        if self.lahkub <= self.saabub:
            raise ValueError("Lahkumise kuupäev peab olema hiljem kui saabumise kuupäev.")
        return self

    @field_validator("guest_name", "guest_phone", mode="before")
    @classmethod
    def ei_tohi_olla_tyhi(cls, v):
        if isinstance(v, str):
            v = v.strip()
        if not v:
            raise ValueError("Väli on kohustuslik.")
        return v

    @field_validator("saun_valik", mode="before")
    @classmethod
    def normaliseri_saun(cls, v):
        if not v or v == "":
            return None
        if v not in ("ise", "meie"):
            raise ValueError("Vigane sauna valik.")
        return v

    @field_validator("grillsysi", mode="before")
    @classmethod
    def normaliseri_grillsysi(cls, v):
        # HTML checkbox saadab "on" kui märgitud, puudub kui märkimata
        if v in ("on", "true", "1", True):
            return True
        return False

    @field_validator("tekk_kogus", mode="before")
    @classmethod
    def tekk_kogus_vahemik(cls, v):
        if v is None or v == "":
            return 0
        try:
            v = int(v)
        except (ValueError, TypeError):
            return 0
        if v < 0:
            return 0
        if v > 4:
            raise ValueError("Lisatekke saab tellida kuni 4.")
        return v


# ---------------------------------------------------------------------------
# Abifunktsioonid
# ---------------------------------------------------------------------------

def get_saadavuse_andmed(accommodation_id: int) -> dict:
    """Tagastab ühe majutuse saadavuse andmed kalendri ja vormi jaoks.

    Tagastab:
      season_start / season_end — YYYY-MM-DD, käesolev või järgmine hooaeg
      max_guests — int või None
      blocked — list[{from, to}], hõivatud vahemikud (bookings + booking_com)
    """
    db = get_db()
    accom = db.execute(
        "SELECT season_start, season_end, max_guests FROM accommodations WHERE id=?",
        (accommodation_id,),
    ).fetchone()

    season_start = season_end = None
    max_guests = None
    if accom:
        max_guests = accom["max_guests"]
        if accom["season_start"]:
            season_start, season_end = _hooaeg_aasta(
                accom["season_start"], accom["season_end"]
            )

    # Hõivatud vahemikud bookings tabelist
    bookings_rows = db.execute(
        "SELECT start_date, end_date FROM bookings "
        "WHERE accommodation_id=? AND status IN ('ootel','kinnitatud','makstud')",
        (accommodation_id,),
    ).fetchall()

    # Hõivatud vahemikud Booking.com sünkroonist
    ical_rows = db.execute(
        "SELECT date_from, date_to FROM booking_com_blocked_dates "
        "WHERE accommodation_id=?",
        (accommodation_id,),
    ).fetchall()

    db.close()

    blocked = [
        {"from": r["start_date"], "to": r["end_date"]} for r in bookings_rows
    ] + [
        {"from": r["date_from"], "to": r["date_to"]} for r in ical_rows
    ]

    return {
        "season_start": season_start,
        "season_end": season_end,
        "max_guests": max_guests,
        "blocked": blocked,
    }


def _lisateenus_hind_euro(db, slug: str, today_str: str) -> Optional[int]:
    row = db.execute(
        "SELECT pr.price_per_night FROM pricing_rules pr "
        "JOIN accommodations a ON a.id=pr.accommodation_id "
        "WHERE a.slug=? AND pr.date_from<=? AND pr.date_to>=? "
        "ORDER BY pr.date_from DESC LIMIT 1",
        (slug, today_str, today_str),
    ).fetchone()
    if row:
        return row["price_per_night"] // 100
    return None


def _vaike_maja_ctx() -> dict:
    db = get_db()
    season_start, season_end = _hooaeg_aasta("04-01", "09-30")
    today_str = date.today().isoformat()
    ctx = {
        "season_start": season_start,
        "season_end": season_end,
        "saun_ise_hind_euro": _lisateenus_hind_euro(db, "saun-ise-kutan", today_str),
        "saun_meie_hind_euro": _lisateenus_hind_euro(db, "saun-meie-kutame", today_str),
        "grillsysi_hind_euro": _lisateenus_hind_euro(db, "grillsysi", today_str),
        "tekk_hind_euro": _lisateenus_hind_euro(db, "tekk", today_str),
        "viga": None,
        "form_data": {},
        "saadavus": get_saadavuse_andmed(1),
    }
    db.close()
    return ctx


# ---------------------------------------------------------------------------
# Marsruudid
# ---------------------------------------------------------------------------

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
    saun_valik = form.get("saun_valik", "").strip()
    grillsysi = form.get("grillsysi", "") in ("on", "true", "1")
    tekk_kogus = int(form.get("tekk_kogus", "0") or "0")
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

    def slug_hind(slug: str) -> Optional[int]:
        r = db.execute(
            "SELECT pr.price_per_night FROM pricing_rules pr "
            "JOIN accommodations a ON a.id=pr.accommodation_id "
            "WHERE a.slug=? AND pr.date_from<=? AND pr.date_to>=? "
            "ORDER BY pr.date_from DESC LIMIT 1",
            (slug, saabub_str, saabub_str),
        ).fetchone()
        return r["price_per_night"] if r else None

    saun_sendid = 0
    saun_label = None
    if saun_valik == "ise":
        h = slug_hind("saun-ise-kutan")
        if h:
            saun_sendid = h
            saun_label = "Saun (ise kütad)"
    elif saun_valik == "meie":
        h = slug_hind("saun-meie-kutame")
        if h:
            saun_sendid = h
            saun_label = "Saun (meie kütame)"

    grillsysi_unit = slug_hind("grillsysi") if grillsysi else None
    grillsysi_sendid = grillsysi_unit if grillsysi_unit else 0

    tekk_unit = slug_hind("tekk") if tekk_kogus > 0 else None
    tekk_sendid = (tekk_unit * tekk_kogus) if tekk_unit else 0

    db.close()
    kokku = majutus_sendid + saun_sendid + grillsysi_sendid + tekk_sendid

    def e(s):
        return f"{s // 100} €"

    oo = "öö" if oid == 1 else "ööd"
    html = (
        '<div class="hind-breakdown">'
        f'<div class="hind-rida"><span>{e(rule["price_per_night"])} × {oid} {oo}</span>'
        f"<span>{e(majutus_sendid)}</span></div>"
    )
    if saun_sendid and saun_label:
        html += f'<div class="hind-rida"><span>{saun_label}</span><span>{e(saun_sendid)}</span></div>'
    if grillsysi_sendid:
        html += f'<div class="hind-rida"><span>Grillsüsi</span><span>{e(grillsysi_sendid)}</span></div>'
    if tekk_sendid:
        html += f'<div class="hind-rida"><span>Lisatekk × {tekk_kogus}</span><span>{e(tekk_sendid)}</span></div>'
    html += f'<div class="hind-kokku"><span>Kokku</span><span>{e(kokku)}</span></div></div>'
    return HTMLResponse(html)


@app.post("/ee/broneeri")
async def broneeri(request: Request):
    form = await request.form()

    # Pydantic valideerimine — andmete kuju ja formaadid
    raw = {
        "accommodation_id": form.get("accommodation_id", "1"),
        "saabub": form.get("saabub", "").strip(),
        "lahkub": form.get("lahkub", "").strip(),
        "guest_count": form.get("guest_count", "").strip() or None,
        "guest_name": form.get("guest_name", ""),
        "guest_email": form.get("guest_email", ""),
        "guest_phone": form.get("guest_phone", ""),
        "saun_valik": form.get("saun_valik", ""),
        "grillsysi": form.get("grillsysi", ""),
        "tekk_kogus": form.get("tekk_kogus", "0"),
    }
    try:
        andmed = BroneerimisVorm.model_validate(raw)
    except ValidationError as e:
        esimene = e.errors()[0]
        viga = esimene["msg"].replace("Value error, ", "")
        ctx = _vaike_maja_ctx()
        ctx.update({"viga": viga, "form_data": dict(form)})
        return templates.TemplateResponse(
            request, "et/majutus/vaike-maja.html", ctx, status_code=422
        )

    saabub_str = andmed.saabub.isoformat()
    lahkub_str = andmed.lahkub.isoformat()

    # DB-põhised kontrollid — hooaeg ja külaliste arv
    db = get_db()
    accom = db.execute(
        "SELECT season_start, season_end, max_guests FROM accommodations WHERE id=?",
        (andmed.accommodation_id,),
    ).fetchone()

    if accom and accom["season_start"]:
        s_start, s_end = _hooaeg_aasta(accom["season_start"], accom["season_end"])
        if saabub_str < s_start or lahkub_str > s_end:
            db.close()
            ctx = _vaike_maja_ctx()
            ctx.update({"viga": "Valitud kuupäevad jäävad väljaspoole hooaega.", "form_data": dict(form)})
            return templates.TemplateResponse(
                request, "et/majutus/vaike-maja.html", ctx, status_code=422
            )

    if accom and accom["max_guests"] is not None:
        if andmed.guest_count is None or andmed.guest_count < 1 or andmed.guest_count > accom["max_guests"]:
            db.close()
            ctx = _vaike_maja_ctx()
            ctx.update({
                "viga": f"Külaliste arv peab olema 1–{accom['max_guests']}.",
                "form_data": dict(form),
            })
            return templates.TemplateResponse(
                request, "et/majutus/vaike-maja.html", ctx, status_code=422
            )

    # Saadavuse kontroll
    conflict = db.execute(
        "SELECT 1 FROM bookings "
        "WHERE accommodation_id=? AND status IN ('ootel','kinnitatud','makstud') "
        "AND start_date < ? AND end_date > ?",
        (andmed.accommodation_id, lahkub_str, saabub_str),
    ).fetchone()
    if conflict:
        db.close()
        ctx = _vaike_maja_ctx()
        form_dict = dict(form)
        form_dict["saabub"] = ""  # kuupäevad resetitakse, klient valib uued
        form_dict["lahkub"] = ""
        ctx.update({"viga": "Need kuupäevad on juba broneeritud. Palun vali teised kuupäevad.", "form_data": form_dict})
        return templates.TemplateResponse(
            request, "et/majutus/vaike-maja.html", ctx, status_code=409
        )

    # Arvuta koguhind + kogu lisateenuste info (hetketõmmis hinnast)
    oid = (andmed.lahkub - andmed.saabub).days
    rule = db.execute(
        "SELECT price_per_night FROM pricing_rules "
        "WHERE accommodation_id=? AND date_from<=? AND date_to>=? "
        "ORDER BY date_from DESC LIMIT 1",
        (andmed.accommodation_id, saabub_str, saabub_str),
    ).fetchone()
    majutus_sendid = (rule["price_per_night"] * oid) if rule else 0

    def addon_row(slug: str):
        return db.execute(
            "SELECT a.id, pr.price_per_night FROM pricing_rules pr "
            "JOIN accommodations a ON a.id=pr.accommodation_id "
            "WHERE a.slug=? AND pr.date_from<=? AND pr.date_to>=? "
            "ORDER BY pr.date_from DESC LIMIT 1",
            (slug, saabub_str, saabub_str),
        ).fetchone()

    addon_kirjed = []  # (accommodation_id, quantity, unit_price)
    kokku_lisad = 0

    if andmed.saun_valik:
        slug = "saun-ise-kutan" if andmed.saun_valik == "ise" else "saun-meie-kutame"
        r = addon_row(slug)
        if r:
            addon_kirjed.append((r["id"], 1, r["price_per_night"]))
            kokku_lisad += r["price_per_night"]

    if andmed.grillsysi:
        r = addon_row("grillsysi")
        if r:
            addon_kirjed.append((r["id"], 1, r["price_per_night"]))
            kokku_lisad += r["price_per_night"]

    if andmed.tekk_kogus > 0:
        r = addon_row("tekk")
        if r:
            addon_kirjed.append((r["id"], andmed.tekk_kogus, r["price_per_night"]))
            kokku_lisad += r["price_per_night"] * andmed.tekk_kogus

    total_price = majutus_sendid + kokku_lisad
    token = secrets.token_urlsafe(8)

    cursor = db.execute(
        "INSERT INTO bookings "
        "(accommodation_id, start_date, end_date, guest_count, "
        " guest_name, guest_email, guest_phone, status, source, total_price, access_token) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'ootel', 'sait', ?, ?)",
        (
            andmed.accommodation_id, saabub_str, lahkub_str, andmed.guest_count,
            andmed.guest_name, str(andmed.guest_email), andmed.guest_phone,
            total_price, token,
        ),
    )
    booking_id = cursor.lastrowid
    for addon_acc_id, qty, unit in addon_kirjed:
        db.execute(
            "INSERT INTO booking_addons (booking_id, accommodation_id, quantity, unit_price) "
            "VALUES (?, ?, ?, ?)",
            (booking_id, addon_acc_id, qty, unit),
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
