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
        FACILITY["find_or_create_instalacion / _ubicacion<br/>normalize + dedup"]
        API --> VALIDATE --> UPSERT --> FACILITY
    end

    FACILITY -->|"client gave direccion → store it,<br/>geocoded_at = now()"| DB
    FACILITY -->|"no direccion → geocoded_at = NULL<br/>(enqueued)"| DB

    DB[("PostgreSQL<br/>instalaciones · ubicaciones · found_people")]

    subgraph worker["Background geocoding worker (app/geocoding_worker.py)"]
        LOOP["run_worker loop<br/>(started in app lifespan)"]
        CLAIM["claim_pending<br/>WHERE geocoded_at IS NULL<br/>FOR UPDATE SKIP LOCKED"]
        OSM{{"OpenStreetMap Nominatim<br/>app/geocoding.py"}}
        WRITE["write direccion / lat / lon<br/>stamp geocoded_at"]
        LOOP --> CLAIM --> OSM --> WRITE
    end

    DB -->|"pending facilities"| CLAIM
    WRITE -->|"update"| DB

    DB -->|"GET /api/v1/found-people (public search)"| CONSUMERS["War Room UI / consumers"]

    classDef ext fill:#fff3cd,stroke:#d39e00;
    class OSM,BOT,OCR ext;
```

## Outcome handling in the worker

For each claimed facility the worker calls Nominatim and acts on the outcome:

| Outcome | Condition | Action |
|---|---|---|
| **matched** | OSM returned a result | write `direccion`/`lat`/`lon`, stamp `geocoded_at` (done) |
| **no match** | HTTP 200, empty list | stamp `geocoded_at` only — stop retrying a dead end |
| **transient** | timeout / network / 5xx | leave `geocoded_at` NULL — retried next cycle |

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
