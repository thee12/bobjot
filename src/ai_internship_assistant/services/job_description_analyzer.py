"""Deterministic structured job-description analysis.

The rule-based analyzer converts standardized JobPosting objects into
provider-independent JobAnalysis objects. It extracts only evidence present in
the posting and never rewrites, summarizes, or invents requirements.

Future OpenAI and hybrid analyzers can implement the JobDescriptionAnalyzer
protocol without changing downstream ATS, skill-gap, or optimization modules.
"""

import hashlib
import html
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    EmploymentType,
    JobAnalysis,
    JobPosting,
    JobSeniority,
    RequirementLevel,
    RoleCategory,
    SkillRequirement,
)

_BLOCK_TAG_PATTERN = re.compile(
    r"</?(?:p|div|li|ul|ol|h[1-6]|br|section|article)[^>]*>",
    re.IGNORECASE,
)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_SENTENCE_PATTERN = re.compile(r"(?<=[.!?])\s+")
_RAW_TEXT_KEYS = (
    "description",
    "content",
    "requirements",
    "responsibilities",
    "qualifications",
    "preferredQualifications",
    "preferred_qualifications",
)

PROGRAMMING_LANGUAGES = (
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "C++",
    "C#",
    "Rust",
    "SQL",
    "Bash",
    "PowerShell",
    "Go",
    "C",
)
TECHNICAL_TOOLS = (
    "GitHub",
    "Kubernetes",
    "ServiceNow",
    "Burp Suite",
    "Metasploit",
    "Wireshark",
    "Splunk",
    "Docker",
    "Linux",
    "Windows",
    "Jira",
    "Nessus",
    "Qualys",
    "Git",
)
FRAMEWORKS = ("FastAPI", "Flask", "Django", "React", "Node.js", "Spring Boot")
CLOUD_PLATFORMS = ("Google Cloud", "AWS", "Azure", "GCP")
CYBERSECURITY_TERMS = (
    "vulnerability management",
    "incident response",
    "malware analysis",
    "endpoint security",
    "network security",
    "threat detection",
    "risk assessment",
    "access control",
    "MITRE ATT&CK",
    "log analysis",
    "security logs",
    "compliance",
    "Wireshark",
    "Splunk",
    "firewall",
    "SIEM",
    "SOC",
    "IAM",
    "NIST",
    "IDS",
    "IPS",
)
CERTIFICATIONS = (
    "AWS Certified Cloud Practitioner",
    "Security+",
    "Network+",
    "CySA+",
    "CISSP",
    "CCNA",
    "CEH",
    "A+",
)

TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "Google Cloud": ("Google Cloud Platform",),
    "Security+": ("CompTIA Security+", "CompTIA Security Plus", "Security Plus"),
    "Network+": ("CompTIA Network+", "CompTIA Network Plus", "Network Plus"),
    "CySA+": ("CompTIA CySA+", "CompTIA CySA Plus", "CySA Plus"),
    "A+": ("CompTIA A+", "CompTIA A Plus", "A Plus"),
    "Node.js": ("NodeJS", "Node JS"),
    "PowerShell": ("Power Shell",),
    "C#": ("C Sharp",),
    "C++": ("C Plus Plus",),
    "student": ("students",),
}
SOFT_SKILLS = (
    "analytical thinking",
    "attention to detail",
    "problem solving",
    "communication",
    "collaboration",
    "documentation",
    "teamwork",
)

_REQUIRED_INDICATORS = (
    "required",
    "must have",
    "minimum qualifications",
    "basic qualifications",
    "you have",
    "requirements",
)
_PREFERRED_INDICATORS = ("preferred", "desired", "familiar with", "exposure to")
_NICE_TO_HAVE_INDICATORS = ("nice to have", "bonus", "plus")

_RESPONSIBILITY_HEADINGS = (
    "responsibilities",
    "what you ll do",
    "what you will do",
    "duties",
    "role overview",
    "in this role",
    "you will",
)
_REQUIRED_HEADINGS = (
    "requirements",
    "required qualifications",
    "minimum qualifications",
    "basic qualifications",
    "qualifications",
    "you have",
)
_PREFERRED_HEADINGS = ("preferred qualifications", "nice to have", "bonus", "desired")

_EXPERIENCE_PATTERNS = (
    re.compile(
        r"\b\d+\+?\s+years?(?:\s+of)?"
        r"(?:\s+relevant|\s+professional|\s+hands-on)?\s+experience\b",
        re.I,
    ),
    re.compile(r"\bprior internship experience\b", re.I),
    re.compile(r"\bprofessional experience\b", re.I),
    re.compile(r"\bhands-on experience\b", re.I),
    re.compile(r"\bcoursework acceptable\b", re.I),
)
_EDUCATION_PATTERNS = (
    re.compile(r"\bcurrently pursuing(?:\s+a|\s+an)?\s+[^.;\n]*degree\b", re.I),
    re.compile(r"\b(?:bachelor'?s|master'?s|associate'?s)\s+degree\b[^.;\n]*", re.I),
    re.compile(r"\bhigh school diploma\b", re.I),
    re.compile(
        r"\b(?:computer science|cybersecurity|information technology|related field)\b",
        re.I,
    ),
)
_DISQUALIFYING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "requires security clearance",
        re.compile(r"\b(?:security\s+)?clearance\b|\btop secret\b", re.I),
    ),
    (
        "U.S. citizenship required",
        re.compile(r"\bU\.?S\.?\s+citizenship\s+(?:is\s+)?required\b", re.I),
    ),
    ("requires relocation", re.compile(r"\brelocat(?:e|ion)\s+(?:is\s+)?required\b", re.I)),
    ("requires 5+ years of experience", re.compile(r"\b(?:5|[6-9]|\d{2,})\+?\s+years?\b", re.I)),
    ("requires Master's degree", re.compile(r"\bmaster'?s\s+degree\s+(?:is\s+)?required\b", re.I)),
    (
        "requires full-time availability during school year",
        re.compile(r"\bfull[- ]time availability\b[^.;\n]*\bschool year\b", re.I),
    ),
    ("requires travel", re.compile(r"\b(?:requires?|up to)\s+\d*%?\s*travel\b", re.I)),
    ("requires being local", re.compile(r"\bmust be local\b|\blocal candidates only\b", re.I)),
)
_INTERNSHIP_INDICATORS = (
    "internship",
    "university program",
    "early talent",
    "campus",
    "co-op",
    "intern",
    "student",
)
_SENIORITY_INDICATORS = ("principal", "director", "architect", "manager", "senior", "staff", "lead")

_ROLE_KEYWORDS: dict[RoleCategory, tuple[str, ...]] = {
    RoleCategory.CYBERSECURITY: (
        "cybersecurity",
        "security",
        "soc",
        "incident response",
        "siem",
        "vulnerability",
    ),
    RoleCategory.SOFTWARE_ENGINEERING: (
        "software",
        "developer",
        "backend",
        "frontend",
        "api",
        "programming",
    ),
    RoleCategory.NETWORKING: ("network", "networking", "routing", "switching", "tcp/ip", "dns"),
    RoleCategory.IT_SUPPORT: ("it support", "help desk", "desktop support", "servicenow"),
    RoleCategory.CLOUD: ("cloud", "aws", "azure", "gcp", "google cloud"),
    RoleCategory.DATA: ("data science", "data analyst", "analytics", "sql"),
    RoleCategory.DEVOPS: ("devops", "docker", "kubernetes", "ci/cd"),
    RoleCategory.UNKNOWN: (),
}


class JobDescriptionAnalyzer(Protocol):
    """Extension point for rule-based, OpenAI, and hybrid analyzers."""

    def analyze(self, job: JobPosting) -> JobAnalysis:
        """Convert one standardized job posting into structured analysis."""


class RuleBasedJobDescriptionAnalyzer:
    """Conservative deterministic job-description analyzer."""

    def analyze(self, job: JobPosting) -> JobAnalysis:
        """Extract structured signals from a job without external calls."""

        lines = self._combined_lines(job)
        combined_text = "\n".join(lines)
        responsibilities = self._responsibilities(job, lines)
        qualifications = self._qualifications(job, lines)
        evidence_segments = self._evidence_segments(job, lines)

        categories = {
            "programming_language": self._extract_terms(PROGRAMMING_LANGUAGES, combined_text),
            "technical_tool": self._deduplicate(
                [*self._extract_terms(TECHNICAL_TOOLS, combined_text), *job.technologies]
            ),
            "framework": self._extract_terms(FRAMEWORKS, combined_text),
            "cloud_platform": self._extract_terms(CLOUD_PLATFORMS, combined_text),
            "cybersecurity": self._extract_terms(CYBERSECURITY_TERMS, combined_text),
            "certification": self._deduplicate(
                [*self._extract_terms(CERTIFICATIONS, combined_text), *job.certifications]
            ),
            "soft_skill": self._extract_terms(SOFT_SKILLS, combined_text),
        }
        requirements = self._skill_requirements(categories, evidence_segments)
        required_skills = [
            requirement
            for requirement in requirements
            if requirement.requirement_level == RequirementLevel.REQUIRED
        ]
        preferred_skills = [
            requirement
            for requirement in requirements
            if requirement.requirement_level in {
                RequirementLevel.PREFERRED,
                RequirementLevel.NICE_TO_HAVE,
            }
        ]
        experience_requirements = self._pattern_matches(_EXPERIENCE_PATTERNS, combined_text)
        education_requirements = self._pattern_matches(_EDUCATION_PATTERNS, combined_text)
        disqualifying = self._disqualifying_requirements(combined_text, evidence_segments)
        internship_indicators = self._extract_terms(
            _INTERNSHIP_INDICATORS,
            f"{job.title}\n{combined_text}",
        )
        seniority_indicators = self._extract_terms(_SENIORITY_INDICATORS, job.title)
        role_category = self._role_category(job.title, combined_text)
        all_signals = self._deduplicate(
            [
                *categories["programming_language"],
                *categories["technical_tool"],
                *categories["framework"],
                *categories["cloud_platform"],
                *categories["cybersecurity"],
                *categories["certification"],
            ]
        )
        ats_keywords = self._ats_keywords(job.title, combined_text, all_signals)
        warnings = self._warnings(
            combined_text=combined_text,
            responsibilities=responsibilities,
            skills=all_signals,
            seniority_indicators=seniority_indicators,
            employment_type=job.employment_type,
        )

        return JobAnalysis(
            job_id=job.id,
            job_title=job.title,
            company=job.company,
            normalized_title=job.normalized_title,
            summary=lines[0] if lines else None,
            responsibilities=responsibilities,
            qualifications=qualifications,
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            technical_tools=categories["technical_tool"],
            programming_languages=categories["programming_language"],
            frameworks=categories["framework"],
            cloud_platforms=categories["cloud_platform"],
            cybersecurity_terms=categories["cybersecurity"],
            certifications=categories["certification"],
            soft_skills=categories["soft_skill"],
            ats_keywords=ats_keywords,
            experience_requirements=experience_requirements,
            education_requirements=education_requirements,
            disqualifying_requirements=disqualifying,
            internship_indicators=internship_indicators,
            seniority_indicators=seniority_indicators,
            role_category=role_category,
            domain_category=role_category,
            seniority=self._seniority(job, internship_indicators, seniority_indicators),
            confidence_score=self._confidence(
                combined_text=combined_text,
                responsibilities=responsibilities,
                qualifications=qualifications,
                skills=all_signals,
            ),
            warnings=warnings,
            raw_text_hash=hashlib.sha256(combined_text.encode()).hexdigest(),
            analysis_source=AnalysisSource.RULE_BASED,
        )

    def _combined_lines(self, job: JobPosting) -> list[str]:
        values: list[str] = []
        if job.description:
            values.extend(self._clean_lines(job.description))
        values.extend(job.responsibilities)
        values.extend(job.requirements)
        values.extend(job.preferred_qualifications)
        values.extend(self._raw_data_lines(job.raw_data))
        return self._deduplicate([self._clean_line(value) for value in values if value])

    def _raw_data_lines(self, raw_data: object) -> list[str]:
        if not isinstance(raw_data, dict):
            return []

        values: list[str] = []
        for key in _RAW_TEXT_KEYS:
            value = raw_data.get(key)
            if isinstance(value, str):
                values.extend(self._clean_lines(value))
            elif isinstance(value, list):
                values.extend(item for item in value if isinstance(item, str))
        return values

    def _clean_lines(self, value: str) -> list[str]:
        unescaped = html.unescape(html.unescape(value))
        with_breaks = _BLOCK_TAG_PATTERN.sub("\n", unescaped)
        without_tags = _HTML_TAG_PATTERN.sub(" ", with_breaks)
        return [
            self._clean_line(line)
            for line in without_tags.splitlines()
            if self._clean_line(line)
        ]

    def _clean_line(self, value: str) -> str:
        return _WHITESPACE_PATTERN.sub(" ", value).strip(" \t-*•")

    def _responsibilities(self, job: JobPosting, lines: Sequence[str]) -> list[str]:
        if job.responsibilities:
            return self._deduplicate(job.responsibilities)
        return self._section_statements(lines, _RESPONSIBILITY_HEADINGS)

    def _qualifications(self, job: JobPosting, lines: Sequence[str]) -> list[str]:
        structured = [*job.requirements, *job.preferred_qualifications]
        if structured:
            return self._deduplicate(structured)
        return self._section_statements(lines, (*_REQUIRED_HEADINGS, *_PREFERRED_HEADINGS))

    def _section_statements(
        self,
        lines: Sequence[str],
        headings: Sequence[str],
    ) -> list[str]:
        statements: list[str] = []
        active = False
        for line in lines:
            normalized = self._normalize(line).rstrip(":")
            if self._is_heading(normalized):
                active = any(heading in normalized for heading in headings)
                continue
            if active:
                statements.extend(self._sentences(line))
        return self._deduplicate(statements)

    def _evidence_segments(
        self,
        job: JobPosting,
        lines: Sequence[str],
    ) -> list[tuple[str, RequirementLevel]]:
        segments: list[tuple[str, RequirementLevel]] = []
        segments.extend((value, RequirementLevel.REQUIRED) for value in job.requirements)
        segments.extend(
            (value, RequirementLevel.PREFERRED) for value in job.preferred_qualifications
        )
        segments.extend((value, RequirementLevel.UNKNOWN) for value in job.technologies)
        segments.extend((value, RequirementLevel.UNKNOWN) for value in job.certifications)

        active_level = RequirementLevel.UNKNOWN
        for line in lines:
            normalized = self._normalize(line).rstrip(":")
            if self._is_heading(normalized):
                active_level = self._heading_level(normalized)
                continue
            for sentence in self._sentences(line):
                segments.append((sentence, self._sentence_level(sentence, active_level)))
        return segments

    def _skill_requirements(
        self,
        categories: dict[str, list[str]],
        evidence_segments: Sequence[tuple[str, RequirementLevel]],
    ) -> list[SkillRequirement]:
        requirements: list[SkillRequirement] = []
        for category, terms in categories.items():
            for term in terms:
                evidence, level = self._best_evidence(term, evidence_segments)
                requirements.append(
                    SkillRequirement(
                        name=term,
                        category=category,
                        requirement_level=level,
                        evidence=evidence,
                        confidence=0.95 if level != RequirementLevel.UNKNOWN else 0.7,
                    )
                )
        return requirements

    def _best_evidence(
        self,
        term: str,
        segments: Sequence[tuple[str, RequirementLevel]],
    ) -> tuple[str, RequirementLevel]:
        matches = [
            (evidence, level)
            for evidence, level in segments
            if self._contains_term(evidence, term)
        ]
        priority = {
            RequirementLevel.REQUIRED: 0,
            RequirementLevel.PREFERRED: 1,
            RequirementLevel.NICE_TO_HAVE: 2,
            RequirementLevel.UNKNOWN: 3,
        }
        if matches:
            return min(matches, key=lambda item: priority[item[1]])
        return term, RequirementLevel.UNKNOWN

    def _heading_level(self, normalized: str) -> RequirementLevel:
        if any(indicator in normalized for indicator in _PREFERRED_HEADINGS):
            return RequirementLevel.PREFERRED
        if any(indicator in normalized for indicator in _REQUIRED_HEADINGS):
            return RequirementLevel.REQUIRED
        return RequirementLevel.UNKNOWN

    def _sentence_level(
        self,
        sentence: str,
        section_level: RequirementLevel,
    ) -> RequirementLevel:
        normalized = self._normalize(sentence)
        if any(indicator in normalized for indicator in _NICE_TO_HAVE_INDICATORS):
            return RequirementLevel.NICE_TO_HAVE
        if any(indicator in normalized for indicator in _PREFERRED_INDICATORS):
            return RequirementLevel.PREFERRED
        if any(indicator in normalized for indicator in _REQUIRED_INDICATORS):
            return RequirementLevel.REQUIRED
        return section_level

    def _role_category(self, title: str, combined_text: str) -> RoleCategory:
        full_text = f"{title} {combined_text}"
        scores = {
            category: sum(
                (3 if self._contains_term(title, keyword) else 1)
                for keyword in keywords
                if self._contains_term(full_text, keyword)
            )
            for category, keywords in _ROLE_KEYWORDS.items()
            if category != RoleCategory.UNKNOWN
        }
        if not scores or max(scores.values(), default=0) == 0:
            return RoleCategory.UNKNOWN
        return max(scores, key=lambda category: scores[category])

    def _seniority(
        self,
        job: JobPosting,
        internship_indicators: Sequence[str],
        seniority_indicators: Sequence[str],
    ) -> JobSeniority:
        if internship_indicators or job.employment_type == EmploymentType.INTERNSHIP:
            return JobSeniority.INTERNSHIP
        if seniority_indicators:
            return JobSeniority.SENIOR

        title = self._normalize(job.title)
        if "entry level" in title or "early career" in title:
            return JobSeniority.ENTRY_LEVEL
        if "junior" in title or re.search(r"\b(?:jr|i)\b", title):
            return JobSeniority.JUNIOR
        if "mid level" in title or re.search(r"\bii\b", title):
            return JobSeniority.MID_LEVEL
        return job.seniority

    def _ats_keywords(self, title: str, text: str, signals: Sequence[str]) -> list[str]:
        repeated = Counter(
            term
            for term in signals
            for _ in range(max(self._term_count(text, term), 1))
        )
        title_terms = [
            token
            for token in self._normalize(title).split()
            if token not in {"and", "or", "the", "a", "an"}
        ]
        ranked_signals = [
            term for term, _ in sorted(repeated.items(), key=lambda item: (-item[1], item[0]))
        ]
        return self._deduplicate([title, *ranked_signals, *title_terms])

    def _confidence(
        self,
        *,
        combined_text: str,
        responsibilities: Sequence[str],
        qualifications: Sequence[str],
        skills: Sequence[str],
    ) -> float:
        score = 0.1
        score += min(len(combined_text.split()) / 300, 0.35)
        score += 0.2 if responsibilities else 0.0
        score += 0.15 if qualifications else 0.0
        score += min(len(skills) * 0.03, 0.2)
        return round(min(score, 1.0), 2)

    def _warnings(
        self,
        *,
        combined_text: str,
        responsibilities: Sequence[str],
        skills: Sequence[str],
        seniority_indicators: Sequence[str],
        employment_type: EmploymentType,
    ) -> list[str]:
        warnings: list[str] = []
        word_count = len(combined_text.split())
        if not combined_text:
            warnings.append("empty description")
        if not skills:
            warnings.append("no skills detected")
        if not responsibilities:
            warnings.append("no responsibilities detected")
        if seniority_indicators:
            warnings.append("likely senior role")
        if employment_type == EmploymentType.UNKNOWN:
            warnings.append("unclear employment type")
        if word_count > 5_000:
            warnings.append("possible parsing failure: extremely long description")
        if word_count > 1_500:
            warnings.append("excessive boilerplate or unusually long description")
        return warnings

    def _disqualifying_requirements(
        self,
        text: str,
        evidence_segments: Sequence[tuple[str, RequirementLevel]],
    ) -> list[str]:
        results: list[str] = []
        for label, pattern in _DISQUALIFYING_PATTERNS:
            if not pattern.search(text):
                continue
            matching_levels = [
                level for evidence, level in evidence_segments if pattern.search(evidence)
            ]
            if matching_levels and all(
                level in {RequirementLevel.PREFERRED, RequirementLevel.NICE_TO_HAVE}
                for level in matching_levels
            ):
                continue
            results.append(label)
        return results

    def _pattern_matches(
        self,
        patterns: Sequence[re.Pattern[str]],
        text: str,
    ) -> list[str]:
        return self._deduplicate(
            match.group(0).strip()
            for pattern in patterns
            for match in pattern.finditer(text)
        )

    def _extract_terms(self, terms: Iterable[str], text: str) -> list[str]:
        return [term for term in terms if self._contains_term(text, term)]

    def _contains_term(self, text: str, term: str) -> bool:
        return self._term_pattern(term).search(text) is not None

    def _term_count(self, text: str, term: str) -> int:
        return len(self._term_pattern(term).findall(text))

    def _term_pattern(self, term: str) -> re.Pattern[str]:
        aliases = (term, *TERM_ALIASES.get(term, ()))
        alternatives = [
            re.escape(alias).replace(r"\ ", r"\s+")
            for alias in sorted(aliases, key=len, reverse=True)
        ]
        return re.compile(
            rf"(?<![A-Za-z0-9])(?:{'|'.join(alternatives)})(?![A-Za-z0-9])",
            re.IGNORECASE,
        )

    def _sentences(self, value: str) -> list[str]:
        return [sentence.strip() for sentence in _SENTENCE_PATTERN.split(value) if sentence.strip()]

    def _is_heading(self, normalized: str) -> bool:
        headings = (*_RESPONSIBILITY_HEADINGS, *_REQUIRED_HEADINGS, *_PREFERRED_HEADINGS)
        return len(normalized.split()) <= 6 and any(heading in normalized for heading in headings)

    def _normalize(self, value: str) -> str:
        return JobPosting._normalize_identity_text(value)

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value.strip())
        return result
