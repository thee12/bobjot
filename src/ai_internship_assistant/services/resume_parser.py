"""LLM-backed resume parsing service.

The parser converts raw resume text into the structured Resume domain model.
It is responsible only for extraction: preserving source wording, section
order, dates, technologies, employers, projects, certifications, and bullet
points as they appear in the input. It must not optimize, rewrite, summarize,
score, or infer facts.

Future parser implementations can satisfy the ResumeParser protocol without
coupling the rest of the application to OpenAI.
"""

from typing import Protocol, runtime_checkable

from openai import APIError, OpenAI
from pydantic import ValidationError

from ai_internship_assistant.domain.models import Resume

_SYSTEM_INSTRUCTIONS = """\
You are a resume information extraction engine.

Extract only information explicitly present in the resume text.
Do not summarize. Do not improve wording. Do not reorder sections.
Do not infer years of experience. Do not invent jobs, certifications,
projects, technologies, employers, dates, metrics, or achievements.

If a value is missing or uncertain, use null for scalar fields and an empty
list for list fields.

Populate the Resume model with:
- full_name, email, phone, location
- linkedin_url, github_url, and other links
- education
- certifications
- skills with categories such as programming language, framework, tool, or technology
- projects, including project technologies and bullet points
- work experience, including experience technologies and bullet point achievements

Preserve wording whenever possible.
"""


class ResumeParsingError(RuntimeError):
    """Base exception for resume parsing failures."""


class EmptyResumeTextError(ResumeParsingError):
    """Raised when raw resume text is empty or whitespace-only."""


class LLMResumeParsingError(ResumeParsingError):
    """Raised when the LLM provider fails before returning a parsed response."""


class MalformedLLMResponseError(ResumeParsingError):
    """Raised when the LLM response cannot be validated as a Resume."""


@runtime_checkable
class ResumeParser(Protocol):
    """Parser interface for converting raw resume text into a Resume.

    Implementations may use OpenAI, another hosted model, a local model, or
    deterministic rules. Callers should depend on this protocol rather than on
    any concrete provider implementation.
    """

    def parse(self, text: str) -> Resume:
        """Parse raw resume text into a structured Resume object."""


class OpenAIResumeParser:
    """OpenAI structured-output parser for raw resume text.

    The parser expects already-extracted plain text, typically produced by the
    document extraction layer. It returns a validated Resume model and leaves
    quality checks to ResumeValidator.
    """

    def __init__(
        self,
        *,
        client: OpenAI | None = None,
        model: str = "gpt-4.1-mini",
        temperature: float = 0.0,
    ) -> None:
        """Create an OpenAI-backed resume parser."""

        self._client = client or OpenAI()
        self._model = model
        self._temperature = temperature

    def parse(self, text: str) -> Resume:
        """Parse raw resume text into a structured Resume object."""

        normalized_text = text.strip()
        if not normalized_text:
            msg = "resume text is empty"
            raise EmptyResumeTextError(msg)

        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=_SYSTEM_INSTRUCTIONS,
                input=normalized_text,
                text_format=Resume,
                temperature=self._temperature,
            )
        except APIError as exc:
            msg = "OpenAI failed while parsing resume text"
            raise LLMResumeParsingError(msg) from exc
        except ValidationError as exc:
            msg = "OpenAI returned a response that could not be validated as a Resume"
            raise MalformedLLMResponseError(msg) from exc

        parsed_resume = getattr(response, "output_parsed", None)
        if not isinstance(parsed_resume, Resume):
            msg = "OpenAI response did not contain a parsed Resume object"
            raise MalformedLLMResponseError(msg)

        return parsed_resume

