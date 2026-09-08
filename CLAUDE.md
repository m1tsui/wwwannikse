# Üldised juhised — Annikse projekt (Tauno Madisson)

## Suhtluskeel

- Vasta eesti keeles, kui ma kirjutan eesti keeles.

## Selle projekti tehnoloogiapinu

- Backend: Python, FastAPI
- Frontend: Jinja2 template'id + HTMX, olemasolev HTML/CSS disain
- Andmebaas: SQLite
- Hostimine: Zone.ee jagatud veebimajutus ("I" pakett), alamdomeen `annikse.oruvilla.ee` samas kontos, kus WordPress (`oruvilla.ee`) — WordPress jääb puutumata
- Protsessihaldus: Zone'i PM2 (mitte systemd, mitte Docker), `--reload` lipp uvicorn käivituskäsus
- Teavitused: Ntfy (sama teenus, mida koduserveris kasutan)
- Täpne plaan: `annikse-plaan.md` ja `annikse-broneerimine.md` samas kaustas — loe neid enne suuremate otsuste tegemist, ära dubleeri nende sisu siin

## Kriitilised tehnilised lõksud (juba kogetud, ära korda)

1. **Serveri kodukaust on `/data03/virt35646`, MITTE `/home/virt35646`.** SSH sessioonis näib `/home/virt35646` töötavat (alias), aga Crontab jm käivituskeskkonnad seda ei tunne — kasuta alati `/data03/virt35646/...` absoluutseid teid.
2. **Jinja2 süntaks:** `templates.TemplateResponse(request, "tee/index.html", {})` — `request` eraldi esimese argumendina, mitte dict'i sees (vana kuju viskab `TypeError: unhashable type: 'dict'`).
3. **Static failide viited absoluutsed** (`/static/styles.css`), mitte suhtelised.

## Töövõtted

- Eelista lihtsat ja hooldatavat lahendust keerukale abstraktsioonile — see on väikese mahuga isiklik projekt, mitte suuremahuline toode.
- **Serveris ei muudeta faile kunagi otse.** Ainus lubatud voog: kohalik arvuti → `git commit` → `git push` → serveris `git pull`. Otsene serveris muutmine tekitab lahknenud Git-ajaloo (juba juhtunud korra, parandati `git reset --hard origin/main`-iga).
- Väiksed, arusaadavad sammud — ära tee suuri "kõik korraga" muudatusi ilma vahepealse kinnituseta, eriti kui riskantne (serveri konfiguratsioon, andmebaasi struktuur).
- Enne serveri/Crontab/PM2 konfiguratsiooni muutmist selgita, mida käsk teeb.
- Kommenteeri kood eesti keeles, lühidalt ja asjalikult.
- Commit-sõnumid inglise keeles, conventional-commit stiilis kui sobib (`fix:`, `feat:`).

## Soovitatud arendusjärjekord

Ehita lihtsamast keerulisemani: andmebaas → kliendi vorm (kontrolli ainult kohalikku andmebaasi, jäta Booking.com kõrvale) → admin-vaade → e-kirjad → alles siis Booking.com iCal sync (Crontab töötavaks kinnitatud) → makse (Maksekeskus) viimasena.

## Mida vältida

- Ära genereeri koodi, mida ma ise hõlpsasti ei mõista ega hooldada — selgus enne nutikust.
- Ära leiuta andmebaasi väljanimesid ise — järgi täpselt `annikse-broneerimine.md` andmemudelit.
