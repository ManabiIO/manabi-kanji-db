from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent


class StrictSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys and non-string mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[str, Any]:
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
        result: dict[str, Any] = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    "YAML merge keys are not allowed", key_node.start_mark,
                )
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"mapping keys must be strings; got {type(key).__name__}", key_node.start_mark,
                )
            if key == "<<" or key_node.tag == "tag:yaml.org,2002:merge":
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    "YAML merge keys are not allowed", key_node.start_mark,
                )
            if key in result:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"duplicate key {key!r}", key_node.start_mark,
                )
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def loads(text: str, *, path: Path | None = None) -> Any:
    try:
        for event in yaml.parse(text, Loader=yaml.SafeLoader):
            if isinstance(event, AliasEvent):
                raise ValueError("YAML aliases are not allowed")
        return yaml.load(text, Loader=StrictSafeLoader)
    except (yaml.YAMLError, ValueError) as exc:
        label = str(path) if path else "<yaml>"
        raise ValueError(f"{label}: {exc}") from exc


def load(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"), path=path)
