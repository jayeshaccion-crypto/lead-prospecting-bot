# Data Model: Neo4j Graph Schema & Entity Resolution

**Created**: 2026-08-03 | **Branch**: `007-neo4j-entity-resolution`

## Canonical Node Types

### Company

The single resolved business entity. Identity is `dedup_key`, set once at creation and never changed.

| Property | Type | Nullable | Notes |
|----------|------|----------|-------|
| `dedup_key` | string | no | Immutable identity (UNIQUE constraint). `md5("phone:<last10>")` when phone present, else `md5("name:<normalized>")` / `md5("name:<normalized>|web:<host>")`. |
| `company_name` | string | no | Display name (the spec's conceptual `name` attribute; Clarification Q1). |
| `normalized_name` | string | no | Output of `normalize_company_name` (indexed). |
| `phone` | string | yes | Last scraped value; never overwritten with empty. |
| `email` | string | yes | As above. |
| `website` | string | yes | As above. |
| `address` | string | yes | As above. |
| `industry_code` | string | yes | As above. |
| `first_seen` | datetime | no | Set only on create (never overwritten). |
| `last_seen` | datetime | no | Updated on every match. |
| `sources` | list[string] | no | Directory names; append-if-absent on merge. |
| `lead_score` | int | yes | Governance property (Constitution Data Layer Isolation — data-layer internal). |
| `lead_score_breakdown` | string | yes | JSON string of the score breakdown; data-layer internal. |

### Category

A business category a company is listed under. Merged by `name` (UNIQUE).

### City

A geographic location. Merged by `name` (UNIQUE).

### Source

A directory a company was scraped from. Merged by `name` (UNIQUE).

## Relationship Types

| Relationship | From → To | Properties | Merge key |
|--------------|-----------|------------|-----------|
| `LISTED_IN` | Company → Category | — | (company `dedup_key`, Category `name`) |
| `LOCATED_IN` | Company → City | — | (company `dedup_key`, City `name`) |
| `SOURCED_FROM` | Company → Source | `scraped_at` (datetime), `raw_record_id` (string) | (company `dedup_key`, Source `name`) — one edge per pair |

`raw_record_id` (content-derived, stable across identical re-runs): `f"{source_name}|{company_name}|{primary_contact}".lower()` where `primary_contact` = phone digits if present, else email, else website; whitespace collapsed.

## DDL — Constraints & Indexes

```cypher
CREATE CONSTRAINT company_dedup_key IF NOT EXISTS FOR (c:Company) REQUIRE c.dedup_key IS UNIQUE
CREATE CONSTRAINT source_name IF NOT EXISTS FOR (s:Source) REQUIRE s.name IS UNIQUE
CREATE CONSTRAINT category_name IF NOT EXISTS FOR (cat:Category) REQUIRE cat.name IS UNIQUE
CREATE CONSTRAINT city_name IF NOT EXISTS FOR (city:City) REQUIRE city.name IS UNIQUE
CREATE INDEX company_normalized_name IF NOT EXISTS FOR (c:Company) ON (c.normalized_name)
CREATE INDEX company_name IF NOT EXISTS FOR (c:Company) ON (c.company_name)
```

## Write Queries (canonical MERGEs)

### Q3 — Company

```cypher
MERGE (c:Company {dedup_key: $dk})
ON CREATE SET
  c.company_name = $name,
  c.normalized_name = $norm,
  c.phone = $phone,
  c.email = $email,
  c.website = $website,
  c.address = $address,
  c.industry_code = $industry_code,
  c.first_seen = $now,
  c.last_seen = $now,
  c.sources = $sources
ON MATCH SET
  c.company_name = $name,
  c.normalized_name = $norm,
  c.phone = CASE WHEN $phone IS NOT NULL AND $phone <> '' THEN $phone ELSE c.phone END,
  c.email = CASE WHEN $email IS NOT NULL AND $email <> '' THEN $email ELSE c.email END,
  c.website = CASE WHEN $website IS NOT NULL AND $website <> '' THEN $website ELSE c.website END,
  c.address = CASE WHEN $address IS NOT NULL AND $address <> '' THEN $address ELSE c.address END,
  c.industry_code = CASE WHEN $industry_code IS NOT NULL AND $industry_code <> '' THEN $industry_code ELSE c.industry_code END,
  c.last_seen = $now,
  c.sources = CASE
    WHEN $src_name IS NOT NULL AND NOT $src_name IN COALESCE(c.sources, [])
    THEN COALESCE(c.sources, []) + [$src_name]
    ELSE c.sources
  END
```

### Q4 — LISTED_IN

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (cat:Category {name: $category})
MERGE (c)-[:LISTED_IN]->(cat)
```

### Q5 — LOCATED_IN

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (city:City {name: $city})
MERGE (c)-[:LOCATED_IN]->(city)
```

### Q6 — SOURCED_FROM

```cypher
MATCH (c:Company {dedup_key: $dk})
MERGE (s:Source {name: $source})
MERGE (c)-[r:SOURCED_FROM]->(s)
SET r.scraped_at = $now, r.raw_record_id = $raw_record_id
```

## Normalization Sample (evidence)

`normalize_company_name`: lowercase → punctuation→space → strip suffix set `pvt|ltd|llp|private limited|opc|inc|corp|corporation|llc|limited|co|company|technologies|solutions|services|systems|group|industries|enterprises` → collapse whitespace.

Verified on 38 real names (IndiaMART 28 + Justdial 10 + TradeIndia 13, deduped to 38 unique):

| Input | Normalized |
|-------|------------|
| Codetrex Infotech Pvt. Ltd. | `codetrex infotech` |
| Zentelex Pvt. Ltd. | `zentelex` |
| Taksh IT Solutions Private Limited | `taksh it` |
| Nitai Technologies (OPC) Private Limited | `nitai` |
| Exclserv Solutions Llp | `exclserv` |
| GGM Technologies | `ggm` |
| Presto Infosolutions Pvt Ltd | `presto infosolutions` |
| Beas Consultancy And Services Pvt. Ltd. | `beas consultancy and` |
| Basudeb It Solution | `basudeb it solution` |
| NCR COMPUTERS AND CCTV | `ncr computers and cctv` |
| Wemonde Private Limited | `wemonde` |
| JP. Technology | `jp technology` |
| Sol9x Private Limited | `sol9x` |

Result: **38 distinct inputs → 38 distinct normalized values (0 collisions)**. `Nitai Technologies (OPC) Private Limited → nitai` confirms the `OPC` addition is required and effective.
