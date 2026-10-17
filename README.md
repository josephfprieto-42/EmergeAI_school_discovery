# SchoolMatch Miami

AI-assisted school discovery for Miami-Dade County families, from infant care through 12th grade. Explore 3,200+ real providers on a map, filter by grade, type, distance, and Florida DOE grade, and describe what you need in plain language to get ranked recommendations with grounded explanations.

Everything runs locally: React + TypeScript + Google Maps in the browser, FastAPI + SQLite on the server, OpenAI for language understanding and explanations. No data is fabricated: every value shown comes from a public dataset listed below, and missing values are displayed as "Not reported".

## What's inside

| Layer | Stack |
| --- | --- |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS 4, `@vis.gl/react-google-maps`, `@googlemaps/markerclusterer`, Zustand |
| Backend | FastAPI, SQLite (FTS5), httpx, OpenAI SDK |
| Data | Miami-Dade County Open Data (ArcGIS), Florida DOE School Grades 2025-26, NCES Common Core of Data (via Urban Institute API) |

Features:

- **Map** with 3,289 providers (public, charter, private, licensed child care, Head Start), clustering, category colors, home pin and radius, click-through details.
- **Explore** panel: optional location (current location, or an address, neighborhood, or ZIP via Places Autocomplete with an offline geocode fallback), name search (full-text), category / grade / distance / FLDOE grade filters, distance-sorted list. Precise coordinates are kept for the open visit unless you choose to remember them with a match chat.
- **Find my match**: conversational input -> structured preferences (LLM) -> SQL filtering -> deterministic weighted ranking -> LLM explanation restricted to the ranked rows. Numbered pins on the map, "why" and "tradeoffs" per school. Follow-up messages refine the previous preferences.
- **Graceful degradation**: without an OpenAI key, a keyword parser and templated explanations take over; without a Google key, geocoding falls back to an offline Miami-Dade ZIP/neighborhood table and the map renders as a projected plot.

## Quick start

Prerequisites: Python 3.9+, Node 20+ (tested on Node 26), macOS/Linux shell.

```bash
# 1. Backend
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cp backend/.env.example backend/.env        # then paste your keys (see below)

# 2. Frontend
(cd frontend && npm install)

# 3. Run both (API on :8000, app on :5173)
./dev.sh
```

Open <http://localhost:5173>.

The repository ships with a pre-built `data/schoolmatch.db` and the raw source snapshots under `data/raw/`, so no network access is needed to run the app. To refresh the data, see [Data pipeline](#data-pipeline). Retrieval details for each file are in [docs/data-sources.md](docs/data-sources.md).

### API keys (`backend/.env`)

| Variable | Needed for | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | Conversational preference extraction and explanations | Server-side only. Default model `gpt-4o-mini` (`OPENAI_MODEL`). |
| `GOOGLE_MAPS_BROWSER_KEY` | Interactive Google Map and Places Autocomplete | Delivered to the browser via `GET /api/config`. In Google Cloud Console restrict it to **HTTP referrers** `http://localhost:5173/*` and to the **Maps JavaScript API** and **Places API (New)**. |
| `GOOGLE_GEOCODING_KEY` | Address -> coordinates | Server-side only, never sent to the browser. If blank, falls back to `GOOGLE_MAPS_BROWSER_KEY` (then your browser key must also allow the Geocoding API and IP referrers), otherwise to the offline lookup. |
| `GOOGLE_MAP_ID` | Optional | A Map ID for Advanced Markers/styling. Defaults to Google's `DEMO_MAP_ID`. |

Enable **Maps JavaScript API**, **Places API (New)**, and **Geocoding API** on the Google Cloud project. Billing must be enabled on the project (the monthly free credit comfortably covers local development).

Restart the API after editing `.env`.

## Data pipeline

All sources are public and keyless. Ingestion produces `data/schoolmatch.db`. URLs, request parameters, snapshot filenames, collection timestamps, and sources that were looked up and not loaded are in [docs/data-sources.md](docs/data-sources.md).

| Source | What we take | Join key |
| --- | --- | --- |
| [Miami-Dade County Open Data](https://gis-mdc.opendata.arcgis.com/) — `SchoolSite`, `CharterSchool`, `PrivateSchool`, `Daycare`, `HeadStart` layers | Name, address, coordinates, grade span, enrollment/capacity, phone, website, licensing | MDCPS school number for public/charter |
| [Florida DOE School Grades 2025-26](https://www.fldoe.org/accountability/accountability-reporting/school-grades/) (`SchoolGrades26.xlsx`, District 13 rows) | Letter grade and history, ELA/Math/Science/Social Studies achievement, learning gains, graduation rate, points earned, Title I, % economically disadvantaged | School number |
| [NCES CCD](https://educationdata.urban.org/documentation/schools.html) via Urban Institute API (LEA 1200390, 2023) | Enrollment, free/reduced lunch, teacher FTE (-> student:teacher ratio), magnet, Title I, locale | State school id (`13-XXXX`) |
| [M-DCPS school directory](https://mdcpswebapps2.dadeschools.net/Help) `GET /api/schools/{number}?details=true` | Official `web` URL for public schools. A URL is stored only when a GET of that exact URL returns HTTP 2xx | MDCPS location number |
| [Your Choice Miami](https://yourchoicemiami.org/program-search) program search | Magnet and parent-choice program names, and whether a test or audition is required. The rows in the app are the browser page snapshots | MDCPS location number |
| [CRDC 2021-22](https://educationdata.urban.org/documentation/) AP, IB, and gifted enrollment, via the Urban Institute (LEA 1200390) | Students enrolled in AP (and by subject), the IB diploma, and gifted or talented programs. A missing count stays blank | NCES school id |
| [FHSAA member directory](https://www.fhsaahome.org/widget/school-directory-locations) | Interscholastic sport and team (boys or girls) for member high schools. A school is linked only when its directory name matches one catalog school | School name |
| [Miami-Dade attendance boundaries](https://gis.miamidade.gov/arcgis/rest/services/CommunityServices/MD_Educational/MapServer) layers 9, 10, and 11 | Elementary, high, and middle attendance polygons | MDCPS location number |
| [Florida private school directory](https://www.floridaschoolchoice.org/information/privateschooldirectory/DownloadExcelFile.aspx) | School-reported religious affiliation, nonprofit status, accreditation, scholarship participation. Survey years of 2023 or earlier stay off the profile | School name and address |

Rebuild:

```bash
backend/.venv/bin/python backend/ingest/fetch_mdc_gis.py
backend/.venv/bin/python backend/ingest/fetch_nces.py
backend/.venv/bin/python backend/ingest/fetch_mdcps_websites.py
backend/.venv/bin/python backend/ingest/fetch_offerings.py crdc fhsaa
# Florida DOE blocks non-browser clients. Save SchoolGrades26.xlsx from the
# school-grades page into data/raw/. A copy is already included.
backend/.venv/bin/python backend/ingest/fetch_boundaries.py
backend/.venv/bin/python backend/ingest/fetch_private_directory.py
# yourchoicemiami.org challenges scripted clients. The program rows the app
# serves are the browser snapshots data/raw/mdcps_*page*.json.
backend/.venv/bin/python backend/ingest/build_db.py
backend/.venv/bin/python backend/ingest/apply_enrichment.py
```

Normalization notes:

- Grades are encoded numerically: `-2` infant/toddler, `-1` PK, `0` K, `1..12`. Daycare = infant-PK; Head Start = PK (Early Head Start = infant-PK).
- Administrative buildings and adult/technical education sites in the public layer are excluded; closed private schools are excluded.
- Where the county layer lacks a grade span or enrollment, NCES values fill the gap.
- Student:teacher ratios outside 4-45 (reporting artifacts) are stored as null.
- Current coverage: 345 traditional public, 181 charter, 965 private, 1,650 licensed child care, 109 Head Start; 450 schools carry FLDOE grades, 489 carry NCES stats.

## Architecture

```
frontend (Vite :5173)  --/api proxy-->  FastAPI (:8000)  -->  SQLite data/schoolmatch.db
                                             |
                                             +--> OpenAI (prefs extraction, explanations)   [server-side key]
                                             +--> Google Geocoding                          [server-side key]
browser --> Google Maps JavaScript API and Places Autocomplete                                [referrer-restricted key]
```

Recommendation flow (`POST /api/recommend`):

1. **Extract** — the conversation (plus previously extracted preferences) is turned into a `Preferences` JSON object: location, child grade(s), categories, radius, priorities, keywords, minimum FLDOE grade. Fallback: regex/keyword parser.
2. **Geocode** — `location_text` is resolved server-side (Google, else offline table).
3. **Filter** — SQL on category, grade span, FLDOE grade; then radius with automatic widening if fewer than 5 candidates.
4. **Rank** — deterministic weighted score: distance decay, attendance-zone match when a home point is set, FLDOE grade + points + achievement, size preference, verified catalog programs (name-only matches are labeled separately), school-reported scholarship participation when cost is a priority, and fit (student:teacher ratio, category preference). Weights shift with the stated priorities. The per-component breakdown is returned with each school.
5. **Explain** — the top N rows (compact JSON) go to the LLM, which must cite only those fields; output is per-school `why`/`tradeoffs` plus a summary and optional follow-up question. Fallback: templated sentences from the same fields.

Other endpoints: `GET /api/schools` (filters, bbox, FTS `q`, lat/lon/radius), `GET /api/schools/{id}`, `GET /api/geocode`, `GET /api/config`, `GET /api/health`. Interactive docs at <http://localhost:8000/docs>.

## Project layout

```
backend/
  app/main.py                 FastAPI app, CORS, routers
  app/config.py               .env loading
  app/db.py                   SQLite access, haversine, row shaping
  app/schemas.py              Pydantic models
  app/routers/{schools,recommend,geo}.py
  app/services/ranking.py     deterministic filter + scoring
  app/services/llm.py         OpenAI calls + fallbacks
  app/services/geocode.py     Google Geocoding + offline fallback
  ingest/fetch_mdc_gis.py     ArcGIS school and child-care points
  ingest/fetch_nces.py        Urban Institute / NCES downloader
  ingest/fetch_mdcps_websites.py
  ingest/fetch_offerings.py   CRDC and FHSAA (choice fetch aborts on a bot challenge)
  ingest/fetch_boundaries.py  attendance polygons
  ingest/fetch_private_directory.py
  ingest/build_db.py          normalizer -> SQLite
  ingest/apply_enrichment.py  boundaries, choice pages, private directory
  .env.example
frontend/
  src/App.tsx                 layout, header, mode switch
  src/store.ts                Zustand state + API orchestration
  src/components/MapView.tsx  Google map (clustered markers, pins, radius) + fallback plot
  src/components/{FilterBar,SchoolList,SchoolDetail,ChatPanel,ui}.tsx
data/
  schoolmatch.db              built database
  raw/                        source snapshots
  audit/                      overlap and enrichment reports
docs/
  data-sources.md             URL, method, snapshot, and timestamp for each source
dev.sh                        run API + web app
```

## Limitations

- Magnet and parent-choice program names come from the Miami-Dade catalog snapshots in `data/raw/mdcps_*page*.json`. Themes are taken from those titles. A match against the school name alone is labeled a name signal. Scripted refetch of yourchoicemiami.org is blocked by a bot challenge and is not bypassed.
- Attendance boundaries come from Miami-Dade GIS layers 9, 10, and 11 (elementary, high, middle). A point inside a polygon is the assigned school for that level. It does not admit a student to a magnet.
- Private-school religious affiliation, nonprofit status, accreditation, and scholarship participation come from the school's own Florida directory survey. Survey years of 2023 or earlier are stored but not copied onto the profile. Scholarship participation is not a tuition price.
- AP, IB, and gifted figures are 2021-22 enrollment counts, not a current course list. A blank count means that figure was not reported.
- FHSAA sports cover member high schools only. Club lists, and sports at elementary and middle schools, are not in a public file.
- The International Baccalaureate school directory blocks automated download. IB program names in the district catalog, and IB diploma enrollment in the CRDC, are what this app stores.
- Florida does not grade private schools or early-childhood providers, so academic comparisons are only available for public and charter schools.
- Tuition amounts, bell times, bus routes, and a current special-education catalog were not in a usable public file. Child-care operating hours on the CARES search require a reCAPTCHA and were not collected. The county daycare layer still supplies license number, expiration, and capacity, and campus after-school care is a separate county flag.
- Daycare license expiration dates come straight from the county layer and may be stale.

## Attribution

Data: Miami-Dade County Information Technology Department (Open Data), Miami-Dade County Public Schools choice catalog, Florida Department of Education, National Center for Education Statistics and the Civil Rights Data Collection via the Urban Institute Education Data Portal, Florida High School Athletic Association. Map: Google Maps Platform.
