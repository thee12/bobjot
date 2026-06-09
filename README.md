# AI Internship Application Assistant

AI Internship Application Assistant is an AI-assisted resume tailoring and job discovery platform for internships and entry-level roles.

The project now includes a local FastAPI backend over the typed service and
persistence layers. It supports resume ingestion, deterministic local job
search, analysis, optimization, export, and application tracking.

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
  api/                 FastAPI app factory, schemas, dependencies, and routers.
  cli/                 Developer-facing application tracker commands.
  config/              Runtime settings and environment configuration.
  domain/models/       Core Pydantic models shared across the system.
  services/            Parsing, analysis, scoring, optimization, and rendering.
  storage/             SQLAlchemy database and repository abstractions.
tests/                 Unit and API integration tests.
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

## FastAPI Backend

Run the local development API:

```bash
uvicorn ai_internship_assistant.api.main:app --reload
```

OpenAPI documentation is available at `http://localhost:8000/docs`. This phase
has no authentication or user isolation and is intended only for trusted local
development. Do not expose it to the public internet or use it as a multi-user
service.

Supported API environment variables:

```text
JOBBOT_DATABASE_URL=sqlite:///data/applications.db
JOBBOT_EXPORT_DIR=generated_resumes
JOBBOT_ENABLE_LLM=false
JOBBOT_OPENAI_MODEL=gpt-4.1-mini
JOBBOT_ENV=local
OPENAI_API_KEY=
```

The default API container uses `MockJobSource`, rule-based job analysis, and a
rule-based bullet rewriter, so job search and optimization do not call external
providers. Resume uploads use an injected parser in tests; setting
`JOBBOT_ENABLE_LLM=true` with `OPENAI_API_KEY` configures the existing OpenAI
structured-output resume parser.

Upload a resume:

```bash
curl -X POST http://localhost:8000/resumes/upload \
  -F "file=@resume.pdf" \
  -F "parse_with_llm=true"
```

Search and optionally save ranked mock jobs:

```bash
curl -X POST http://localhost:8000/jobs/search \
  -H "Content-Type: application/json" \
  -d '{"resume_id":"resume_123","max_results":10,"save_results":true}'
```

Run safe optimization and export a stored version:

```bash
curl -X POST http://localhost:8000/optimization/run \
  -H "Content-Type: application/json" \
  -d '{"resume_id":"resume_123","saved_job_id":"job_456","export_formats":["docx","pdf"]}'

curl -X POST http://localhost:8000/exports/resume-version/version_789 \
  -H "Content-Type: application/json" \
  -d '{"formats":["markdown","docx","pdf"]}'
```

Create and update an application:

```bash
curl -X POST http://localhost:8000/applications \
  -H "Content-Type: application/json" \
  -d '{"saved_job_id":"job_456","resume_version_id":"version_789","status":"applied"}'

curl -X PATCH http://localhost:8000/applications/application_123/status \
  -H "Content-Type: application/json" \
  -d '{"status":"interviewing","note":"Recruiter screen scheduled."}'
```

Uploads are limited to 10 MB PDF/DOCX files, checked by extension and file
signature, sanitized, and deleted after extraction. Downloads use opaque
application-generated IDs and cannot address arbitrary filesystem paths.
Ordinary saved-job responses omit provider `raw_data`.

Run API integration tests without live LLM or external job calls:

```bash
pytest tests/test_api.py
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
  -> RuleBasedJobDescriptionAnalyzer.analyze()
  -> JobAnalysis(...)
  -> optional OpenAIJobDescriptionAnalyzer / HybridJobDescriptionAnalyzer
  -> SkillGapAnalyzer.analyze(CandidateProfile, JobAnalysis)
  -> SkillGapReport(...)
  -> ATSMatchScoringService.score(Resume, CandidateProfile, JobAnalysis, SkillGapReport)
  -> ATSMatchReport(...)
  -> ResumeOptimizationPlanner.create_plan(...)
  -> ResumeOptimizationPlan(...)
  -> OpenAIResumeBulletRewriter.rewrite(BulletRewriteRequest)
  -> BulletRewriteResult(...)
  -> FullResumeOptimizer.optimize(ResumeOptimizationRequest)
  -> OptimizedResumeResult(...)
  -> ResumeVersioningService.save_optimized_resume(...)
  -> StoredResumeVersion(...)
  -> MarkdownResumeRenderer.render(...)
  -> RenderedResume(...)
  -> DocxResumeRenderer.render_to_file(...) / PdfResumeRenderer.render_to_file(...)
  -> ATS-friendly resume artifact
  -> ApplicationTrackingService.create_application(...)
  -> tracked application, notes, status history, and follow-up dates
  -> jobbot CLI
  -> developer-operable application tracker
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

### Job Description Analysis

`RuleBasedJobDescriptionAnalyzer` converts a standardized `JobPosting` into a
provider-independent `JobAnalysis`. It cleans HTML and repeated lines, preserves
source wording for responsibilities and qualifications, and extracts explicit
skills, tools, languages, frameworks, cloud platforms, cybersecurity terms,
certifications, soft skills, education, experience, internship signals,
seniority signals, and possible disqualifying requirements.

Phase 4A is intentionally deterministic and makes no LLM or external API calls.
Each required or preferred skill includes its source evidence and confidence.
Unclear evidence remains `UNKNOWN`; the analyzer prefers a missing field over an
invented or over-inferred requirement. Results include a text hash, confidence
score, and warnings for sparse, senior-level, unclear, or unusually long
postings.

The structured output is the future input contract for ATS resume/job matching,
skill-gap analysis, and factual resume optimization. Rule dictionaries and
section heuristics are finite and cannot understand every job-posting format.
Future `OpenAIJobDescriptionAnalyzer` and hybrid implementations can implement
the same `JobDescriptionAnalyzer` protocol without changing downstream modules.

### LLM And Hybrid Job Analysis

`OpenAIJobDescriptionAnalyzer` uses OpenAI structured outputs to return the same
validated `JobAnalysis` contract as the deterministic analyzer. It can interpret
messy sections and vague wording, but its prompt strictly requires extraction
from the supplied posting only. Locally controlled job identity, normalized
title, text hash, provenance, and bounded evidence snippets are enforced after
the provider response is validated.

`HybridJobDescriptionAnalyzer` runs rule-based analysis first, then merges a
validated LLM result conservatively:

- LLM section interpretation is preferred for required versus preferred skills.
- Exact rule-based keywords are retained when the LLM misses them.
- ATS keywords and evidence-backed fields are deduplicated.
- Confidence is reduced when role, domain, or seniority classifications disagree.
- Missing keys, timeouts, provider failures, malformed responses, and empty
  descriptions return the rule-based result with a warning.

Structured outputs are required because downstream ATS scoring, skill-gap
analysis, and resume optimization need a stable typed contract. Only job
posting data is sent to this analyzer; it does not receive resumes or personal
candidate information.

Configuration is environment-driven:

```text
OPENAI_API_KEY=
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_MODEL=gpt-4.1-mini
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_TEMPERATURE=0.0
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_TIMEOUT_SECONDS=30
AI_INTERNSHIP_ASSISTANT_JOB_ANALYSIS_MAX_INPUT_LENGTH=30000
AI_INTERNSHIP_ASSISTANT_ENABLE_LLM_ANALYSIS=false
AI_INTERNSHIP_ASSISTANT_ENABLE_HYBRID_ANALYSIS=false
```

LLM and hybrid analysis are disabled by default for safe local development.
Every LLM call has cost and latency, and structured extraction can still
misclassify ambiguous language. Hybrid fallback and explicit analysis
provenance make those limitations visible to downstream modules.

### Skill Gap Analysis

`SkillGapAnalyzer` deterministically compares a factual `CandidateProfile`
against a structured `JobAnalysis`. It returns an independent `SkillGapReport`
containing direct matches, missing required and preferred skills, certification
gaps, possible disqualifying concerns, learning recommendations, and safe
resume-emphasis opportunities. It makes no LLM or external API calls and does
not mutate either input.

Matching strength is intentionally explicit:

- `EXACT`: candidate and job terminology match case-insensitively.
- `NORMALIZED`: a centralized alias map proves equivalence, such as `Python3`
  to `Python`, `AWS` to `Amazon Web Services`, or `CompTIA Security+` to
  `Security+`.
- `RELATED`: a conservative relationship exists, but it is not a direct claim.
  Related evidence creates an emphasis opportunity only.
- `NONE`: reserved for consumers that need to represent no match.

Every missing skill has `safe_to_add_to_resume=false`. Related skills are also
not safe direct claims. For example, Wireshark may support careful emphasis
around packet analysis, but the system must not claim packet-analysis
experience unless that evidence exists in the candidate profile. Certification
recommendations likewise tell the candidate to learn about or pursue a
credential, never to add an unearned credential.

The report is the safety contract for future resume optimization: direct and
normalized matches identify existing facts that may be emphasized; related
opportunities explain cautious wording; gaps identify terms that must not be
claimed. Current matching uses finite alias and relationship dictionaries and
cannot understand every semantic relationship.

### Estimated ATS Match Scoring

`ATSMatchScoringService` estimates how well the candidate's current factual
resume and profile align with one structured job description. It produces an
explainable `ATSMatchReport` with component scores, keyword coverage,
required/preferred skill coverage, certification coverage, role, experience,
education alignment, resume-section scores, concern penalties, optimization
priority, and safety-aware guidance.

This is an internal deterministic heuristic, not a guarantee of success in any
real applicant tracking system. Proprietary ATS products use different,
undisclosed ranking and filtering behavior.

Default component weights are centralized in `ATSMatchScoringConfig`:

- required skill coverage: 30%
- ATS keyword coverage: 25%
- role alignment: 15%
- preferred skill coverage: 10%
- certification coverage: 7.5%
- experience-level alignment: 7.5%
- education alignment: 5%

Concern penalties are applied after weighted scoring. Estimated recommendation
levels are `EXCELLENT_MATCH` (90+), `STRONG_MATCH` (80+), `GOOD_MATCH` (70+),
`POSSIBLE_MATCH` (60+), `WEAK_MATCH` (40+), and `NOT_RECOMMENDED` (below 40).
Optimization priority separately estimates whether factual tailoring is likely
to be useful.

The ATS report respects the skill-gap safety contract. Missing skills with
`safe_to_add_to_resume=false` remain missing and guidance explicitly says not
to add them without actual evidence. Section-level opportunities may suggest
where existing facts could be emphasized, but this phase does not rewrite the
resume.

Job fit ranking and ATS match scoring answer different questions:

- Job fit ranking: should the candidate consider this job?
- Estimated ATS match scoring: how well does the current resume align with this
  job description?

### Resume Optimization Planning

`ResumeOptimizationPlanner` creates a strict, deterministic safety contract
before any resume rewriting occurs. It consumes the original `Resume`,
`CandidateProfile`, `JobAnalysis`, `SkillGapReport`, and `ATSMatchReport`, then
returns a separate `ResumeOptimizationPlan`. It does not rewrite bullets,
change resume content, or call an LLM.

Planning happens before rewriting so a future optimizer receives explicit
permissions and prohibitions rather than an unconstrained instruction to
"tailor this resume." The plan identifies:

- sections and existing skills to reorder or emphasize
- existing projects and experience entries to feature
- keywords supported by direct resume evidence
- related terms that require cautious wording
- unsupported keywords that must not be added
- forbidden claims, factuality risks, and mitigations
- learning recommendations for missing skills
- a conservative, non-guaranteed score-improvement range

Keyword safety statuses are:

- `SAFE_TO_INCLUDE`: direct factual evidence supports the keyword.
- `SAFE_TO_EMPHASIZE`: existing wording or evidence supports cautious emphasis.
- `RELATED_ONLY`: related evidence exists, but the exact keyword is not a direct claim.
- `NOT_SAFE_TO_INCLUDE`: no supporting candidate evidence exists.
- `LEARNING_RECOMMENDATION_ONLY`: keep the term out of the resume until genuine
  experience or a completed project supports it.

Forbidden claims make unsupported language explicit. For example, when Splunk
is missing, the plan may prohibit claims such as "Used Splunk" or "Built
production solutions with Splunk." Future rewriting modules must treat
`ResumeOptimizationPlan` as an allowlist and denylist: they may not add facts,
technologies, certifications, metrics, projects, employers, dates, or
experience outside the plan and source resume.

Deterministic planning has finite keyword and phrase-awareness. A human should
review cautious emphasis recommendations before generating a final resume.

### Safe Resume Bullet Rewriting

Bullet rewriting is isolated to one bullet at a time. A
`BulletRewriteRequest` contains the original bullet, parent section/item,
candidate evidence, target job, and the optimization plan's safe keywords,
related keywords, unsafe keywords, and forbidden claims. The versioned
`resume-bullet-rewrite-v1` prompt sends only that constrained bullet-level
context to OpenAI structured outputs.

`OpenAIResumeBulletRewriter` never trusts provider output directly. Every
proposed bullet passes through `BulletRewriteSafetyValidator`, which rejects:

- unsafe keywords or forbidden claims
- technologies absent from allowed evidence
- new metrics absent from the original bullet or evidence
- unsupported production, enterprise, SOC, or security experience scope
- major meaning changes, vague output, empty output, or excessive length

Rejected output returns the exact original bullet with structured safety
violations and `FALLBACK_ORIGINAL` provenance. Provider failures, timeouts, and
malformed responses use `RuleBasedResumeBulletRewriter`, which may only improve
capitalization or punctuation and never introduces keywords or claims.

Safe and related keywords are permissions, not instructions to stuff keywords.
Related terms may only appear when candidate evidence supports the wording.
Existing metrics may be preserved; metrics may never be created. This phase
does not rewrite full sections in one shot.

### Full Resume Optimization

`FullResumeOptimizer` assembles a complete structured `OptimizedResume` from the
original resume, candidate and job evidence, skill-gap and ATS reports, the
optimization plan, and an injected `ResumeBulletRewriter`. It never sends the
entire resume to an LLM. Deterministic orchestration handles section, skill,
project, and experience ordering; configurable limits handle approximate
one-page trimming; only individual bullets cross the rewriter boundary.

The optimization plan is a mandatory safety contract. Planned skills absent
from the source are blocked, unsupported and learning-only keywords remain
missing, and certifications, technologies, education, employers, roles, and
dates are copied from the original resume. Every proposed bullet is locally
validated again even if the rewriter reports it as safe. One failed or unsafe
bullet preserves its original text and cannot fail the whole resume.

Every decision produces a `ResumeChange` with the original and new values,
reason, evidence, and safety status. `ResumeOptimizationSafetyReport` records
blocked changes and any final unsafe keywords, forbidden claims, invented
technologies, or invented metrics. Strict mode returns an original-content
`OptimizedResume` when any unsafe change is attempted. Non-strict mode keeps
safe changes while rejecting unsafe ones.

The result includes a conservative estimated improvement range scaled from the
planner's estimate and the safe changes actually completed. It is not a
guaranteed ATS score. `OptimizedResume` is a rendering-neutral persistence
contract; DOCX/PDF templates, version storage, and rescoring remain future
work.

### Resume Versioning And Persistence

Resume persistence treats the master resume and every tailored resume as
separate versioned artifacts. `ResumeVersioningService.save_master_resume()`
stores parsed structured resume JSON and optional source-file metadata, never
the raw PDF or DOCX bytes. Duplicate master sources are detected with normalized
SHA-256 hashes. Saving an optimized result always creates a new immutable
version and never overwrites the master or an earlier tailored version.

SQLite is the Phase 5D default, implemented through SQLAlchemy repositories so
services do not depend on database-specific SQL. The migration-friendly schema
contains:

- `master_resumes`: source-of-truth parsed resumes and non-binary upload metadata
- `resume_versions`: optimized resume, plan, skill-gap report, ATS report,
  safety report, change log, score estimates, and target-job linkage
- `jobs`: minimal standardized job and optional analysis records

Complex Pydantic contracts are serialized consistently as JSON and reconstructed
as typed domain models. Each artifact records a model schema version and emits a
compatibility warning when it differs from the current version. Lightweight
version summaries avoid deserializing full resume contents for list views.

Readable version names are generated from target role and company. Re-optimizing
for the same job creates a new suffix such as `v2`. Only metadata notes may be
updated; optimized resume content remains immutable. A lightweight comparison
service currently compares score estimates and change-type counts, leaving
semantic content diffing to a future UI phase.

Configure persistence with:

```text
AI_INTERNSHIP_ASSISTANT_DATABASE_URL=sqlite:///data/applications.db
AI_INTERNSHIP_ASSISTANT_SQLITE_FILE_PATH=data/applications.db
AI_INTERNSHIP_ASSISTANT_ENABLE_PERSISTENCE=true
```

Persistence tests use isolated in-memory SQLite databases:

```bash
pytest tests/test_resume_versioning.py
```

Production deployment should migrate the SQLAlchemy schema to PostgreSQL and
add encryption at rest, access controls, secure deletion, authentication, and
audit logs. Resume contents and PII must never be written to application logs.

### Application Tracking

`ApplicationTrackingService` provides the persistence boundary for a
lightweight internship-application CRM. A `SavedJob` is a durable snapshot of a
job the user wants to retain; a `JobApplication` is the separate pipeline
record created only when the user intends to track an application. Saving a job
does not mark it as applied.

The application-tracking schema extends the existing SQLite/SQLAlchemy
persistence layer:

- `saved_jobs`: job snapshots, normalized duplicate keys, optional job analysis,
  ATS report, fit score, ATS score, and last-seen time
- `job_applications`: status, optional resume-version linkage, milestone dates,
  follow-up date, source, and private summary notes
- `application_notes`: append-only typed notes
- `application_status_history`: chronological old/new status transitions

Saved-job deduplication reuses `JobNormalizationService`. Matching normalized
apply URLs, source URLs, provider IDs, or company/title/location fingerprints
refresh `last_seen_at` rather than silently creating another record.
`allow_duplicate=True` is available for an explicit user decision.

Application statuses include planned, ready to apply, applied, follow-up
needed, interview stages, offer, rejected, withdrawn, and closed. Transitions
are intentionally permissive and always recorded. Entering milestone statuses
sets the corresponding timestamp only when it is still empty, preserving the
first known applied, response, rejection, offer, or withdrawal time.

Applications may reference an immutable optimized resume version. The foreign
key uses nullable `SET NULL` behavior so future resume-version cleanup cannot
destroy application history. List queries return lightweight
`JobApplicationSummary` values and support status, company, role, source,
applied-date range, due follow-up, interview, and resume-version filters.
Follow-up queries exclude rejected, offered, withdrawn, and closed records.

```python
saved = tracking.save_job(job, job_analysis, ats_report, fit_score=86.0)
application = tracking.create_application(saved.id, resume_version.id)
application = tracking.update_application_status(
    application.id,
    ApplicationStatus.APPLIED,
    "Applied through the company website.",
)
tracking.set_follow_up_date(application.id, date(2026, 6, 16))
due = tracking.list_applications(ApplicationFilters(needs_follow_up=True))
```

Tracker tests use isolated in-memory SQLite databases:

```bash
pytest tests/test_application_tracking.py
```

Application notes and outcome history are sensitive career data. The tracker
does not send email, schedule calendars, automate applications, store
credentials, or log private notes and serialized resume/job contents.

### Application Tracker CLI

The `jobbot` Typer CLI makes the application tracker usable before a frontend
or API exists. It is intentionally thin: commands parse and display data while
`ApplicationTrackingService` owns validation, relationships, status behavior,
and repository operations.

Install the project and initialize the configured database by running any
command:

```bash
python -m pip install -e .
jobbot --help
jobbot jobs list
```

The CLI resolves its database in this order:

1. global `--db-url`
2. `JOBBOT_DATABASE_URL`
3. `AI_INTERNSHIP_ASSISTANT_DATABASE_URL`
4. development default `sqlite:///data/applications.db`

For example:

```bash
jobbot --db-url sqlite:///data/dev-tracker.db jobs list
```

Save and inspect jobs:

```bash
jobbot jobs save --file examples/jobs/soc_analyst_intern.json
jobbot jobs list --company "Example Security" --active-only
jobbot jobs show <saved_job_id>
jobbot jobs show <saved_job_id> --json
```

`jobs save` accepts `JobPosting`-compatible JSON and optional
`--analysis-file` and `--ats-file` structured JSON inputs. The sample under
`examples/jobs/` shows the minimum practical format. JSON is validated before
the service is called; this command never scrapes or makes network requests.

Track an application:

```bash
jobbot applications create --job <saved_job_id> --resume-version <resume_version_id>
jobbot applications status <application_id> APPLIED --note "Applied through company website."
jobbot applications followup <application_id> 2026-06-20
jobbot applications note <application_id> "Recruiter requested availability." --type INTERVIEW
jobbot applications list --status APPLIED
jobbot applications due
jobbot applications show <application_id>
jobbot applications history <application_id>
jobbot applications link-resume <application_id> <resume_version_id>
```

Statuses and note types are case-insensitive at the CLI boundary. Key save,
list, and show commands support `--json` for automation. Expected input,
lookup, JSON, and database errors produce concise messages without stack
traces. The CLI creates no reminders, notifications, emails, calendar events,
applications, or browser activity.

CLI tests use temporary SQLite files and make no LLM or network calls:

```bash
pytest tests/test_cli.py
```

### Markdown Resume Rendering

`MarkdownResumeRenderer` converts either a source `Resume` or an
`OptimizedResume` into deterministic, human-readable Markdown. Rendering is a
presentation-only stage: it does not optimize, rewrite, infer, score, or add
content. Existing section order, bullets, technologies, certifications,
education, contact facts, and additional sections are preserved.

The default output is intentionally simple and ATS-friendly:

- plain contact values separated by pipes
- simple Markdown headings
- dash bullets
- no tables, columns, icons, images, nested bullets, or decorative separators
- plain URLs rather than Markdown links

`ResumeRenderOptions` controls section visibility, section order, bullet limits,
heading and bullet styles, metadata comments, and source artifact IDs. Strict
ATS mode forces dash bullets and can be paired with `ATS_SIMPLE` headings for
plain uppercase section labels. Missing data is omitted rather than replaced
with placeholders. Bullet limits only affect the rendering and produce
warnings; source models are never mutated.

`render_to_file()` writes UTF-8 Markdown, creates parent directories, sanitizes
filenames, generates readable filenames when given an output directory, records
a SHA-256 content hash, and refuses to overwrite an existing file unless
explicitly allowed. The Markdown renderer rejects non-`.md` file extensions.

Markdown is the canonical simple text representation for previewing, debugging,
comparison, and export pipelines. DOCX and PDF renderers implement the same
formatting-only safety boundary without adding resume facts or changing
optimization behavior.

### ATS-Friendly DOCX Export

`DocxResumeRenderer` exports a source `Resume` or stored `OptimizedResume`
directly to a Microsoft Word `.docx` file without rerunning optimization. It is
a formatting-only implementation of the same renderer boundary: existing
contact facts, education, certifications, skills, projects, experience,
additional sections, technologies, and bullets are preserved exactly.

The default template is a compact ATS-safe Word layout derived from the
`compact_reference_guide` document preset with deliberate resume overrides:

- Calibri 10.5 pt body, 15 pt candidate name, and 11.5 pt section headings
- 0.6-inch margins and compact paragraph spacing
- plain black typography and simple uppercase headings
- real Word bullet-list paragraphs
- no tables, columns, images, icons, text boxes, shapes, or important
  header/footer content

`DocxRenderOptions` supports font and margin controls, compact spacing, section
order, project and experience limits, bullet limits, source artifact IDs, and
explicit overwrite permission. Trimming affects only the exported view,
produces warnings, and never mutates the structured resume.

`render_to_file()` creates parent directories, sanitizes filenames, creates
collision suffixes for directory-based exports, rejects non-`.docx`
destinations, calculates byte size and SHA-256 metadata, and refuses explicit
file overwrites unless allowed. Generated files should remain in a private,
configurable directory:

```text
AI_INTERNSHIP_ASSISTANT_RESUME_OUTPUT_DIR=generated_resumes
```

The DOCX exporter differs from Markdown rendering only in presentation and
artifact format. Both render existing facts and share the same safety boundary.
Perfect one-page enforcement remains future work.

### ATS-Friendly PDF Export

`PdfResumeRenderer` exports a source `Resume` or stored `OptimizedResume`
directly to a selectable-text `.pdf` without rerunning optimization or calling
an LLM. It uses ReportLab for direct text-based generation and shares the
canonical section extraction and ordering behavior of `MarkdownResumeRenderer`.

The default PDF uses Letter paper, Helvetica 10.5 pt body text, compact
0.6-inch margins, plain uppercase headings, simple bullets, and a single-column
layout. It contains no images, tables, icons, text boxes, columns, remote fonts,
decorative graphics, hidden text, or important header/footer content.
Supported content includes contact facts, summary, education, certifications,
grouped skills, projects, experience, technologies, bullets, and generic
additional sections.

`PdfRenderOptions` controls standard font choice, typography, margins, line
spacing, page size, compact mode, section and bullet limits, source artifact
IDs, extractable-text validation, and explicit overwrite permission. Length
limits affect only the exported view and produce warnings. The exporter records
page count and warns when output exceeds one page; it never silently removes a
section or mutates the source resume.

`render_to_file()` creates private parent directories, sanitizes filenames,
creates collision suffixes for directory exports, rejects non-`.pdf`
destinations, sets safe document metadata, calculates byte size and SHA-256,
and optionally reopens the result with `pdfplumber` to verify key text is
extractable. Generated files use the same configurable private output location:

```text
AI_INTERNSHIP_ASSISTANT_RESUME_OUTPUT_DIR=generated_resumes
```

PDF text extraction varies across applicant tracking systems. Prefer DOCX for
ATS uploads when the employer accepts it; use PDF when the employer specifically
requests PDF or when preserving a stable visual artifact matters.
