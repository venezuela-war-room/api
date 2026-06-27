# ETL / Data-Flow Diagram

How records move from volunteer sources into the searchable registry, and how facility
addresses are filled asynchronously by the background geocoding worker.

```mermaid
flowchart TD
    subgraph sources["Data sources"]
        BOT["edwinvrgs Telegram bot<br/>(official + citizen reports)"]
        OCR["ecrespo OCR CSV<br/>(scripts/import_csv.py)"]
    end

    BOT -->|"POST /api/v1/found-people(/bulk)<br/>X-Admin-Key"| API
    OCR -->|"bulk upsert"| API

    subgraph ingest["Ingestion (request path — no network calls)"]
        API["FastAPI router<br/>app/routers/people.py"]
        VALIDATE["Pydantic validate + clean<br/>app/schemas.py"]
        UPSERT["crud.upsert_person<br/>dedup on source_hash"]
        GATE{"_looks_like_facility<br/>(ubicacion_actual)?"}
        FACILITY["find_or_create_instalacion<br/>normalize + dedup"]
        DETALLE["ubicacion with instalacion_id = NULL<br/>text → detalles (never geocoded)"]
        API --> VALIDATE --> UPSERT --> GATE
        GATE -->|"real place"| FACILITY
        GATE -->|"free text"| DETALLE
    end

    FACILITY -->|"client gave direccion → store it,<br/>geocoded_at = now()"| DB
    FACILITY -->|"no direccion → geocoded_at = NULL<br/>(enqueued)"| DB
    DETALLE --> DB

    DB[("PostgreSQL<br/>instalaciones · ubicaciones · found_people")]

    subgraph worker["Background geocoding worker (app/geocoding_worker.py)"]
        LOOP["run_worker loop<br/>(started in app lifespan)"]
        CLAIM["claim_pending<br/>WHERE geocoded_at IS NULL<br/>FOR UPDATE SKIP LOCKED"]
        OSM{{"OpenStreetMap Nominatim<br/>(query = normalized name)"}}
        MATCH{"OSM match?"}
        DEDUP{"osm_id already<br/>on another facility?"}
        MERGE["merge_instalacion<br/>fold into canonical row"]
        WRITE["write direccion / lat / lon / osm_id<br/>stamp geocoded_at"]
        DEMOTE["demote_instalacion_to_detalle<br/>(no match + no keyword → free text)"]
        LOOP --> CLAIM --> OSM --> MATCH
        MATCH -->|"yes"| DEDUP
        MATCH -->|"no match + named facility"| WRITE
        MATCH -->|"no match + keyword-less"| DEMOTE
        DEDUP -->|"new place"| WRITE
        DEDUP -->|"known place"| MERGE
    end

    DB -->|"pending facilities"| CLAIM
    WRITE -->|"update"| DB
    MERGE -->|"merge + delete dup"| DB
    DEMOTE -->|"detalle + delete facility"| DB

    DB -->|"GET /api/v1/found-people (public search)"| CONSUMERS["War Room UI / consumers"]

    classDef ext fill:#fff3cd,stroke:#d39e00;
    class OSM,BOT,OCR ext;
```

## Outcome handling in the worker

For each claimed facility the worker calls Nominatim and acts on the outcome:

| Outcome | Condition | Action |
|---|---|---|
| **matched** | OSM returned a result | if another facility already has this `osm_id` → `merge_instalacion` into it; else write `direccion`/`lat`/`lon`/`osm_id`, stamp `geocoded_at` |
| **no match** (named facility) | empty list, name has a facility keyword | stamp `geocoded_at`, keep as unconfirmed facility (`osm_id` NULL) — a real place OSM lacks |
| **no match** (keyword-less) | empty list, no facility keyword | `demote_instalacion_to_detalle` — it was free text that slipped the ingest gate |
| **transient** | timeout / network / 5xx | leave `geocoded_at` NULL — retried next cycle |

The worker geocodes the **normalized** facility name (`normalized_nombre`), not the raw one —
Nominatim resolves "hospital domingo luciani" but not "Hosp. Domingo Luciani", and the canonical
query is what makes variants land on the same `osm_id`.

## Key properties

- **Geocoding is off the request path.** Ingestion returns immediately; addresses fill in
  asynchronously. Bulk imports never block on (or get throttled by) Nominatim.
- **The queue is a column, not a broker.** `geocoded_at IS NULL` ⟺ "needs geocoding",
  backed by the partial index `ix_instalaciones_pending_geocode`. New rows enqueue
  automatically; client-supplied addresses are pre-marked done.
- **Safe to scale.** `FOR UPDATE SKIP LOCKED` lets multiple workers/replicas share the
  queue without double-processing. Concurrency defaults to 1 to respect public Nominatim's
  ~1 req/sec policy.
- **Manual drain.** `scripts/backfill_addresses.py` runs the same `process_pending_batch`
  on demand (e.g. without the web app, or when the worker is disabled).
