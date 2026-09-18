"""
field_mapper.py
----------------
Turns an arbitrary, possibly-nested compliance JSON payload into a flat
list of translatable strings (for one batched provider call), and later
reinserts the translated strings back into a deep copy of the original
structure.

Design reasoning:
The task input can "become more complex later" (nested rule lists,
arrays of objects, etc). Hardcoding "translate data['product_name'],
data['status']..." would break the moment the frontend nests a
`rules: [ {description: ...}, ... ]` array. So instead we walk the
structure generically:

  - dict:  for each key, if key is in field_config -> it's a translation
           target (handled per its mode). Recurse into the value anyway
           in case a translatable field is nested one level deeper
           (defensive; normally the leaf value is a string).
  - list:  recurse into each element (this is what makes arrays of rule
           objects work without special-casing "rules").
  - other: leaf, nothing to do unless it was reached via a configured key.

We never recurse based on VALUE type alone -- only configured field NAMES
are ever queued for translation. A field not in field_config is walked
over (in case it contains nested configured fields inside it) but its own
value is left completely alone. This is what guarantees product_id,
rules_checked, generated_at, rule IDs, etc. can never end up translated,
even if the payload shape changes -- they were never on the allow-list.
"""

import copy
from dataclasses import dataclass
from typing import Any, List


@dataclass
class FieldRef:
    """
    Points at one translatable leaf inside the (deep-copied) data
    structure, plus the field's translation mode.

    `path` is a list of keys/indices describing how to reach the field,
    e.g. ["rules", 2, "description"] means data["rules"][2]["description"].
    This lets reinsertion navigate back to the exact spot without assuming
    the top-level shape.
    """
    path: list
    field_name: str
    mode: str  # "text" or "enum"
    original_value: str


def _get_by_path(data: Any, path: list) -> Any:
    node = data
    for key in path:
        node = node[key]
    return node


def _set_by_path(data: Any, path: list, value: Any) -> None:
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def extract_translatable(data: Any, field_config: dict) -> List[FieldRef]:
    """
    Walk `data` and return a list of FieldRef for every configured,
    non-empty string field found. Order is deterministic (dict/list
    traversal order) so the caller can build a parallel list of raw
    strings to send to the provider and later zip results back by index.
    """
    refs: List[FieldRef] = []
    _walk(data, path=[], field_config=field_config, refs=refs)
    return refs


def _walk(node: Any, path: list, field_config: dict, refs: List[FieldRef]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = path + [key]
            mode = field_config.get(key)
            if mode is not None and isinstance(value, str) and value.strip():
                refs.append(FieldRef(path=child_path, field_name=key, mode=mode, original_value=value))
            # Recurse regardless, in case this value is itself a dict/list
            # that contains further configured fields nested inside it.
            _walk(value, child_path, field_config, refs)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk(item, path + [idx], field_config, refs)
    # else: leaf scalar (int/float/bool/None/already-handled str) -> stop.


def build_output_skeleton(data: Any) -> Any:
    """Deep copy so the original request payload is never mutated in place."""
    return copy.deepcopy(data)


def apply_translations(output: Any, refs: List[FieldRef], translations: dict) -> Any:
    """
    Write resolved translations back into `output` (already a deep copy).

    `translations` maps id(ref) -> translated string, one entry per ref
    that was actually resolved (glossary hit, cache hit, or provider
    result). Every ref MUST have an entry by the time this is called --
    translator_service is responsible for ensuring 100% coverage before
    calling this, so partially-translated output is never returned.

    mode == "text": overwrite the field's value in place.
    mode == "enum": leave the original field untouched, add a sibling
                    "<field>_translated" key immediately in the same dict.
    """
    for ref in refs:
        translated = translations[id(ref)]
        if ref.mode == "text":
            _set_by_path(output, ref.path, translated)
        else:  # enum
            parent_path = ref.path[:-1]
            parent = _get_by_path(output, parent_path) if parent_path else output
            parent[f"{ref.field_name}_translated"] = translated
    return output
