"""
Template loader for YAML-based template configuration.

Loads and validates template configurations from config/templates/*.yaml.
Provides runtime access to template definitions and generates classification
prompt context for the LLM.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

from src.classification.template_config import TemplateConfig, FieldType


logger = logging.getLogger(__name__)


class TemplateValidationError(Exception):
    """Raised when a template fails validation."""

    def __init__(self, template_name: str, message: str):
        self.template_name = template_name
        self.message = message
        super().__init__(f"Template '{template_name}': {message}")


class TemplateLoadError(Exception):
    """Raised when a template file cannot be loaded."""

    def __init__(self, file_path: Path, message: str):
        self.file_path = file_path
        self.message = message
        super().__init__(f"Failed to load '{file_path}': {message}")


class TemplateLoader:
    """
    Loads and manages template configurations from YAML files.

    Templates are loaded from a directory containing .yaml files.
    Files starting with '_' are treated as template examples and skipped.

    Example usage (preferred - using factory method):
        loader = TemplateLoader.from_directory(Path("config/templates"))
        task_template = loader.get_template("task")
        prompt_context = loader.build_classification_prompt_context()

    Example usage (legacy - still supported):
        loader = TemplateLoader(Path("config/templates"))
        loader.load_all()
        task_template = loader.get_template("task")
    """

    def __init__(self, templates_dir: Path):
        """
        Initialize the template loader.

        Args:
            templates_dir: Path to directory containing template YAML files.
        """
        self.templates_dir = Path(templates_dir)
        self._templates: Dict[str, TemplateConfig] = {}
        self._load_errors: List[str] = []
        self._loaded: bool = False

    @classmethod
    def from_directory(cls, templates_dir: Path) -> "TemplateLoader":
        """Create and initialize a TemplateLoader from a directory.

        Factory method that ensures templates are loaded immediately.
        Preferred over direct construction.

        Args:
            templates_dir: Path to directory containing template YAML files.

        Returns:
            Initialized TemplateLoader with all templates loaded.

        Raises:
            FileNotFoundError: If templates_dir does not exist.
            TemplateLoadError: If any template file is invalid.
        """
        loader = cls(templates_dir)
        loader.load_all()
        return loader

    @property
    def templates(self) -> Dict[str, TemplateConfig]:
        """Get all loaded templates."""
        return self._templates.copy()

    @property
    def load_errors(self) -> List[str]:
        """Get any errors encountered during loading."""
        return self._load_errors.copy()

    def load_all(self, raise_on_error: bool = False) -> int:
        """
        Load all YAML template files from the templates directory.

        Files starting with '_' (like _template.yaml) are skipped.
        Invalid templates are logged but don't prevent other templates
        from loading unless raise_on_error is True.

        Args:
            raise_on_error: If True, raise exception on first error.
                           If False (default), log errors and continue.

        Returns:
            Number of templates successfully loaded.

        Raises:
            FileNotFoundError: If templates directory doesn't exist.
            TemplateLoadError: If raise_on_error and a file fails to load.
            TemplateValidationError: If raise_on_error and validation fails.
        """
        self._templates.clear()
        self._load_errors.clear()

        if not self.templates_dir.exists():
            raise FileNotFoundError(
                f"Templates directory not found: {self.templates_dir}"
            )

        if not self.templates_dir.is_dir():
            raise NotADirectoryError(
                f"Templates path is not a directory: {self.templates_dir}"
            )

        yaml_files = list(self.templates_dir.glob("*.yaml"))
        yaml_files.extend(self.templates_dir.glob("*.yml"))

        loaded_count = 0

        for file_path in yaml_files:
            # Skip files starting with underscore (template examples)
            if file_path.name.startswith("_"):
                logger.debug(f"Skipping template example: {file_path.name}")
                continue

            try:
                template = self._load_template_file(file_path)
                if template.name in self._templates:
                    error_msg = f"Duplicate template name '{template.name}' in {file_path}"
                    if raise_on_error:
                        raise TemplateValidationError(template.name, error_msg)
                    self._load_errors.append(error_msg)
                    logger.error(error_msg)
                    continue

                self._templates[template.name] = template
                loaded_count += 1
                logger.info(f"Loaded template: {template.name} ({template.display_name})")

            except (TemplateLoadError, TemplateValidationError) as e:
                if raise_on_error:
                    raise
                self._load_errors.append(str(e))
                logger.error(str(e))
            except Exception as e:
                error_msg = f"Unexpected error loading {file_path}: {e}"
                if raise_on_error:
                    raise TemplateLoadError(file_path, str(e))
                self._load_errors.append(error_msg)
                logger.error(error_msg)

        logger.info(f"Loaded {loaded_count} templates from {self.templates_dir}")
        self._loaded = True
        return loaded_count

    def _load_template_file(self, file_path: Path) -> TemplateConfig:
        """
        Load and validate a single template file.

        Args:
            file_path: Path to the YAML file.

        Returns:
            Validated TemplateConfig.

        Raises:
            TemplateLoadError: If file cannot be read or parsed.
            TemplateValidationError: If template data is invalid.
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise TemplateLoadError(file_path, f"Invalid YAML: {e}")
        except IOError as e:
            raise TemplateLoadError(file_path, f"Cannot read file: {e}")

        if data is None:
            raise TemplateLoadError(file_path, "File is empty")

        if not isinstance(data, dict):
            raise TemplateLoadError(file_path, "Root must be a YAML mapping")

        try:
            template = TemplateConfig.from_dict(data)
            self._validate_template(template, file_path)
            return template
        except ValueError as e:
            raise TemplateValidationError(
                data.get("name", file_path.stem),
                str(e)
            )

    def _validate_template(self, template: TemplateConfig, file_path: Path) -> None:
        """
        Perform additional validation on a loaded template.

        Args:
            template: The template to validate.
            file_path: Source file path (for error messages).

        Raises:
            TemplateValidationError: If validation fails.
        """
        errors = []

        # Check for at least one field
        if not template.fields:
            errors.append("Template must have at least one field")

        # Check for duplicate field names
        field_names = [f.name for f in template.fields]
        duplicates = [n for n in field_names if field_names.count(n) > 1]
        if duplicates:
            errors.append(f"Duplicate field names: {set(duplicates)}")

        # Validate select fields have options (multi_select allows empty - auto-creates in Notion)
        for field in template.fields:
            if field.type == FieldType.SELECT:
                if not field.options:
                    errors.append(
                        f"Field '{field.name}' is select but has no options"
                    )

        # Verify page_body_template has basic structure if provided
        if template.page_body_template:
            # Just check it's a non-empty string - Jinja2 validation happens at render time
            if not isinstance(template.page_body_template, str):
                errors.append("page_body_template must be a string")

        if errors:
            raise TemplateValidationError(
                template.name,
                "; ".join(errors)
            )

    def load_template(self, file_path: Path) -> TemplateConfig:
        """
        Load a single template file and add it to the loaded templates.

        Useful for testing or dynamically adding templates.

        Args:
            file_path: Path to the template YAML file.

        Returns:
            The loaded TemplateConfig.

        Raises:
            TemplateLoadError: If file cannot be loaded.
            TemplateValidationError: If template is invalid.
        """
        template = self._load_template_file(file_path)
        self._templates[template.name] = template
        return template

    def get_template(self, name: str) -> Optional[TemplateConfig]:
        """
        Get a specific template by name.

        Args:
            name: Template name (e.g., "task", "journal").

        Returns:
            TemplateConfig if found, None otherwise.
        """
        if not self._loaded:
            import warnings
            warnings.warn(
                "TemplateLoader.get_template() called before load_all(). "
                "Use TemplateLoader.from_directory() for safer initialization.",
                DeprecationWarning,
                stacklevel=2,
            )
        return self._templates.get(name)

    def get_enabled_templates(self) -> List[TemplateConfig]:
        """
        Get all enabled templates.

        Returns:
            List of TemplateConfig where enabled=True.
        """
        return [t for t in self._templates.values() if t.enabled]

    def get_disabled_templates(self) -> List[TemplateConfig]:
        """
        Get all disabled templates.

        Returns:
            List of TemplateConfig where enabled=False.
        """
        return [t for t in self._templates.values() if not t.enabled]

    def get_template_names(self) -> List[str]:
        """
        Get all loaded template names.

        Returns:
            List of template names.
        """
        return list(self._templates.keys())

    def has_template(self, name: str) -> bool:
        """
        Check if a template with the given name is loaded.

        Args:
            name: Template name to check.

        Returns:
            True if template exists.
        """
        return name in self._templates

    def build_classification_prompt_context(self) -> str:
        """
        Generate the template definitions section for the classification prompt.

        This output is inserted into the LLM prompt to provide template
        information for classification decisions.

        Only enabled templates are included.

        Returns:
            Formatted string with all template definitions.
        """
        enabled = self.get_enabled_templates()

        if not enabled:
            return "No templates available for classification."

        sections = []
        for template in enabled:
            sections.append(template.build_prompt_section())

        return "\n\n".join(sections)

    def validate_classification_result(
        self,
        template_name: str,
        fields: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate a classification result against template definition.

        Args:
            template_name: Name of the template to validate against.
            fields: Extracted fields from classification.

        Returns:
            Validated fields with defaults applied.

        Raises:
            ValueError: If template not found or validation fails.
        """
        template = self.get_template(template_name)
        if template is None:
            raise ValueError(f"Unknown template: {template_name}")

        return template.validate_extracted_fields(fields, apply_defaults=True)

    def get_fallback_template(self) -> Optional[TemplateConfig]:
        """
        Get the fallback template (typically 'general').

        Returns:
            The 'general' template if it exists and is enabled, else None.
        """
        general = self.get_template("general")
        if general and general.enabled:
            return general
        return None

    def reload(self) -> int:
        """
        Reload all templates from disk.

        Useful after template files have been modified.

        Returns:
            Number of templates loaded.
        """
        return self.load_all()

    def __len__(self) -> int:
        """Return number of loaded templates."""
        return len(self._templates)

    def __contains__(self, name: str) -> bool:
        """Check if template name exists."""
        return name in self._templates

    def __iter__(self):
        """Iterate over loaded templates."""
        return iter(self._templates.values())
