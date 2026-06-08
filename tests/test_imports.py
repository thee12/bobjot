"""Smoke tests for the initial scaffold."""

from ai_internship_assistant.config import AppSettings
from ai_internship_assistant.domain.models import Resume, UserPreferences


def test_core_models_importable() -> None:
    """The initial package should expose the core model surface."""

    settings = AppSettings()
    resume = Resume(full_name="Example Candidate")
    preferences = UserPreferences(desired_titles=["Software Engineering Intern"])

    assert settings.env == "local"
    assert resume.full_name == "Example Candidate"
    assert preferences.desired_titles == ["Software Engineering Intern"]

