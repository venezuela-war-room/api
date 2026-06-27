# Entity-Relationship Diagram

```mermaid
erDiagram

    instalaciones {
        UUID        id                  PK  "gen_random_uuid()"
        VARCHAR     tipo                    "hospital | albergue | morgue | punto_concentracion | centro_medico"
        VARCHAR     nombre                  "display name"
        VARCHAR     normalized_nombre       "lowercase + unaccent, dedup key"
        VARCHAR     direccion               "address — client-supplied or geocoded"
        FLOAT       lat                     "latitude (from OpenStreetMap)"
        FLOAT       lon                     "longitude (from OpenStreetMap)"
        TIMESTAMPTZ geocoded_at             "NULL = pending geocoding; set once attempted"
        TIMESTAMPTZ created_at              "auto"
    }

    ubicaciones {
        UUID        id                  PK
        UUID        instalacion_id      FK  "nullable — null when no registered facility"
        TEXT        detalles                "ward, section, floor, or custom address"
        VARCHAR     normalized_detalles     "normalize(detalles) or '', used for dedup"
        TIMESTAMPTZ created_at              "auto"
    }

    api_keys {
        UUID        id                  PK
        VARCHAR     key_prefix              "first 12 chars of raw key"
        VARCHAR     key_hash            UK  "SHA-256 of raw key — never stored plain"
        VARCHAR     team_name               "e.g. ocr-ecrespo, bot-edwinvrgs"
        VARCHAR     description
        BOOLEAN     is_active               "revocation flag, default true"
        TIMESTAMPTZ created_at              "auto"
    }

    found_people {
        UUID        id                  PK
        VARCHAR     full_name               "required"
        VARCHAR     document_id             "cédula, digits only"
        INTEGER     age
        UUID        ubicacion_id        FK  "nullable — person's current location"
        VARCHAR     lugar_procedencia       "zone / place of origin"
        TEXT        relevant_info           "notes, diagnosis, source info"
        BOOLEAN     fallecido               "deceased flag, default false"
        VARCHAR     source_url
        VARCHAR     source_hash         UK  "sha256 dedup key"
        VARCHAR     status                  "verified | citizen_report | needs_review | removed"
        UUID        api_key_id          FK  "which team ingested this record"
        JSONB       raw                     "original record verbatim"
        TIMESTAMPTZ created_at              "auto"
        TIMESTAMPTZ updated_at              "auto, updated on upsert"
    }

    instalaciones ||--o{ ubicaciones  : "referenced by"
    ubicaciones   ||--o{ found_people : "location of"
    api_keys      ||--o{ found_people : "ingested by"
```

## Relationships

| From | Cardinality | To | Description |
|---|---|---|---|
| `instalaciones` | 1 → many | `ubicaciones` | A facility can have many location instances (one per ward/section/detail) |
| `ubicaciones` | 1 → many | `found_people` | A location can have many people (e.g. all patients in the same ward) |
| `api_keys` | 1 → many | `found_people` | A team API key is linked to all records it ingested |

## Location model explained

```
instalaciones           — the registered facility (Hospital Vargas, Albergue Catia, etc.)
    ↓ (optional FK)
ubicaciones             — a specific location within or without a facility
    · instalacion_id    → points to a known facility, OR null for unknown/ad-hoc locations
    · detalles          → "Sala de Emergencias, Piso 3" OR "Calle Principal #5, Catia"
    ↓
found_people.ubicacion_id
```

**Example flows:**
- Person at a registered hospital ward: `instalacion → Hospital Vargas` + `detalles = "UCI"`
- Person at a shelter: `instalacion → Albergue Municipal Catia` + `detalles = null`
- Person at an unknown address: `instalacion_id = null` + `detalles = "Casa amarilla, Av. Principal, La Guaira"`

## Valid `tipo` values for `instalaciones`

| Tipo | Description |
|---|---|
| `hospital` | Full hospitals |
| `albergue` | Shelters and temporary housing |
| `centro_medico` | Clinics and smaller medical centers |
| `morgue` | Morgues — for identification of deceased |
| `punto_concentracion` | Staging/assembly points set up after the earthquake |

## Notes

- `ubicacion_id` on `found_people` is nullable — a record can exist without a known location (e.g. unconfirmed citizen reports)
- `api_key_id` on `found_people` records which team submitted each row — useful for audit and data quality tracking
- `source_hash` is the **deduplication key**: bulk upserts use `ON CONFLICT (source_hash) DO UPDATE`
- `fallecido = true` does NOT set `status = 'removed'` — deceased records remain publicly searchable for family identification
- `status = 'removed'` is a soft delete for data quality reasons (duplicates, errors); it hides records from default search
- `ubicaciones` deduplicates by `(instalacion_id, normalized_detalles)` — same ward at the same hospital → same `ubicacion` row shared across all people there

## Indexes

| Table | Column(s) | Type | Purpose |
|---|---|---|---|
| `found_people` | `document_id` | B-tree | Exact cédula lookup |
| `found_people` | `status` | B-tree | Status filter |
| `found_people` | `updated_at DESC` | B-tree | Default sort |
| `found_people` | `ubicacion_id` | B-tree | Location filter join |
| `found_people` | `api_key_id` | B-tree | Per-team record queries |
| `found_people` | `fallecido` | B-tree | Deceased filter |
| `found_people` | `full_name` (GIN trgm) | GIN | Fuzzy name search via `pg_trgm` |
| `instalaciones` | `(tipo, normalized_nombre)` | Unique | Facility dedup per type |
| `instalaciones` | `created_at` WHERE `geocoded_at IS NULL` | Partial B-tree | Geocoding worker's pending-queue scan |
| `ubicaciones` | `(instalacion_id, normalized_detalles)` | Unique | Location dedup per facility+ward |

## Geocoding

`direccion`, `lat`, and `lon` on `instalaciones` are filled by a background worker (see the
[ETL diagram](etl-diagram.md)). `geocoded_at` is the queue marker: `NULL` means the facility
still needs an address; the worker claims those rows (`FOR UPDATE SKIP LOCKED`), calls
OpenStreetMap Nominatim, and stamps `geocoded_at`. A client-supplied `direccion` is stored on
ingestion and pre-marks the row done.
