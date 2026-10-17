# Data sources and retrieval

Every value in `data/schoolmatch.db` comes from a public file listed here. Missing values stay null and the app shows them as "Not reported". Nothing is inferred from a school name.

This file is the retrieval record: the URL, the script or manual step, the snapshot under `data/raw/`, and what the snapshot itself stores. The README pipeline table is a short index. Per-school attribution in the database is described at the end.

Collection dates below are the timestamps stored in the snapshots or written by the loader. Snapshots that do not store a timestamp say so.

## How a rebuild runs

```bash
backend/.venv/bin/python backend/ingest/fetch_mdc_gis.py
backend/.venv/bin/python backend/ingest/fetch_nces.py
backend/.venv/bin/python backend/ingest/fetch_mdcps_websites.py
backend/.venv/bin/python backend/ingest/fetch_offerings.py crdc fhsaa
# SchoolGrades26.xlsx is saved in a browser. See Florida DOE below.
backend/.venv/bin/python backend/ingest/fetch_boundaries.py
backend/.venv/bin/python backend/ingest/fetch_private_directory.py
# Choice and magnet page JSON is saved in a browser. See Your Choice Miami below.
backend/.venv/bin/python backend/ingest/build_db.py
backend/.venv/bin/python backend/ingest/apply_enrichment.py
```

`build_db.py` deletes and recreates `data/schoolmatch.db`. `apply_enrichment.py` then updates that file in place. Run enrichment after the build. It replaces attendance zones, program rows, and the private-directory table. It leaves the rest of the school rows in place.

`data/audit/enrichment_report.json` is rewritten by `apply_enrichment.py`. `data/audit/overlap_report.json` is rewritten by `build_db.py`.

## Sources that are loaded

### Miami-Dade County school and child-care points

| | |
| --- | --- |
| Portal | [Miami-Dade County Open Data](https://gis-mdc.opendata.arcgis.com/) |
| Service | `https://services.arcgis.com/8Pc9XBTAsYuxx9Ny/arcgis/rest/services` |
| Script | `backend/ingest/fetch_mdc_gis.py` |
| Loader | `backend/ingest/build_db.py` |
| Database tags | `mdc_gis_public`, `mdc_gis_charter`, `mdc_gis_private`, `mdc_gis_daycare`, `mdc_gis_headstart` |

One paged FeatureServer query per layer. Parameters: `where=1=1`, `outFields=*`, `outSR=4326`, `f=json`, 2,000 records per page. No API key.

| Layer | Service name | Snapshot | Features in the current file |
| --- | --- | --- | --- |
| Public school sites | `SchoolSite_gdb` | `data/raw/mdc_public.json` | 451 |
| Charter schools | `CharterSchool_gdb` | `data/raw/mdc_charter.json` | 181 |
| Private schools | `PrivateSchool_gdb` | `data/raw/mdc_private.json` | 971 |
| Licensed child care | `Daycare_gdb` | `data/raw/mdc_daycare.json` | 1,650 |
| Head Start | `HeadStart_gdb` | `data/raw/mdc_headstart.json` | 109 |

Each file stores `service` (the layer name) and `features`. It does not store the full query URL or a fetch time. The method is the script above.

Fields used: name, address, coordinates, grade span, enrollment or capacity, phone, website when the layer has one, and daycare license number plus expiration. Public and charter rows join to later files on the M-DCPS location number. Administrative and adult or technical sites in the public layer are dropped. Closed private schools are dropped. A daycare on a K-12 campus sets that school's after-school-care flag. That flag is the county daycare layer, not a separate feed.

### Florida DOE school grades, 2025-26

| | |
| --- | --- |
| Page | [Florida DOE school grades](https://www.fldoe.org/accountability/accountability-reporting/school-grades/) |
| File | `SchoolGrades26.xlsx`, district number `13` (Miami-Dade) |
| Snapshot | `data/raw/SchoolGrades26.xlsx` |
| Loader | `backend/ingest/build_db.py` (`ingest_fldoe`) |
| Database tag | `fldoe` |

Florida DOE blocks non-browser clients. There is no fetch script. The workbook is downloaded in a browser and saved at the path above. The file has no sidecar, so the download time and the exact file URL are not recorded. The loader reads the sheet whose header begins with `District Number` and keeps rows where that column is `13`.

Stored fields: letter grade and prior grades, ELA, math, science, and social studies achievement, learning gains, graduation rate, points earned, Title I, and percent economically disadvantaged. Grades land in `school_grades`, which has no source column. The school row is tagged `fldoe`.

### NCES Common Core of Data, 2023

| | |
| --- | --- |
| Docs | [Urban Institute school directory](https://educationdata.urban.org/documentation/schools.html) |
| Request | `GET https://educationdata.urban.org/api/v1/schools/ccd/directory/2023/?leaid=1200390` |
| Script | `backend/ingest/fetch_nces.py` |
| Snapshot | `data/raw/nces_directory.json` |
| Loader | `backend/ingest/build_db.py` (`ingest_nces`) |
| Database tag | `nces` |

The script follows the API `next` link until the result set ends. It tries year 2023, then 2022 if 2023 is empty. The current file is year 2023, LEA `1200390` (Miami-Dade County Public Schools, including district-sponsored charters), 556 rows. The file stores `year`, `leaid`, and `results`. It does not store the request URL or a fetch time.

Join key is the state school id (`13-XXXX`), matched to the M-DCPS location number. Used when the county layer has no grade span or enrollment: enrollment, free and reduced-price lunch, teacher FTE (turned into a student:teacher ratio), magnet, Title I, and locale. Ratios outside 4–45 are stored as null. Rows land in `school_stats`, which has no source column. The school row is tagged `nces`.

### M-DCPS public school websites

| | |
| --- | --- |
| Directory | `GET https://mdcpswebapps2.dadeschools.net/api/schools/{number}?details=true` |
| Help page | [M-DCPS school directory](https://mdcpswebapps2.dadeschools.net/Help) |
| Script | `backend/ingest/fetch_mdcps_websites.py` |
| Snapshot | `data/raw/mdcps_websites.json` |
| Loader | `backend/ingest/build_db.py` (`apply_mdcps_websites`) |
| Database tag | `mdcps_website` |

The county public layer has no website field. The script takes location numbers from `mdc_public.json`, skipping administrative types `A` and `O`. It calls the directory with `curl` because this host rejects the TLS handshake from the macOS Python used here. A `web` value is kept only when it is an absolute http(s) URL and a GET of that exact URL returns HTTP 2xx. The district homepage, with no school path or query, is dropped. Retries once on failure. Eight workers.

The snapshot records the URL template, `checked_at` `2026-10-17T16:02:29.758400+00:00`, the keep rule, and 343 schools.

### Your Choice Miami programs

Program names shown in the app come from browser-saved search pages. A scripted copy also exists. The two are not the same load.

**What the app serves**

| | |
| --- | --- |
| Page | [Your Choice Miami program search](https://yourchoicemiami.org/program-search) |
| Snapshots | `data/raw/mdcps_choice_page1.json`, `mdcps_choice_page2.json`, `mdcps_choice_page3.json`, `mdcps_magnet_page1.json`, `mdcps_magnet_page2.json` |
| Loader | `backend/ingest/apply_enrichment.py` (`ingest_programs`) |
| Database tag | `yourchoicemiami` |
| Audit | `data/audit/enrichment_report.json` → `choice_and_magnet_programs` |

These five files are JSON arrays saved from the public catalog in a browser. Scripted clients receive a Sucuri JavaScript challenge. `fetch_choice_programs.py` and the choice branch of `fetch_offerings.py` stop when they see that challenge. They do not solve it.

Each school object stores `mdcps_id`, `name`, `address`, `programs`, `program_heading`, and `source_url` (`https://yourchoicemiami.org/program-search/school-details?school={id}`). The files do not store a capture time. The loader stamps every program row with `collected_at` `2026-10-17T16:40:00+00:00`, a constant in `apply_enrichment.py`, and writes the same sentence into the enrichment report: the rows were read in a browser.

Current files: 249 choice-school rows (100 + 100 + 49) and 122 magnet-school rows (100 + 22). The last enrichment report: 371 school rows, 1,093 programs, 299 schools matched on M-DCPS location number, 3 unmatched. Magnet and choice are taken from `program_heading`. "Test required" and "auditions required" are read from the program title. Themes are derived from those titles by `backend/ingest/program_themes.py`.

`apply_enrichment.py` drops `school_programs` and rebuilds it from these pages only.

**Scripted copy that does not supply the program rows**

| | |
| --- | --- |
| Script | `backend/ingest/fetch_offerings.py` (the `choice` target) |
| Snapshot | `data/raw/mdcps_programs.json` |
| First loader | `backend/ingest/offerings.py`, called from `build_db.py` |
| Database tag | `mdcps_choice` |

`mdcps_programs.json` records source `https://yourchoicemiami.org/program-search`, `fetched_at` `2026-10-17T16:23:29.012755+00:00`, and 294 schools. That fetch succeeded. `build_db.py` inserts those programs and tags the school `mdcps_choice`. `apply_enrichment.py` then deletes `school_programs` and does not remove the `mdcps_choice` tag. After a full rebuild, program rows are `yourchoicemiami` and many of the same schools still carry the earlier `mdcps_choice` tag.

`backend/ingest/fetch_choice_programs.py` is a second downloader. It writes `data/raw/mdcps_choice_programs.json`, which is not in this repository. On a Sucuri response it exits and tells you to use the saved page snapshots.

**File present and not loaded**

`data/raw/mdcps_magnet_catalog_2026_27.txt` is the text of a 2026-27 M-DCPS magnet catalog. No ingest script reads it. The file does not record a download URL or a capture time.

### CRDC AP, IB, and gifted enrollment, 2021-22

| | |
| --- | --- |
| Docs | [Urban Institute Education Data Portal](https://educationdata.urban.org/documentation/) |
| Request | `GET https://educationdata.urban.org/api/v1/schools/crdc/ap-ib-enrollment/2021/race/sex/?leaid=1200390` |
| Script | `backend/ingest/fetch_offerings.py` (`crdc`) |
| Snapshot | `data/raw/crdc_academics.json` |
| Loader | `backend/ingest/offerings.py` (`ingest_academics`) |
| Database tag | `crdc` |

The script pages with the API `next` link. It keeps the race `99` / sex `99` total, and sums race and sex breakdowns only when that total cell is a negative reserve code (missing). Negative codes are not stored as zero. The snapshot records the request URL, `year` 2021, `leaid` `1200390`, `fetched_at` `2026-10-17T16:27:55.307568+00:00`, and 509 schools.

Join is the NCES school id already stored from the Common Core of Data. Counts go in `school_academics` (no source column). A blank count means that figure was not reported. These are 2021-22 enrollment counts, not a current course list.

### FHSAA member sports

| | |
| --- | --- |
| Page | [FHSAA school directory locations](https://www.fhsaahome.org/widget/school-directory-locations) |
| Script | `backend/ingest/fetch_offerings.py` (`fhsaa`) |
| Snapshot | `data/raw/fhsaa_sports.json` |
| Loader | `backend/ingest/offerings.py` (`ingest_sports`) |
| Database tag | `fhsaa` on the school; `school_sports.source` is `fhsaa` |

The script reads the sport `<select>`, then requests each `sport_id` with an empty `school_id`. It parses the directory popup for school name, street, and ZIP. Staff names on the page are not stored. The snapshot records the page URL, `fetched_at` `2026-10-17T16:24:32.635701+00:00`, and 32 sports.

A school is linked only when the directory name matches one catalog school and not two. Elementary and middle school sports, and club lists, are not in this file.

### Attendance boundaries

| | |
| --- | --- |
| Service | `https://gis.miamidade.gov/arcgis/rest/services/CommunityServices/MD_Educational/MapServer` |
| Script | `backend/ingest/fetch_boundaries.py` |
| Snapshot | `data/raw/mdc_attendance_boundaries.json` |
| Loader | `backend/ingest/apply_enrichment.py` (`ingest_boundaries`) |
| Database tag | `mdc_attendance_boundary` |
| Audit | `data/audit/enrichment_report.json` → `attendance_boundaries` |

Public, keyless ArcGIS. One paged query per layer, `where=1=1`, `outFields=*`, `returnGeometry=true`, `outSR=4326`, `geometryPrecision=5`, 100 records per page, 0.3 seconds between pages. User agent `SchoolMatchMiami/1.0`. The script checks that a sample ring is in the Miami-Dade longitude and latitude range before writing the file.

| Level | Layer id |
| --- | --- |
| Elementary | 9 |
| High | 10 |
| Middle | 11 |

The snapshot stores `source`, `collected_at` `2026-10-17T16:26:29.963291+00:00`, the layer description, the service copyright text, and 336 features. The loader keeps one row per level and `OBJECTID`. The last enrichment report integrated 303 zones, matched 283 schools, and left 2 zones unmatched. Feature `MODIFIEDDATE` values in that load run from 2016-05-19 to 2026-09-16. Polygons and `collected_at` are stored on `attendance_zones`.

A point inside a polygon is the assigned school for that level. It does not admit a student to a magnet. Attribute Miami-Dade County GIS and M-DCPS School Operations.

### Florida private school directory

| | |
| --- | --- |
| Form | `https://www.floridaschoolchoice.org/information/privateschooldirectory/DownloadExcelFile.aspx` |
| Script | `backend/ingest/fetch_private_directory.py` |
| Snapshots | `data/raw/fl_private_directory_dade.xlsx`, `data/raw/fl_private_directory_dade.json` |
| Loader | `backend/ingest/apply_enrichment.py` (`load_directory`) |
| Database tag | `fldoe_private_directory` |
| Audit | `data/audit/enrichment_report.json` → `private_school_directory` |

The directory page is a public Excel download under section 1002.42, Florida Statutes. `robots.txt` does not disallow this path. The script GETs the form, copies the ASP.NET hidden fields, checks Miami-Dade (`cblSelectDistrict$12`), checks the extra survey columns (nonprofit, scholarship programs, enrollment, grades, student type, accreditation, religious affiliation, denomination), and posts `btnDownload`. It rejects an HTML body. User agent `SchoolMatchMiami/1.0`.

The JSON sidecar records the form URL, `collected_at` `2026-10-17T16:26:42.721629+00:00`, district `DADE`, the statute, and this verification line: schools submit the annual survey and Florida DOE does not verify it.

The last enrichment report: 687 directory rows, 380 matched, 307 unmatched. Survey years of 2023 or earlier stay in `private_directory` and are not copied onto the school profile (22 such rows in that report). Religious affiliation, nonprofit status, accreditation, and scholarship participation on a profile are the school's own survey answers. Scholarship participation is not a tuition amount.

## Sources that were not ingested

Recorded in `data/audit/enrichment_report.json` under `unavailable`, and in the README limitations.

| Source | URL | Why it is not in the database |
| --- | --- | --- |
| Florida DCF CARES public search | `https://caressearch.myflfamilies.com/PublicSearch/` | Every search requires a bearer token and a reCAPTCHA v3 token. Operating hours and inspection history were not collected. |
| DCF statewide child-care list | `https://www.myflfamilies.com/sites/default/files/2023-11/Public%20-%202023-11-1%20-%20Statewide.pdf` | The public file found is dated 2023-11-01 and has no operating hours. It was not ingested. |
| Tuition, bell times, bus routes, special-education catalog | — | No current bulk file was found. `alt_ese` in the school-grades workbook is zero for every graded school in this database, so it was not surfaced. |
| International Baccalaureate school directory | — | Automated download is blocked. IB names in the district catalog, and IB diploma enrollment in the CRDC, are what is stored. |

## What the database records

| Place | What it stores |
| --- | --- |
| `schools.sources` | JSON array of source tags for that school |
| `school_sources` | One row per school and source, with `source_id` and `match_method` (how the row was joined, not how the file was downloaded) |
| `attendance_zones` | `source`, `collected_at`, polygon, and the feature's own modified date |
| `school_programs` | `source` (`yourchoicemiami` after enrichment), per-school `source_url`, and `collected_at` |
| `private_directory` | `source`, `collected_at`, and the DOE verification sentence |
| `school_sports` | `source` `fhsaa` |
| `school_grades`, `school_stats`, `school_academics` | No source column. The matching tag on `schools.sources` is `fldoe`, `nces`, or `crdc` |

Source tags in the current database: `mdc_gis_public`, `mdc_gis_charter`, `mdc_gis_private`, `mdc_gis_daycare`, `mdc_gis_headstart`, `fldoe`, `nces`, `mdcps_website`, `mdcps_choice`, `yourchoicemiami`, `crdc`, `fhsaa`, `mdc_attendance_boundary`, `fldoe_private_directory`.

`mdcps_choice` and `yourchoicemiami` are both Your Choice Miami. See the program section above for which file each tag came from.

## Attribution

Miami-Dade County Information Technology Department (Open Data), Miami-Dade County Public Schools choice catalog, Florida Department of Education, National Center for Education Statistics and the Civil Rights Data Collection via the Urban Institute Education Data Portal, Florida High School Athletic Association.
