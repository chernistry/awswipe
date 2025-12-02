"""YAML configuration loader with validation."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Optional, Any

import yaml


@dataclass
class TagFilters:
    """Tag-based filtering rules."""
    include: Dict[str, List[str]] = field(default_factory=dict)
    exclude: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class Config:
    """AWSwipe configuration."""
    regions: List[str] = field(default_factory=lambda: ["all"])
    resource_types: List[str] = field(default_factory=lambda: ["all"])
    tag_filters: TagFilters = field(default_factory=TagFilters)
    exclude_patterns: List[str] = field(default_factory=list)
    dry_run: bool = True
    json_logs: bool = False
    verbosity: int = 0

    def should_include_region(self, region: str) -> bool:
        """Check if region should be processed."""
        if "all" in self.regions:
            return True
        return region in self.regions

    def should_include_resource(self, resource_type: str) -> bool:
        """Check if resource type should be processed."""
        if "all" in self.resource_types:
            return True
        return resource_type in self.resource_types

    def matches_tag_filters(self, tags: Dict[str, str]) -> bool:
        """Check if resource tags match include/exclude filters."""
        # Check exclude first
        for key, values in self.tag_filters.exclude.items():
            if key in tags and tags[key] in values:
                return False
        # Check include (if specified, at least one must match)
        if self.tag_filters.include:
            for key, values in self.tag_filters.include.items():
                if key in tags and tags[key] in values:
                    return True
            return False
        return True

    def matches_exclude_pattern(self, name: str) -> bool:
        """Check if resource name matches any exclude pattern."""
        import fnmatch
        return any(fnmatch.fnmatch(name, p) for p in self.exclude_patterns)


def load_config(path: Optional[str] = None) -> Config:
    """Load config from YAML file or return defaults.
    
    Args:
        path: Path to YAML config file. If None, returns default config.
    
    Returns:
        Config instance
    
    Raises:
        FileNotFoundError: If specified path doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    if path is None:
        return Config()
    
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    
    return _parse_config(data)


def _parse_config(data: Dict[str, Any]) -> Config:
    """Parse config dict into Config dataclass."""
    tag_filters_data = data.get("tag_filters", {})
    tag_filters = TagFilters(
        include=tag_filters_data.get("include", {}),
        exclude=tag_filters_data.get("exclude", {}),
    )
    
    return Config(
        regions=data.get("regions", ["all"]),
        resource_types=data.get("resource_types", ["all"]),
        tag_filters=tag_filters,
        exclude_patterns=data.get("exclude_patterns", []),
        dry_run=data.get("dry_run", True),
        json_logs=data.get("json_logs", False),
        verbosity=data.get("verbosity", 0),
    )
