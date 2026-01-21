"""Weekly synthesis module for voice capture pipeline.

This module provides functionality for the Phase 4 weekly synthesis feature,
including:
- Querying Notion for captures within a date range
- Grouping captures by template type
- Building synthesis prompts
- Generating weekly summaries
- Handling sparse weeks with supplemental input

The module is designed to work with the Claude skill for on-demand
weekly reflection synthesis via Notion MCP.
"""

from src.synthesis.notion_query import (
    NotionQueryService,
    NotionQueryError,
    NotionQueryRateLimitError,
    VoiceCapture,
    query_captures_by_date_range,
    group_by_template,
)

from src.synthesis.prompt_builder import (
    CaptureStatistics,
    IdeaReference,
    SynthesisPromptBuilder,
    WeeklySummaryData,
    build_synthesis_prompt,
)

from src.synthesis.sparse_handler import (
    SPARSE_WEEK_THRESHOLD,
    SparseWeekHandler,
    SparseWeekPromptResult,
    SparseWeekQuestion,
    build_sparse_week_context,
    detect_sparse_week,
    format_supplemental_input,
    get_sparse_week_questions,
)

__all__ = [
    # Notion Query
    "NotionQueryService",
    "NotionQueryError",
    "NotionQueryRateLimitError",
    "VoiceCapture",
    "query_captures_by_date_range",
    "group_by_template",
    # Prompt Builder
    "CaptureStatistics",
    "IdeaReference",
    "SynthesisPromptBuilder",
    "WeeklySummaryData",
    "build_synthesis_prompt",
    # Sparse Week Handling
    "SPARSE_WEEK_THRESHOLD",
    "SparseWeekHandler",
    "SparseWeekPromptResult",
    "SparseWeekQuestion",
    "build_sparse_week_context",
    "detect_sparse_week",
    "format_supplemental_input",
    "get_sparse_week_questions",
]
