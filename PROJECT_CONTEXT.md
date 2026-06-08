# Project Context

## Product Summary

AI Internship Application Assistant helps users discover suitable internships and entry-level roles, analyze job descriptions, and generate tailored resume versions while preserving factual accuracy.

## Architectural Intent

The project uses a modular `src` layout with clear boundaries:

- Domain models represent resumes, jobs, extracted ATS signals, scores, generated resume versions, and application history.
- Service modules will orchestrate parsing, job discovery, analysis, scoring, optimization, and document generation.
- Storage modules will isolate database concerns from business workflows.
- Configuration is centralized and typed.

## Candidate Profile Architecture

`CandidateProfile` is the normalized representation intended for most future
downstream modules. The rules-based `CandidateProfileGenerator` consumes a
`Resume` and `ValidationReport`, organizes existing skills, classifies domains
and experience level from explicit evidence, recommends evidence-supported
target role categories, and produces a confidence score.

The generator may classify evidence but must never add factual claims. Its
current limitations are intentional: domain and role maps are deterministic,
finite, and designed to be replaced or extended behind the `ProfileGenerator`
boundary without changing downstream consumers.

## Job Search Query Architecture

`JobSearchQueryGenerator` converts a `CandidateProfile` and optional
`JobSearchPreferences` into a deduplicated `JobSearchQuerySet`. Queries are
organized into high, medium, and low priority tiers according to primary and
secondary domain alignment. User preferences refine locations, remote or hybrid
modes, employment types, desired roles, and exclusions without discarding
candidate-profile evidence.

The generator is deterministic and source-agnostic. It does not search the
internet. Future Greenhouse, Lever, company-career-page, and other integrations
can consume `JobSearchQuery` objects directly without analyzing the candidate
profile themselves.

## Job Source Architecture

Every future provider integration implements the `JobSource` interface and
returns standardized `JobPosting` objects. Provider-specific payloads remain
available in `raw_data`, while normalized title, company, location, employment
type, work arrangement, canonical URL, and fingerprint fields provide one
consistent contract for downstream ranking, ATS analysis, and deduplication.

`JobSearchService` runs a `JobSearchQuerySet` across configured sources. Expected
provider failures become structured `JobSourceError` records, allowing results
from successful sources to remain available. Unexpected programming errors are
not silently swallowed.

`MockJobSource` returns realistic fake postings for tests and local development.
It must not be treated as a production provider and performs no HTTP requests.

## Greenhouse Integration

`GreenhouseJobSource` implements `JobSource` using Greenhouse's public Job Board
API list-jobs endpoint with `content=true`. A `GreenhouseCompanyConfig` defines
each editable company board by its public `board_token`. The adapter filters
jobs deterministically, normalizes matches into `JobPosting`, preserves the raw
Greenhouse payload, and records board-level failures without discarding results
from successful boards.

The integration uses no private APIs, authentication bypasses, cookies, login
pages, application automation, or rate-limit avoidance. The adapter treats
Greenhouse `updated_at` as the best available public date approximation for
`posted_date`; downstream modules should not assume it is the original posting
date. Tests use `httpx.MockTransport` and fixtures under
`tests/fixtures/greenhouse/`, so the test suite makes no live network calls.

## Lever Integration

`LeverJobSource` implements `JobSource` using Lever's public Postings API in
JSON mode. A `LeverCompanyConfig` identifies each editable public site by its
`company_slug`, matching the public URL pattern
`jobs.lever.co/{company_slug}`. The adapter defensively maps Lever posting
fields, categories, list sections, salary ranges, workplace type, and creation
timestamps into the standardized `JobPosting` contract while preserving the
raw posting payload.

Greenhouse returns a board response containing a `jobs` list, while Lever
returns the postings list directly and provides richer structured categories
and list sections. Both sources share deterministic role, location, seniority,
employment-type, and work-arrangement helpers.

The Lever integration uses published public data only. It does not use private
APIs, user cookies, logged-in pages, application POST endpoints, browser
automation, or rate-limit avoidance. Tests use `httpx.MockTransport` and
fixtures under `tests/fixtures/lever/`, so no live network calls occur.

## Phase 1 Scope

This scaffold includes:

- package structure
- project metadata
- dependency declarations
- typed Pydantic domain models
- placeholder modules with future responsibilities documented
- test package skeleton

This scaffold intentionally excludes:

- resume parsing logic
- job scraping logic
- LLM prompts
- FastAPI routes
- optimization logic
- ATS scoring algorithms
- database schema migrations

## AI Safety Constraint

The system must preserve truthfulness. Any future optimization component must be constrained to facts present in the user's source resume or explicitly supplied by the user. It may improve presentation but must not create new factual claims.
