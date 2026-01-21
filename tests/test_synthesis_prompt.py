"""Tests for synthesis prompt builder module.

Tests cover:
- SynthesisPromptBuilder prompt construction
- Capture grouping and formatting
- Statistics calculation
- Weekly summary template rendering
- Supplemental input handling
- Output format specification
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.synthesis.notion_query import VoiceCapture
from src.synthesis.prompt_builder import (
    CaptureStatistics,
    IdeaReference,
    SynthesisPromptBuilder,
    WeeklySummaryData,
    build_synthesis_prompt,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_captures():
    """Create a list of sample captures for testing."""
    return [
        VoiceCapture(
            id="task-1",
            url="https://notion.so/task-1",
            title="Review quarterly report",
            captured_at=datetime(2026, 1, 20, 14, 30),
            template_type="Task",
            device="Watch",
            tags=["work", "quarterly-review"],
            content="## Summary\nNeed to review the Q4 report by Friday.",
            properties={"Duration": {"type": "number", "number": 45}},
        ),
        VoiceCapture(
            id="journal-1",
            url="https://notion.so/journal-1",
            title="Monday reflection",
            captured_at=datetime(2026, 1, 20, 18, 0),
            template_type="Journal",
            device="Phone",
            tags=["personal"],
            content="## Summary\nGood productive day. Made progress on the dashboard.",
            properties={"Duration": {"type": "number", "number": 60}},
        ),
        VoiceCapture(
            id="idea-1",
            url="https://notion.so/idea-1",
            title="Automate report generation",
            captured_at=datetime(2026, 1, 21, 9, 15),
            template_type="Idea",
            device="Watch",
            tags=["automation", "reporting"],
            content="## Summary\nWhat if we could automate the monthly reporting process?",
            properties={"Duration": {"type": "number", "number": 30}},
        ),
        VoiceCapture(
            id="task-2",
            url="https://notion.so/task-2",
            title="Schedule team meeting",
            captured_at=datetime(2026, 1, 22, 10, 0),
            template_type="Task",
            device="Watch",
            tags=["work", "meetings"],
            content="## Summary\nNeed to schedule the project kickoff meeting.",
            properties={"Duration": {"type": "number", "number": 25}},
        ),
    ]


@pytest.fixture
def empty_captures():
    """Empty captures list."""
    return []


@pytest.fixture
def sparse_captures():
    """Only 2 captures (sparse week)."""
    return [
        VoiceCapture(
            id="task-1",
            url="https://notion.so/task-1",
            title="Single task",
            captured_at=datetime(2026, 1, 20, 14, 30),
            template_type="Task",
            device="Watch",
            tags=["work"],
            content="A single task capture.",
            properties={},
        ),
        VoiceCapture(
            id="journal-1",
            url="https://notion.so/journal-1",
            title="Brief note",
            captured_at=datetime(2026, 1, 21, 9, 0),
            template_type="Journal",
            device="Phone",
            tags=[],
            content="Just a brief note.",
            properties={},
        ),
    ]


@pytest.fixture
def builder():
    """Create a SynthesisPromptBuilder instance."""
    return SynthesisPromptBuilder()


@pytest.fixture
def date_range():
    """Standard date range for testing."""
    return {
        "start": datetime(2026, 1, 15),
        "end": datetime(2026, 1, 22),
    }


# ============================================================================
# CaptureStatistics Tests
# ============================================================================

class TestCaptureStatistics:
    """Tests for CaptureStatistics dataclass."""

    def test_default_values(self):
        """Test default values for CaptureStatistics."""
        stats = CaptureStatistics()
        assert stats.total_captures == 0
        assert stats.by_type == {}
        assert stats.total_duration_seconds == 0.0
        assert stats.supplemental_input_used is False

    def test_total_duration_formatted_minutes(self):
        """Test duration formatting with minutes."""
        stats = CaptureStatistics(total_duration_seconds=125)
        assert stats.total_duration_formatted == "2 minutes 5 seconds"

    def test_total_duration_formatted_seconds_only(self):
        """Test duration formatting with seconds only."""
        stats = CaptureStatistics(total_duration_seconds=45)
        assert stats.total_duration_formatted == "45 seconds"

    def test_total_duration_formatted_singular(self):
        """Test duration formatting with singular values."""
        stats = CaptureStatistics(total_duration_seconds=61)
        assert stats.total_duration_formatted == "1 minute 1 second"

    def test_total_duration_formatted_zero(self):
        """Test duration formatting with zero."""
        stats = CaptureStatistics(total_duration_seconds=0)
        assert stats.total_duration_formatted == "0 seconds"


# ============================================================================
# WeeklySummaryData Tests
# ============================================================================

class TestWeeklySummaryData:
    """Tests for WeeklySummaryData dataclass."""

    def test_default_values(self):
        """Test default values for WeeklySummaryData."""
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
        )
        assert data.overview == ""
        assert data.accomplishments == []
        assert data.key_activities == ""
        assert data.challenges == []
        assert data.ideas == []
        assert data.insights == ""
        assert data.upcoming == []

    def test_full_data(self):
        """Test WeeklySummaryData with all fields populated."""
        idea = IdeaReference(
            title="Test Idea",
            url="https://notion.so/idea",
            summary="A test idea",
        )
        stats = CaptureStatistics(
            total_captures=5,
            by_type={"Task": 3, "Journal": 2},
        )
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
            overview="A productive week.",
            accomplishments=["Completed project", "Fixed bug"],
            key_activities="Worked on dashboard.",
            challenges=["Time constraints"],
            ideas=[idea],
            insights="Need more focus time.",
            upcoming=["Review meeting"],
            stats=stats,
        )
        assert data.overview == "A productive week."
        assert len(data.accomplishments) == 2
        assert len(data.ideas) == 1
        assert data.stats.total_captures == 5


# ============================================================================
# SynthesisPromptBuilder Tests
# ============================================================================

class TestSynthesisPromptBuilder:
    """Tests for SynthesisPromptBuilder class."""

    def test_build_synthesis_prompt_basic(self, builder, sample_captures, date_range):
        """Test basic prompt building with sample captures."""
        prompt = builder.build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
        )

        # Verify header section
        assert "You are synthesizing a week's worth of voice captures" in prompt
        assert "January 15, 2026" in prompt
        assert "January 22, 2026" in prompt
        assert "Total Captures:** 4" in prompt

        # Verify captures section
        assert "This Week's Captures" in prompt
        assert "### Task (2)" in prompt
        assert "### Journal (1)" in prompt
        assert "### Idea (1)" in prompt
        assert "Review quarterly report" in prompt
        assert "Monday reflection" in prompt
        assert "Automate report generation" in prompt

        # Verify guidelines section
        assert "Synthesis Guidelines" in prompt
        assert "Accomplishments" in prompt
        assert "Key Activities" in prompt
        assert "Challenges" in prompt

        # Verify output format section
        assert "Output Format" in prompt
        assert '"overview"' in prompt
        assert '"accomplishments"' in prompt

    def test_build_synthesis_prompt_empty(self, builder, empty_captures, date_range):
        """Test prompt building with no captures."""
        prompt = builder.build_synthesis_prompt(
            captures=empty_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
        )

        assert "Total Captures:** 0" in prompt
        assert "No captures found for this period" in prompt

    def test_build_synthesis_prompt_with_supplemental(
        self, builder, sample_captures, date_range
    ):
        """Test prompt building with supplemental input."""
        supplemental = "I also had a major client meeting on Wednesday that I didn't record."

        prompt = builder.build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
            supplemental_input=supplemental,
        )

        assert "Supplemental Input" in prompt
        assert "major client meeting on Wednesday" in prompt
        assert "incorporate this information" in prompt

    def test_format_single_capture(self, builder, sample_captures):
        """Test formatting of a single capture."""
        capture = sample_captures[0]  # Task capture
        formatted = builder._format_single_capture(capture)

        assert "**Review quarterly report**" in formatted
        assert "January 20, 2026" in formatted
        assert "Device: Watch" in formatted
        assert "Tags: work, quarterly-review" in formatted
        assert "https://notion.so/task-1" in formatted
        assert "review the Q4 report" in formatted

    def test_format_single_capture_no_tags(self, builder):
        """Test formatting capture with no tags."""
        capture = VoiceCapture(
            id="test-1",
            url="https://notion.so/test",
            title="Test capture",
            captured_at=datetime(2026, 1, 20),
            template_type="Task",
            device="Watch",
            tags=[],
            content="Test content",
        )
        formatted = builder._format_single_capture(capture)
        assert "Tags: none" in formatted

    def test_format_single_capture_long_content(self, builder):
        """Test formatting capture with very long content."""
        long_content = "A" * 3000  # Exceeds 2000 char limit
        capture = VoiceCapture(
            id="test-1",
            url="https://notion.so/test",
            title="Long capture",
            captured_at=datetime(2026, 1, 20),
            template_type="Task",
            device="Watch",
            tags=[],
            content=long_content,
        )
        formatted = builder._format_single_capture(capture)

        # Content should be truncated
        assert len(formatted) < 3000
        assert "..." in formatted

    def test_format_single_capture_no_date(self, builder):
        """Test formatting capture with missing date."""
        capture = VoiceCapture(
            id="test-1",
            url="https://notion.so/test",
            title="No date capture",
            captured_at=None,
            template_type="Task",
            device="Watch",
            tags=[],
            content="",
        )
        formatted = builder._format_single_capture(capture)
        assert "Unknown date" in formatted

    def test_calculate_statistics(self, builder, sample_captures):
        """Test statistics calculation."""
        from src.synthesis.notion_query import group_by_template

        grouped = group_by_template(sample_captures)
        stats = builder._calculate_statistics(sample_captures, grouped)

        assert stats.total_captures == 4
        assert stats.by_type["Task"] == 2
        assert stats.by_type["Journal"] == 1
        assert stats.by_type["Idea"] == 1
        # Duration: 45 + 60 + 30 + 25 = 160
        assert stats.total_duration_seconds == 160.0

    def test_calculate_statistics_no_duration(self, builder):
        """Test statistics calculation without duration properties."""
        captures = [
            VoiceCapture(
                id="test-1",
                url="",
                title="Test",
                captured_at=datetime(2026, 1, 20),
                template_type="Task",
                device="Watch",
                properties={},
            ),
        ]
        from src.synthesis.notion_query import group_by_template

        grouped = group_by_template(captures)
        stats = builder._calculate_statistics(captures, grouped)

        assert stats.total_captures == 1
        assert stats.total_duration_seconds == 0.0

    def test_format_captures_for_display(self, builder, sample_captures):
        """Test display formatting of captures."""
        display = builder.format_captures_for_display(sample_captures)

        assert "Total: 4 captures" in display
        assert "Task: 2" in display
        assert "Journal: 1" in display
        assert "Idea: 1" in display

    def test_format_captures_for_display_empty(self, builder, empty_captures):
        """Test display formatting with no captures."""
        display = builder.format_captures_for_display(empty_captures)
        assert "No captures to display" in display


# ============================================================================
# Prompt Section Tests
# ============================================================================

class TestPromptSections:
    """Tests for individual prompt sections."""

    def test_build_header(self, builder):
        """Test header section building."""
        stats = CaptureStatistics(
            total_captures=5,
            by_type={"Task": 3, "Journal": 2},
            total_duration_seconds=120,
        )
        header = builder._build_header(
            start_date=datetime(2026, 1, 15),
            end_date=datetime(2026, 1, 22),
            stats=stats,
        )

        assert "synthesizing a week's worth of voice captures" in header
        assert "January 15, 2026" in header
        assert "January 22, 2026" in header
        assert "Total Captures:** 5" in header
        assert "Task: 3" in header
        assert "Journal: 2" in header
        assert "2 minutes 0 seconds" in header

    def test_build_captures_section_empty(self, builder):
        """Test captures section with empty dict."""
        section = builder._build_captures_section({})
        assert "No captures found for this period" in section

    def test_build_captures_section_ordered(self, builder, sample_captures):
        """Test that captures section maintains type order."""
        from src.synthesis.notion_query import group_by_template

        grouped = group_by_template(sample_captures)
        section = builder._build_captures_section(grouped)

        # Find positions of each type header
        journal_pos = section.find("### Journal")
        task_pos = section.find("### Task")
        idea_pos = section.find("### Idea")

        # Journal should come before Task (per TEMPLATE_TYPE_ORDER)
        assert journal_pos < task_pos
        # Task should come before Idea
        assert task_pos < idea_pos

    def test_build_supplemental_section(self, builder):
        """Test supplemental input section."""
        supplemental = "Additional context from user."
        section = builder._build_supplemental_section(supplemental)

        assert "Supplemental Input" in section
        assert "Additional context from user" in section
        assert "incorporate this information" in section

    def test_build_guidelines_section(self, builder):
        """Test guidelines section content."""
        section = builder._build_guidelines_section()

        # Verify all guideline topics are present
        assert "Overview" in section
        assert "Accomplishments" in section
        assert "Key Activities" in section
        assert "Challenges & Blockers" in section
        assert "Ideas Generated" in section
        assert "Insights & Reflections" in section
        assert "Upcoming" in section
        assert "Statistics" in section

        # Verify important guidance
        assert "do not invent" in section.lower() or "Do not invent" in section
        assert "reflective" in section.lower()

    def test_build_output_format_section(self, builder):
        """Test output format section."""
        section = builder._build_output_format_section()

        assert "Output Format" in section
        assert "valid JSON" in section
        assert '"overview"' in section
        assert '"accomplishments"' in section
        assert '"key_activities"' in section
        assert '"challenges"' in section
        assert '"ideas"' in section
        assert '"insights"' in section
        assert '"upcoming"' in section


# ============================================================================
# Weekly Summary Template Rendering Tests
# ============================================================================

class TestWeeklySummaryRendering:
    """Tests for weekly summary template rendering."""

    def test_render_weekly_summary(self, builder):
        """Test rendering weekly summary template."""
        idea = IdeaReference(
            title="Automation Idea",
            url="https://notion.so/idea-1",
            summary="Automate reporting process",
        )
        stats = CaptureStatistics(
            total_captures=5,
            by_type={"Task": 3, "Journal": 2},
            total_duration_seconds=180,
        )
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
            overview="A focused week on project delivery.",
            accomplishments=["Completed dashboard", "Fixed critical bug"],
            key_activities="Worked primarily on dashboard feature. Had planning meeting.",
            challenges=["Tight timeline", "Resource constraints"],
            ideas=[idea],
            insights="Need more deep work blocks.",
            upcoming=["Deploy dashboard", "Team retrospective"],
            stats=stats,
        )

        rendered = builder.render_weekly_summary(data)

        # Verify header
        assert "# Week of January 15, 2026 - January 22, 2026" in rendered

        # Verify overview
        assert "focused week on project delivery" in rendered

        # Verify accomplishments
        assert "- Completed dashboard" in rendered
        assert "- Fixed critical bug" in rendered

        # Verify key activities
        assert "dashboard feature" in rendered

        # Verify challenges
        assert "- Tight timeline" in rendered
        assert "- Resource constraints" in rendered

        # Verify ideas with links
        assert "[Automation Idea](https://notion.so/idea-1)" in rendered
        assert "Automate reporting process" in rendered

        # Verify insights
        assert "deep work blocks" in rendered

        # Verify upcoming
        assert "- Deploy dashboard" in rendered
        assert "- Team retrospective" in rendered

        # Verify statistics
        assert "Total captures:** 5" in rendered
        assert "Task(3)" in rendered
        assert "Journal(2)" in rendered
        assert "3 minutes" in rendered

    def test_render_weekly_summary_empty_sections(self, builder):
        """Test rendering with empty sections."""
        stats = CaptureStatistics(total_captures=0, by_type={})
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
            stats=stats,
        )

        rendered = builder.render_weekly_summary(data)

        assert "No accomplishments captured this week" in rendered
        assert "No challenges noted this week" in rendered
        assert "No ideas captured this week" in rendered
        assert "No upcoming items identified" in rendered

    def test_render_weekly_summary_with_supplemental_flag(self, builder):
        """Test rendering notes when supplemental input was used."""
        stats = CaptureStatistics(
            total_captures=2,
            by_type={"Task": 2},
            supplemental_input_used=True,
        )
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
            overview="Summary with supplemental.",
            stats=stats,
        )

        rendered = builder.render_weekly_summary(data)
        assert "includes supplemental input" in rendered


# ============================================================================
# Convenience Function Tests
# ============================================================================

class TestConvenienceFunction:
    """Tests for build_synthesis_prompt convenience function."""

    def test_build_synthesis_prompt_function(self, sample_captures, date_range):
        """Test the standalone convenience function."""
        prompt = build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
        )

        assert "You are synthesizing" in prompt
        assert "This Week's Captures" in prompt
        assert "Task (2)" in prompt

    def test_build_synthesis_prompt_function_with_supplemental(
        self, sample_captures, date_range
    ):
        """Test convenience function with supplemental input."""
        prompt = build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
            supplemental_input="Extra context here.",
        )

        assert "Supplemental Input" in prompt
        assert "Extra context here" in prompt


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestEdgeCases:
    """Tests for edge cases and unusual inputs."""

    def test_capture_with_special_characters(self, builder):
        """Test formatting capture with special characters."""
        capture = VoiceCapture(
            id="test-1",
            url="https://notion.so/test",
            title='Test with "quotes" and <brackets>',
            captured_at=datetime(2026, 1, 20),
            template_type="Task",
            device="Watch",
            tags=["tag-with-dash", "tag_with_underscore"],
            content="Content with special chars: & < > \" '",
        )
        formatted = builder._format_single_capture(capture)

        # Should include the content without errors
        assert "quotes" in formatted
        assert "brackets" in formatted

    def test_capture_with_unknown_template_type(self, builder):
        """Test handling capture with unusual template type."""
        captures = [
            VoiceCapture(
                id="test-1",
                url="https://notion.so/test",
                title="Custom Type",
                captured_at=datetime(2026, 1, 20),
                template_type="CustomType",
                device="Watch",
            ),
        ]

        from src.synthesis.notion_query import group_by_template

        grouped = group_by_template(captures)
        section = builder._build_captures_section(grouped)

        # Should include the custom type
        assert "### CustomType (1)" in section

    def test_multiple_ideas_in_summary(self, builder):
        """Test rendering multiple ideas in summary."""
        ideas = [
            IdeaReference(
                title="Idea 1",
                url="https://notion.so/idea-1",
                summary="First idea",
            ),
            IdeaReference(
                title="Idea 2",
                url="https://notion.so/idea-2",
                summary="Second idea",
            ),
            IdeaReference(
                title="Idea 3 without summary",
                url="https://notion.so/idea-3",
            ),
        ]
        stats = CaptureStatistics(total_captures=3, by_type={"Idea": 3})
        data = WeeklySummaryData(
            start_date="January 15, 2026",
            end_date="January 22, 2026",
            ideas=ideas,
            stats=stats,
        )

        rendered = builder.render_weekly_summary(data)

        assert "[Idea 1](https://notion.so/idea-1)" in rendered
        assert "[Idea 2](https://notion.so/idea-2)" in rendered
        assert "[Idea 3 without summary](https://notion.so/idea-3)" in rendered
        assert "First idea" in rendered
        assert "Second idea" in rendered

    def test_very_long_supplemental_input(self, builder, sample_captures, date_range):
        """Test handling very long supplemental input."""
        long_input = "This is a very long supplemental input. " * 100

        prompt = builder.build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
            supplemental_input=long_input,
        )

        # Should include the full input
        assert long_input in prompt
        assert "Supplemental Input" in prompt

    def test_capture_without_content(self, builder):
        """Test formatting capture without content."""
        capture = VoiceCapture(
            id="test-1",
            url="https://notion.so/test",
            title="No Content",
            captured_at=datetime(2026, 1, 20),
            template_type="Task",
            device="Watch",
            tags=[],
            content="",
        )
        formatted = builder._format_single_capture(capture)

        # Should not include Content section
        assert "Content:" not in formatted
        assert "```" not in formatted


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for full workflow."""

    def test_full_prompt_to_rendering_workflow(self, builder, sample_captures, date_range):
        """Test complete workflow from captures to rendered summary."""
        # Build the prompt
        prompt = builder.build_synthesis_prompt(
            captures=sample_captures,
            start_date=date_range["start"],
            end_date=date_range["end"],
        )

        # Simulate LLM response parsing (mock response data)
        # This would come from Claude in production
        mock_llm_response = {
            "overview": "A productive week focused on quarterly work.",
            "accomplishments": [
                "Started quarterly report review",
                "Made progress on dashboard",
            ],
            "key_activities": "Focused on quarterly deliverables and planning.",
            "challenges": ["Time constraints"],
            "ideas": [
                {
                    "title": "Automate report generation",
                    "url": "https://notion.so/idea-1",
                    "summary": "Automate monthly reporting",
                }
            ],
            "insights": "Need to batch similar tasks together.",
            "upcoming": ["Complete quarterly report"],
        }

        # Convert LLM response to WeeklySummaryData
        from src.synthesis.notion_query import group_by_template

        grouped = group_by_template(sample_captures)
        stats = builder._calculate_statistics(sample_captures, grouped)

        data = WeeklySummaryData(
            start_date=date_range["start"].strftime("%B %d, %Y"),
            end_date=date_range["end"].strftime("%B %d, %Y"),
            overview=mock_llm_response["overview"],
            accomplishments=mock_llm_response["accomplishments"],
            key_activities=mock_llm_response["key_activities"],
            challenges=mock_llm_response["challenges"],
            ideas=[IdeaReference(**i) for i in mock_llm_response["ideas"]],
            insights=mock_llm_response["insights"],
            upcoming=mock_llm_response["upcoming"],
            stats=stats,
        )

        # Render the summary
        rendered = builder.render_weekly_summary(data)

        # Verify the rendered output
        assert "# Week of January 15, 2026 - January 22, 2026" in rendered
        assert "quarterly work" in rendered
        assert "quarterly report review" in rendered
        assert "Time constraints" in rendered
        assert "[Automate report generation](https://notion.so/idea-1)" in rendered
        assert "Total captures:** 4" in rendered
