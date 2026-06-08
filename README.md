# AI Internship Application Assistant

AI Internship Application Assistant is an AI-assisted resume tailoring and job discovery platform for internships and entry-level roles.

The Phase 1 scaffold defines the project architecture only. It does not implement scraping, LLM prompts, API endpoints, resume optimization, or generation logic.

## Goals

- Accept a user's master resume in PDF or DOCX format.
- Parse resumes into structured data.
- Match user qualifications and preferences to internships and entry-level jobs.
- Analyze job descriptions for ATS keywords, skills, technologies, certifications, and action verbs.
- Generate tailored resume versions without inventing experience, credentials, projects, tools, dates, metrics, or achievements.
- Score ATS compatibility.
- Store application history and generated resume versions.

## Non-Negotiable AI Rules

The optimizer must never fabricate:

- jobs
- certifications
- projects
- technologies
- employers
- dates
- years of experience
- metrics or achievements

It may only reorder, rewrite, emphasize, align keywords, and improve readability using facts already present in the source resume.

## Project Layout

```text
src/ai_internship_assistant/
  config/              Runtime settings and environment configuration.
  domain/models/       Core Pydantic models shared across the system.
  services/            Future service-layer modules for parsing, analysis, scoring, and generation.
  storage/             Future database and repository abstractions.
tests/                 Test suite skeleton.
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## Quality Checks

```bash
pytest
ruff check .
mypy src
```

## Current Status

The current extraction pipeline supports:

```text
Resume PDF/DOCX
  -> extract_text()
  -> raw text
  -> OpenAIResumeParser.parse()
  -> Resume(...)
  -> ResumeValidator.validate()
  -> ValidationReport(...)
  -> CandidateProfileGenerator.generate()
  -> CandidateProfile(...)
  -> JobSearchQueryGenerator.generate()
  -> JobSearchQuerySet(...)
  -> JobSearchService.search_all()
  -> JobSearchResultSet(...)
  -> standardized JobPosting objects
```

The parser performs extraction only. It does not optimize, rewrite, score, or
tailor resumes.

The candidate profile is the normalized downstream contract for future job
discovery, ranking, ATS scoring, skill-gap analysis, and optimization modules.
The current generator is deterministic and rules-based. It may classify
existing evidence into domains and likely target roles, but it never invents
skills, credentials, projects, technologies, education, or work history.

The job search query generator creates prioritized, role-oriented searches from
the candidate profile and optional location, remote, employment-type, and role
preferences. It performs no web searches. Future job-source integrations will
consume the structured `JobSearchQuery` objects.

The job source layer defines a provider-neutral `JobSource` interface. Future
Greenhouse, Lever, and company career-page integrations will normalize their
provider responses into the same `JobPosting` model. The included
`MockJobSource` is development-only and performs no network calls.

### Greenhouse Source

`GreenhouseJobSource` is the first real provider adapter. It uses only the
public, unauthenticated Greenhouse Job Board GET endpoint and never submits
applications or accesses private recruiting data.

Add boards by constructing `GreenhouseCompanyConfig` entries with:

- `company_name`: display name stored on normalized postings
- `board_token`: public token from `boards.greenhouse.io/{board_token}`
- `base_url`: optional public board URL
- `enabled`: whether the board should be searched
- `tags`: editable metadata for future filtering

The checked-in seed configuration is a disabled placeholder. Requests use a
clear user agent, timeout, optional delay between company boards, and no
automatic rate-limit bypass. Unit tests use mocked HTTP responses only.

### Lever Source

`LeverJobSource` uses only Lever's public published-postings GET endpoint:
`https://api.lever.co/v0/postings/{company_slug}?mode=json`. It never accesses
private postings, submits applications, or uses authentication credentials.

Add sites by constructing `LeverCompanyConfig` entries with:

- `company_name`: display name stored on normalized postings
- `company_slug`: public site name from `jobs.lever.co/{company_slug}`
- `base_url`: optional public Lever job-site URL
- `enabled`: whether the site should be searched
- `tags`: editable metadata for future filtering

Lever exposes a JSON list directly, while Greenhouse wraps jobs in a board
response object. Both adapters use shared deterministic matching and normalize
their provider-specific fields into `JobPosting`. Lever list sections are
classified into responsibilities, requirements, and preferred qualifications
when headings make that classification clear. Unit tests use mocked HTTP
responses only.

### Job Normalization And Deduplication

`JobNormalizationService` creates non-mutating normalized views of provider
postings. It standardizes common title variants, a small expandable company
alias set, locations, remote labels, tracking parameters, and description
formatting. Stable fingerprints use normalized company, title, and location.

`JobDeduplicationService` merges only high-confidence duplicates:

- identical normalized apply URL: `1.0`
- identical normalized source URL: `0.95`
- same normalized company, highly similar title, and same location: `0.85`

Possible duplicates below the automatic merge threshold remain separate and
produce warnings. Canonical selection prefers the posting with the most
complete description, followed by apply URL availability, direct ATS source,
posted date, and structured fields. Duplicate groups retain every original job
for traceability.

`JobSearchService(..., normalize=True, deduplicate=True)` enables the clean-job
pipeline. Both options default to `False` to preserve existing raw-result
behavior.

### Job Fit Ranking

`JobFitScoringService` deterministically scores clean jobs against a
`CandidateProfile`. It produces separate component scores, matched and missing
skills, matched certifications and keywords, disqualifying flags, warnings,
and a human-readable explanation.

Default component weights are centralized in `JobFitScoringConfig`:

- role match: 25%
- skill match: 25%
- domain match: 15%
- experience level: 15%
- employment type: 10%
- certification match: 5%
- location match: 3%
- keyword match: 2%

Recommendation levels are `STRONG_MATCH` (90+), `GOOD_MATCH` (75+),
`POSSIBLE_MATCH` (60+), `WEAK_MATCH` (40+), and `NOT_RECOMMENDED` (below 40).
Flags such as senior-level role, clearance, advanced degree, years-of-
experience, unrelated domain, and location mismatch reduce scores but do not
automatically remove jobs.

Scoring is rule-based and explainable. It currently relies on finite,
configurable keyword maps and deterministic token matching. Future embedding or
LLM components can augment individual score components without replacing the
ranking result contract.
