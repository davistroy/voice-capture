"""Notion property mapper.

Maps template field configurations to Notion property formats.
Handles all field types per TDD 4.4:
- title -> title property
- date -> date property (ISO 8601)
- select -> select property
- multi_select -> multi_select (auto-creates options)
- rich_text -> rich_text blocks
- number -> number property
- checkbox -> checkbox property
"""

import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Union

from src.classification.template_config import FieldConfig, FieldType

logger = logging.getLogger(__name__)


class PropertyMappingError(Exception):
    """Raised when property mapping fails."""
    pass


class PropertyMapper:
    """Maps extracted fields to Notion property format.

    Converts template field values to Notion API property objects
    based on the field type defined in the template configuration.
    """

    def map_field_to_property(
        self,
        field_config: FieldConfig,
        value: Any,
    ) -> Dict[str, Any]:
        """Map a single field value to Notion property format.

        Args:
            field_config: Field configuration defining the type and property name.
            value: The extracted field value to map.

        Returns:
            Notion property object ready for API call.

        Raises:
            PropertyMappingError: If mapping fails for the field type.
        """
        field_type = field_config.type

        try:
            if field_type == FieldType.TITLE:
                return self._map_title(value)
            elif field_type == FieldType.DATE:
                return self._map_date(value)
            elif field_type == FieldType.SELECT:
                return self._map_select(value)
            elif field_type == FieldType.MULTI_SELECT:
                return self._map_multi_select(value)
            elif field_type == FieldType.RICH_TEXT:
                return self._map_rich_text(value)
            elif field_type == FieldType.NUMBER:
                return self._map_number(value)
            elif field_type == FieldType.CHECKBOX:
                return self._map_checkbox(value)
            else:
                raise PropertyMappingError(
                    f"Unknown field type: {field_type}"
                )
        except Exception as e:
            if isinstance(e, PropertyMappingError):
                raise
            raise PropertyMappingError(
                f"Failed to map field '{field_config.name}' "
                f"(type={field_type.value}): {e}"
            ) from e

    def map_fields_to_properties(
        self,
        fields: Dict[str, Any],
        field_configs: List[FieldConfig],
        apply_defaults: bool = True,
    ) -> Dict[str, Any]:
        """Map multiple fields to Notion properties.

        Args:
            fields: Dictionary of extracted field values.
            field_configs: List of field configurations from template.
            apply_defaults: Whether to apply defaults for missing optional fields.

        Returns:
            Dictionary of Notion property name -> property object mappings.
        """
        properties: Dict[str, Any] = {}

        for field_config in field_configs:
            field_name = field_config.name
            notion_property_name = field_config.get_notion_property_name()

            # Get value from extracted fields or use default
            if field_name in fields:
                value = fields[field_name]
            elif apply_defaults and field_config.default is not None:
                value = field_config.default
            else:
                # Skip if no value and no default
                continue

            # Skip None values
            if value is None:
                continue

            # Skip empty strings for non-required fields
            if value == "" and not field_config.required:
                continue

            try:
                property_obj = self.map_field_to_property(field_config, value)
                properties[notion_property_name] = property_obj
            except PropertyMappingError as e:
                logger.warning(f"Skipping field '{field_name}': {e}")
                continue

        return properties

    def _map_title(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion title property.

        Args:
            value: String title value.

        Returns:
            Notion title property object.
        """
        title_text = str(value) if value is not None else ""

        return {
            "title": [
                {
                    "text": {
                        "content": title_text
                    }
                }
            ]
        }

    def _map_date(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion date property.

        Accepts:
        - datetime object
        - date object
        - ISO 8601 string

        Args:
            value: Date value in supported format.

        Returns:
            Notion date property object.
        """
        if value is None or value == "":
            raise PropertyMappingError("Date value cannot be empty")

        # Handle datetime objects
        if isinstance(value, datetime):
            date_str = value.isoformat()
        elif isinstance(value, date):
            date_str = value.isoformat()
        elif isinstance(value, str):
            # Assume ISO 8601 format string
            date_str = value
        else:
            raise PropertyMappingError(
                f"Invalid date value type: {type(value).__name__}"
            )

        return {
            "date": {
                "start": date_str
            }
        }

    def _map_select(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion select property.

        Args:
            value: String value that should match an existing option.

        Returns:
            Notion select property object.
        """
        if value is None or value == "":
            raise PropertyMappingError("Select value cannot be empty")

        return {
            "select": {
                "name": str(value)
            }
        }

    def _map_multi_select(
        self,
        value: Union[List[str], str, Any],
    ) -> Dict[str, Any]:
        """Map value to Notion multi_select property.

        Auto-creates options if they don't exist in the database.

        Args:
            value: List of strings or comma-separated string.

        Returns:
            Notion multi_select property object.
        """
        # Handle different input types
        if isinstance(value, list):
            items = value
        elif isinstance(value, str):
            # Handle comma-separated string
            items = [item.strip() for item in value.split(",") if item.strip()]
        else:
            items = [str(value)] if value else []

        # Filter out empty items and convert to Notion format
        multi_select = [
            {"name": str(item)}
            for item in items
            if item and str(item).strip()
        ]

        return {
            "multi_select": multi_select
        }

    def _map_rich_text(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion rich_text property.

        Args:
            value: String text value.

        Returns:
            Notion rich_text property object.
        """
        text = str(value) if value is not None else ""

        # Notion has a 2000 char limit per rich_text element
        # Split into chunks if needed
        rich_text_elements = self._split_text_to_rich_text(text)

        return {
            "rich_text": rich_text_elements
        }

    def _map_number(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion number property.

        Args:
            value: Numeric value (int or float).

        Returns:
            Notion number property object.
        """
        if value is None or value == "":
            raise PropertyMappingError("Number value cannot be empty")

        try:
            num_value = float(value)
        except (ValueError, TypeError) as e:
            raise PropertyMappingError(
                f"Invalid number value: {value}"
            ) from e

        return {
            "number": num_value
        }

    def _map_checkbox(self, value: Any) -> Dict[str, Any]:
        """Map value to Notion checkbox property.

        Args:
            value: Boolean or truthy value.

        Returns:
            Notion checkbox property object.
        """
        # Handle various boolean representations
        if isinstance(value, bool):
            bool_value = value
        elif isinstance(value, str):
            bool_value = value.lower() in ("true", "yes", "1", "on")
        elif isinstance(value, (int, float)):
            bool_value = bool(value)
        else:
            bool_value = bool(value) if value is not None else False

        return {
            "checkbox": bool_value
        }

    def _split_text_to_rich_text(
        self,
        text: str,
        chunk_size: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Split text into rich_text elements respecting Notion's limits.

        Notion has a 2000 character limit per rich_text element.

        Args:
            text: Text to split.
            chunk_size: Maximum characters per element.

        Returns:
            List of Notion rich_text objects.
        """
        if not text or len(text) <= chunk_size:
            return [{"type": "text", "text": {"content": text or ""}}]

        rich_text = []
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            rich_text.append({"type": "text", "text": {"content": chunk}})

        return rich_text


def create_device_property(device: str) -> Dict[str, Any]:
    """Create Device rich_text property with formatted name.

    Args:
        device: Device string (watch, phone, unknown).

    Returns:
        Notion rich_text property object.
    """
    device_lower = device.lower()
    if device_lower == "watch":
        display_name = "Watch"
    elif device_lower == "phone":
        display_name = "Phone"
    else:
        display_name = "Unknown"

    return {
        "rich_text": [
            {
                "type": "text",
                "text": {"content": display_name}
            }
        ]
    }


def create_type_property(template_display_name: str) -> Dict[str, Any]:
    """Create Type select property from template display name.

    Args:
        template_display_name: Display name of the template.

    Returns:
        Notion select property object.
    """
    return {
        "select": {
            "name": template_display_name
        }
    }
