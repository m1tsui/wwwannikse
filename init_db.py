"""
Annikse andmebaasi loomine ja algsisu.

Kasutus:
    .venv/bin/python3 init_db.py               # skeem + majutusüksused
    .venv/bin/python3 init_db.py --test-hinnad # + testhinnad kohalikuks arenduseks

Skript on idempotentne — korduv käivitamine ei riku olemasolevat andmebaasi.
Andmemudel: vt annikse-broneerimine.md p 3.
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "annikse.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accommodations (
    id                   INTEGER PRIMARY KEY,
    slug                 TEXT NOT NULL UNIQUE,
    name_et              TEXT NOT NULL,
    name_en              TEXT NOT NULL,
    type                 TEXT NOT NULL CHECK (type IN ('majutus', 'lisateenus')),
    season_start         TEXT,          -- MM-DD, ainult majutus-tüübil
    season_end           TEXT,          -- MM-DD
    max_guests           INTEGER,       -- NULL = pole vajalik (karavan, lisateenused)
    booking_com_ical_url TEXT,          -- NULL = pole Booking.com'is
    addon_group          TEXT,          -- ainult lisateenus-tüübil; sama grupp = teineteist välistavad (nt 'saun')
    has_quantity         INTEGER NOT NULL DEFAULT 0  -- 1 = klient saab koguse valida (grillsüsi, tekk)
);

CREATE TABLE IF NOT EXISTS pricing_rules (
    id               INTEGER PRIMARY KEY,
    accommodation_id INTEGER NOT NULL REFERENCES accommodations(id),
    date_from        TEXT NOT NULL,     -- YYYY-MM-DD
    date_to          TEXT NOT NULL,
    price_per_night  INTEGER NOT NULL   -- sendid; lisateenuste puhul "hind ühiku kohta"
);

CREATE TABLE IF NOT EXISTS bookings (
    id               INTEGER PRIMARY KEY,
    accommodation_id INTEGER NOT NULL REFERENCES accommodations(id),
    start_date       TEXT NOT NULL,     -- YYYY-MM-DD
    end_date         TEXT NOT NULL,
    guest_count      INTEGER,           -- kohustuslik väikesel majal/telgil, NULL karavanil
    guest_name       TEXT NOT NULL,
    guest_email      TEXT NOT NULL,
    guest_phone      TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'ootel'
                     CHECK (status IN ('ootel', 'kinnitatud', 'makstud', 'tagasi_lükatud')),
    source           TEXT NOT NULL DEFAULT 'sait'
                     CHECK (source IN ('sait', 'booking_com')),
    total_price      INTEGER NOT NULL,  -- sendid, sh kõik lisateenused
    access_token     TEXT NOT NULL UNIQUE,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS booking_addons (
    booking_id       INTEGER NOT NULL REFERENCES bookings(id),
    accommodation_id INTEGER NOT NULL REFERENCES accommodations(id),
    quantity         INTEGER NOT NULL DEFAULT 1,   -- kogus (nt 2 tekki); 1 kui has_quantity=0
    unit_price       INTEGER NOT NULL,             -- hetketõmmis hinnast — ei muutu hiljem
    PRIMARY KEY (booking_id, accommodation_id)
);

CREATE TABLE IF NOT EXISTS booking_com_blocked_dates (
    id               INTEGER PRIMARY KEY,
    accommodation_id INTEGER NOT NULL REFERENCES accommodations(id),
    date_from        TEXT NOT NULL,     -- YYYY-MM-DD
    date_to          TEXT NOT NULL,
    last_synced_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bookings_accom_dates
    ON bookings (accommodation_id, start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_blocked_accom_dates
    ON booking_com_blocked_dates (accommodation_id, date_from, date_to);
"""

# Majutusüksused ja lisateenused.
# Veerud: slug, name_et, name_en, type, season_start, season_end,
#         max_guests, booking_com_ical_url, addon_group, has_quantity
ACCOMMODATIONS = [
    # --- majutus ---
    (
        "vaike-maja", "Väike maja rattail", "Väike maja rattail",
        "majutus", "04-01", "09-30", 4,
        "https://ical.booking.com/v1/export?t=8e953c0d-2411-4320-b573-10fa72f69fe4",
        None, 0,
    ),
    (
        "telkimine", "Telkimine", "Telkimine",
        "majutus", "05-01", "08-31", 4,
        None, None, 0,
    ),
    (
        "karavan", "Karavanauto", "Karavanauto",
        "majutus", "03-01", "10-31", None,
        None, None, 0,
    ),
    # --- lisateenused ---
    # saun-grupp: teineteist välistavad (raadionupud)
    (
        "saun-ise-kutan", "Saun (klient kütab ise)", "Saun (klient kütab ise)",
        "lisateenus", None, None, None,
        None, "saun", 0,
    ),
    (
        "saun-meie-kutame", "Saun (meie kütame)", "Saun (meie kütame)",
        "lisateenus", None, None, None,
        None, "saun", 0,
    ),
    # sõltumatud lisateenused (kogusega)
    (
        "grillsysi", "Grillsüsi", "Grillsüsi",
        "lisateenus", None, None, None,
        None, None, 1,
    ),
    (
        "tekk", "Lisatekk", "Lisatekk",
        "lisateenus", None, None, None,
        None, None, 1,
    ),
]

# Testhinnad — AINULT kohalikuks arenduseks, --test-hinnad lipuga.
# Serveris sisestatakse hinnad admin-vaates. Sendid.
TEST_PRICING = [
    # slug,              date_from,    date_to,      price
    ("vaike-maja",       "2026-01-01", "2026-12-31", 9000),   # 90 €/öö
    ("telkimine",        "2026-01-01", "2026-12-31", 4000),   # 40 €/öö
    ("karavan",          "2026-01-01", "2026-12-31", 2500),   # 25 €/öö
    ("saun-ise-kutan",   "2026-01-01", "2026-12-31", 3500),   # 35 € kogu viibimise eest
    ("saun-meie-kutame", "2026-01-01", "2026-12-31", 4500),   # 45 € kogu viibimise eest
    ("grillsysi",        "2026-01-01", "2026-12-31",  500),   #  5 €/kott
    ("tekk",             "2026-01-01", "2026-12-31",    0),   # tasuta
]


def main():
    test_hinnad = "--test-hinnad" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)

    conn.executemany(
        """INSERT OR IGNORE INTO accommodations
           (slug, name_et, name_en, type, season_start, season_end,
            max_guests, booking_com_ical_url, addon_group, has_quantity)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ACCOMMODATIONS,
    )

    if test_hinnad:
        for slug, date_from, date_to, price in TEST_PRICING:
            row = conn.execute("SELECT id FROM accommodations WHERE slug=?", (slug,)).fetchone()
            if row is None:
                continue
            exists = conn.execute(
                "SELECT 1 FROM pricing_rules WHERE accommodation_id=? AND date_from=? AND date_to=?",
                (row[0], date_from, date_to),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO pricing_rules (accommodation_id, date_from, date_to, price_per_night) VALUES (?,?,?,?)",
                    (row[0], date_from, date_to, price),
                )

    conn.commit()

    accom_count = conn.execute("SELECT COUNT(*) FROM accommodations").fetchone()[0]
    price_count = conn.execute("SELECT COUNT(*) FROM pricing_rules").fetchone()[0]
    conn.close()

    print(f"Andmebaas valmis: {DB_PATH}")
    print(f"  Majutusüksusi ja lisateenuseid: {accom_count}")
    print(f"  Hinnareegleid: {price_count}" + ("  (testandmed)" if test_hinnad else ""))


if __name__ == "__main__":
    main()
