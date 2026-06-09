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

## Job Normalization And Deduplication

`JobNormalizationService` creates a separate `NormalizedJobPosting` and never
mutates the original provider posting. Normalization covers common title
variants, a deliberately small company alias map, locations, remote variants,
tracking-free URLs, description whitespace, and deterministic fingerprints.

`JobDeduplicationService` is intentionally conservative. Identical normalized
apply or source URLs are strong duplicate evidence. Text-based merging requires
the same normalized company, highly similar title tokens, and the same known
location. Unknown-location similarities below the merge threshold remain
separate and generate warnings.

Every `JobDeduplicationGroup` preserves a canonical job plus all original
duplicate jobs and sources. Canonical selection favors completeness rather than
provider preference alone. This allows future embedding similarity,
LLM-assisted review, larger alias databases, and user-confirmed duplicate
decisions without changing downstream clean-job consumers.

## Job Fit Ranking

`JobFitScoringService` consumes `CandidateProfile` and clean `JobPosting`
objects. It produces independent `JobFitScore` objects and a deterministic
`RankedJobResultSet`; neither input is mutated. Component weights and flag
penalties are centralized in `JobFitScoringConfig`.

The current rule-based engine scores role, skills, domain, experience level,
employment type, location, certifications, and keywords. It records matched
and missing evidence, disqualifying flags, warnings, and concise explanations.
Ranking sorts by overall score, recommendation level, role relevance, posting
date, company, title, and stable job ID.

Known limitations are deliberate: keyword maps are finite, nearby-location
logic is limited to exact or same-state matching, and deterministic token
matching cannot understand all semantic role relationships. Future embedding,
LLM job-analysis, and ATS components can replace or augment individual scores
without changing downstream ranking consumers.

## Job Description Analysis

`RuleBasedJobDescriptionAnalyzer` is the first implementation of the
`JobDescriptionAnalyzer` protocol. It consumes standardized `JobPosting`
objects and returns immutable-by-convention, strongly typed `JobAnalysis`
results without mutating source postings or making network calls.

The analyzer combines normalized posting fields with selected textual provider
fields, cleans HTML and duplicate lines, and applies centralized term catalogs,
section-aware requirement classification, and conservative regular-expression
checks. Extracted `SkillRequirement` entries preserve evidence and distinguish
required, preferred, nice-to-have, and unknown context. Ambiguous requirements
remain unknown.

The rule-based implementation is explainable and suitable for tests, but its
catalogs and section heuristics are intentionally finite. Future OpenAI and
hybrid analyzers may augment semantic extraction behind the same protocol.
Downstream ATS scoring, skill-gap analysis, and resume optimization should
consume `JobAnalysis` rather than provider-specific raw text.

`OpenAIJobDescriptionAnalyzer` now provides that structured provider-backed
implementation using the versioned `job-description-analysis-v1` prompt. Its
privacy boundary accepts only `JobPosting` fields and never candidate profiles
or resume data. Provider responses are schema-validated, evidence snippets are
bounded, and locally trusted identity and hash fields replace provider-supplied
values.

`HybridJobDescriptionAnalyzer` always creates rule-based analysis first. It
prefers validated LLM section interpretation, retains exact deterministic
keyword matches, deduplicates merged fields, and lowers confidence when role,
domain, or seniority classifications disagree. Any expected LLM failure returns
the rule-based result with a warning instead of interrupting the job pipeline.
Analysis provenance is recorded as `RULE_BASED`, `LLM`, or `HYBRID`.

LLM analysis is opt-in because it adds latency, cost, and provider privacy
considerations. Typed settings control model, temperature, timeout, maximum
input length, and feature flags. The API key is read from `OPENAI_API_KEY` and
must not be committed.

## Skill Gap Analysis

`SkillGapAnalyzer` consumes a `CandidateProfile` and `JobAnalysis` and produces
a separate `SkillGapReport`. It is deterministic, provider-independent, and
does not mutate either input. The report separates matched required and
preferred skills, missing skills, certification gaps, possible disqualifying
concerns, learning recommendations, and resume-emphasis opportunities.

Alias-aware normalization may establish factual equivalence, such as
`Python3`/`Python` or `CompTIA Security+`/`Security+`. Conservative related-skill
mappings can only create emphasis opportunities; they never count as direct
matches and never make a missing skill safe to add to a resume. All missing
skills have `safe_to_add_to_resume=false`.

Overall severity considers required versus preferred gaps, internship
seniority, related evidence, and explicit concerns. It does not make final
legal or employment-eligibility decisions. The finite alias and related-skill
maps are intentionally explainable and can be expanded without changing the
stable report contract consumed by future ATS scoring and resume optimization.

## Estimated ATS Match Scoring

`ATSMatchScoringService` consumes `Resume`, `CandidateProfile`, `JobAnalysis`,
and `SkillGapReport` and returns a separate `ATSMatchReport`. It measures the
current resume's estimated textual and factual alignment with a specific job;
it does not decide whether the job itself is a good target. That remains the
responsibility of `JobFitScoringService`.

The estimated ATS score is deterministic and versioned. Configurable weights
cover required and preferred skills, ATS keywords, certifications, role,
experience level, and education. Explicit skill-gap concerns apply transparent
penalties after weighted scoring. Missing component data receives a neutral
score and a warning instead of a misleading zero.

Keyword matching uses the same conservative alias vocabulary as skill-gap
analysis and scans factual resume/profile evidence across skills, projects,
experience, certifications, education, target roles, and profile terms.
Section scores show where keywords are currently supported. Optimization
guidance respects `safe_to_add_to_resume`; unsupported keywords are never
recommended for direct addition.

`ATSMatchReport` is an internal heuristic and must never be described as a
guaranteed ATS screening result. Real applicant tracking systems vary and use
proprietary behavior. Future resume optimization can use the report to choose
factual emphasis opportunities and identify unsafe missing terms without
changing the scoring contract.

## Resume Optimization Planning

`ResumeOptimizationPlanner` is the mandatory safety stage before future resume
rewriting. It consumes the original resume plus the candidate, job, skill-gap,
and estimated ATS contracts, and returns a separate `ResumeOptimizationPlan`
without mutating any input or generating rewritten content.

The plan classifies important job keywords into direct, cautiously
emphasizable, related-only, unsupported, or learning-only statuses. Direct
resume evidence can authorize inclusion. Related evidence cannot become a
direct claim. Missing skills remain unsafe and generate forbidden claims,
learning recommendations, and factuality-risk mitigations.

Section, skill-ordering, project, and experience plans reference existing
resume evidence only. Nontechnical experience may support communication or
teamwork when those facts are present, but it cannot be recast as technical
experience. Expected score improvement is a conservative range, not a promise.
Major job-fit concerns can mark planning as `SKIP`.

Future bullet rewriting and full-resume generation must consume
`ResumeOptimizationPlan` as a strict allowlist and denylist. They must preserve
the original resume's employers, projects, credentials, technologies, dates,
metrics, responsibilities, and achievements unless an evidence-backed plan
explicitly permits truthful rephrasing or emphasis.

## Safe Resume Bullet Rewriting

`ResumeBulletRewriter` is the provider-neutral interface for rewriting one
bullet at a time. `OpenAIResumeBulletRewriter` uses the versioned
`resume-bullet-rewrite-v1` structured-output prompt, while
`RuleBasedResumeBulletRewriter` provides a formatting-only fallback.
`build_bullet_rewrite_request` converts a `ResumeOptimizationPlan` into the
bullet-level permission boundary used by a rewriter.

Provider output is untrusted until `BulletRewriteSafetyValidator` approves it.
The validator detects unsafe keywords, forbidden claims, unsupported known
technologies, invented metrics, unsupported experience scope, excessive
length, vague output, and major meaning drift. Any detected violation rejects
the proposal and preserves the exact original bullet. Provider errors or
malformed output cannot fail the full resume pipeline.

Accepted bullet results expose included and avoided keywords, confidence,
provenance, warnings, and structured safety violations for future full-resume
generation and audit. Local validation is intentionally conservative and
finite; human review remains important, especially where semantic meaning is
subtle.

## Full Resume Optimization

`FullResumeOptimizer` is the orchestration boundary that turns the original
resume and optimization contracts into a complete, structured
`OptimizedResumeResult`. It uses composition: the deterministic optimizer owns
ordering, trimming, summary policy, traceability, and final safety checks,
while an injected `ResumeBulletRewriter` owns only isolated bullet proposals.
This keeps future local, OpenAI, or other provider implementations replaceable
without changing full-resume assembly.

The optimizer treats `ResumeOptimizationPlan` as an allowlist and denylist.
Skills and entries may only be reordered from the source resume. Structured
education, certification, project technology, experience technology, employer,
role, and date facts are copied unchanged. Summary generation is optional,
deterministic, and restricted to candidate-profile evidence plus safe plan
keywords; strict mode does not add a summary that was absent from the source.

Every rewrite is locally validated again at the orchestration boundary. Unsafe
or failed rewrites preserve the original bullet and create blocked,
traceable `ResumeChange` records. Strict mode rolls the result back to original
content after any blocked unsafe change. Non-strict mode keeps independently
safe changes while excluding unsafe proposals.

The final safety audit detects newly introduced unsafe keywords, forbidden
claims, metrics, and structured technologies. `ResumeChange` and
`ResumeOptimizationSafetyReport` make every applied, trimmed, unchanged, or
blocked decision inspectable for future persistence, comparison, UI review,
and export. The estimated after-score scales the planner's conservative range
by completed safe changes and must never be presented as an actual ATS result
or guaranteed improvement.

Current length management uses configurable entry, bullet, and character
limits because no visual renderer exists yet. Future DOCX/PDF export and resume
versioning should consume `OptimizedResume` without changing the optimizer's
factuality boundary.

## Resume Versioning And Persistence

The persistence layer treats resumes as immutable artifacts instead of mutable
documents. `master_resumes` stores each parsed source-of-truth `Resume`;
`resume_versions` stores complete optimized artifacts linked back to a master;
and `jobs` provides minimal explicit target-job linkage. Saving another version
for the same role creates a new record and readable version-name suffix rather
than updating previous content.

SQLAlchemy repositories isolate database operations from application services.
SQLite is the development default, while the declarative models, string UUIDs,
foreign keys, and repository boundaries leave a direct future path to
PostgreSQL and Alembic migrations. Phase 5D uses `Database.initialize()` for
simple early-project schema creation.

Structured resume, optimization plan, skill-gap report, ATS report, safety
report, and change-log contracts are stored as versioned JSON and reconstructed
into Pydantic models at retrieval. Corrupted or incompatible JSON raises a
meaningful artifact error without including sensitive resume contents.
Artifact schema-version differences produce compatibility warnings.

`ResumeVersioningService` owns master/version relationships, duplicate-source
hash checks, readable collision-free names, and immutable version creation.
Only version notes have a controlled update method. Version summaries allow
future dashboards to list artifacts without loading full resume JSON, and the
minimal comparison service exposes score deltas and change-type counts for
future comparison UI.

Raw uploaded PDF/DOCX files are not persisted. Production use must add
encryption at rest, access controls, secure deletion, user authentication, and
audit logs, and must never log full resume data or PII.

## Markdown Resume Rendering

`ResumeRenderer` is the provider-neutral presentation boundary for future
Markdown, DOCX, PDF, HTML, and plain-text outputs. The first implementation,
`MarkdownResumeRenderer`, accepts either the factual source `Resume` or a
complete `OptimizedResume` and emits a separate `RenderedResume`. It performs no
optimization, inference, rewriting, or scoring.

Markdown rendering is deterministic for the same resume and options. It
preserves section and item order, exact bullet wording, technologies,
certifications, education, experience identity, contact facts, and generic
additional sections. Skill display is alias-aware only for deduplication;
rendering retains the first source-supported display spelling and never adds a
skill.

The default format avoids tables, columns, icons, images, nested bullets,
decorative separators, and Markdown links. Strict ATS mode forces dash bullets
and supports plain simple headings. Optional bullet limits trim only the
rendered view and emit warnings without mutating source objects.

File output writes UTF-8 Markdown through a controlled method that creates
parents, sanitizes filenames, refuses silent overwrite, and returns byte size
and SHA-256 metadata. Rendered content can later be persisted as an export
artifact or used as the canonical simple-text input for DOCX/PDF generation,
without rerunning optimization.

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
