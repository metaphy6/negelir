"""Phase 22.2 bullet 4 — Annotation corpus for Phase22ImportRewriter validation.

Contains ≥15 representative patterns exercising all seven rewrite patterns with
byte-equal output validation. Each corpus entry includes:
  - name: descriptive identifier
  - input_code: source with ai.* imports
  - expected_output: rewritten to new package layout
  - non_targets (optional): samples that must NOT be rewritten (SQL, log messages)
  
Pattern coverage:
  1. from ai.<pkg>.<mod> import X → from <pkg>.<mod> import X
  2. import ai.<pkg> → import <pkg> as <pkg>
  3. Quoted type annotations "ai.<pkg>.<Class>" → "<pkg>.<Class>"
  4. TYPE_CHECKING block imports (same as 1/2)
  5. __all__ re-exports with ai.* fully-qualified names
  6. Pydantic model_rebuild() / update_forward_refs() calls
  7. Provenance headers # negelir-generated-from: ai/<path>@<sha256>
"""

from __future__ import annotations

from typing import TypedDict, Optional

# Type alias for corpus entry structure
class CorpusEntry(TypedDict, total=False):
    """Structure of a single corpus entry."""
    name: str
    input_code: str
    expected_output: str
    non_targets: list[str]


# ─────────────────────────────────────────────────────────────────────────
# CORPUS — Representative patterns for all 7 rewrite patterns
# ─────────────────────────────────────────────────────────────────────────

CORPUS: list[CorpusEntry] = [
    # ─── Pattern 1: from ai.<pkg>.<mod> import X ───
    {
        "name": "pattern_1_basic_from_import",
        "input_code": (
            "from common.config import Config\n"
            "x = Config()\n"
        ),
        "expected_output": (
            "from common.config import Config\n"
            "x = Config()\n"
        ),
    },
    {
        "name": "pattern_1_from_import_multiple_names",
        "input_code": (
            "from common.config import Config, cfg, load_config\n"
        ),
        "expected_output": (
            "from common.config import Config, cfg, load_config\n"
        ),
    },
    {
        "name": "pattern_1_nested_module_import",
        "input_code": (
            "from common.text.turkish import suffix_harmony_ok, normalize\n"
        ),
        "expected_output": (
            "from common.text.turkish import suffix_harmony_ok, normalize\n"
        ),
    },

    # ─── Pattern 2: import ai.<pkg> ───
    {
        "name": "pattern_2_import_with_alias",
        "input_code": (
            "import ai.common\n"
            "config = ai.common.config.Config()\n"
        ),
        "expected_output": (
            "import common as common\n"
            "config = ai.common.config.Config()\n"
        ),
    },
    {
        "name": "pattern_2_import_nested_module",
        "input_code": (
            "import nlp.dispatcher\n"
            "result = ai.nlp.dispatcher.dispatch(text)\n"
        ),
        "expected_output": (
            "import nlp.dispatcher as nlp\n"
            "result = ai.nlp.dispatcher.dispatch(text)\n"
        ),
    },

    # ─── Pattern 3: Quoted type annotations ───
    {
        "name": "pattern_3_quoted_type_in_annotation",
        "input_code": (
            "from typing import Optional\n"
            "def process(item: 'ai.common.Config') -> Optional['ai.common.Record']:\n"
            "    return None\n"
        ),
        "expected_output": (
            "from typing import Optional\n"
            "def process(item: 'common.Config') -> Optional['common.Record']:\n"
            "    return None\n"
        ),
    },
    {
        "name": "pattern_3_annotated_metadata",
        "input_code": (
            "from typing import Annotated\n"
            "ValidConfig = Annotated[dict, 'ai.common.Config']\n"
        ),
        "expected_output": (
            "from typing import Annotated\n"
            "ValidConfig = Annotated[dict, 'common.Config']\n"
        ),
    },
    {
        "name": "pattern_3_union_quoted_types",
        "input_code": (
            "from typing import Union\n"
            "Result = Union['ai.common.Config', 'ai.nlp.Intent', str]\n"
        ),
        "expected_output": (
            "from typing import Union\n"
            "Result = Union['common.Config', 'nlp.Intent', str]\n"
        ),
    },

    # ─── Pattern 4: TYPE_CHECKING block ───
    {
        "name": "pattern_4_type_checking_import",
        "input_code": (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from common.config import Config\n"
            "    from nlp.dispatcher import Dispatcher\n"
        ),
        "expected_output": (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from common.config import Config\n"
            "    from nlp.dispatcher import Dispatcher\n"
        ),
    },

    # ─── Pattern 5: __all__ re-exports ───
    {
        "name": "pattern_5_all_tuple_reexport",
        "input_code": (
            "__all__ = [\n"
            "    'ai.common.Config',\n"
            "    'ai.nlp.Intent',\n"
            "    'SomeLocal',\n"
            "]\n"
        ),
        "expected_output": (
            "__all__ = [\n"
            "    'common.Config',\n"
            "    'nlp.Intent',\n"
            "    'SomeLocal',\n"
            "]\n"
        ),
    },

    # ─── Pattern 6: Pydantic model_rebuild() ───
    {
        "name": "pattern_6_pydantic_model_rebuild",
        "input_code": (
            "from pydantic import BaseModel\n"
            "class MyModel(BaseModel):\n"
            "    config: 'ai.common.Config'\n"
            "    model_rebuild(_parent_namespace_depth=2)\n"
        ),
        "expected_output": (
            "from pydantic import BaseModel\n"
            "class MyModel(BaseModel):\n"
            "    config: 'common.Config'\n"
            "    model_rebuild(_parent_namespace_depth=2)\n"
        ),
    },
    {
        "name": "pattern_6_pydantic_update_forward_refs",
        "input_code": (
            "from pydantic import BaseModel\n"
            "class Record(BaseModel):\n"
            "    nested: 'ai.common.Record' = None\n"
            "    @classmethod\n"
            "    def setup(cls):\n"
            "        cls.update_forward_refs()\n"
        ),
        "expected_output": (
            "from pydantic import BaseModel\n"
            "class Record(BaseModel):\n"
            "    nested: 'common.Record' = None\n"
            "    @classmethod\n"
            "    def setup(cls):\n"
            "        cls.update_forward_refs()\n"
        ),
    },

    # ─── Pattern 7: Provenance headers ───
    {
        "name": "pattern_7_provenance_header",
        "input_code": (
            "# negelir-generated-from: ai/common/schemas/records.py@abc123def456\n"
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class GeneratedRecord:\n"
            "    pass\n"
        ),
        "expected_output": (
            "# negelir-generated-from: common/schemas/records.py@abc123def456\n"
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class GeneratedRecord:\n"
            "    pass\n"
        ),
    },

    # ─── Complex combined patterns ───
    {
        "name": "complex_typeddict_with_forward_refs",
        "input_code": (
            "from typing import TypedDict, TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from common.config import Config\n"
            "class ConfigDict(TypedDict):\n"
            "    settings: 'ai.common.Config'\n"
            "    description: str\n"
        ),
        "expected_output": (
            "from typing import TypedDict, TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from common.config import Config\n"
            "class ConfigDict(TypedDict):\n"
            "    settings: 'common.Config'\n"
            "    description: str\n"
        ),
    },
    {
        "name": "complex_protocol_definition",
        "input_code": (
            "from typing import Protocol\n"
            "class DataProvider(Protocol):\n"
            "    def get_data(self) -> 'ai.common.DataRecord':\n"
            "        ...\n"
        ),
        "expected_output": (
            "from typing import Protocol\n"
            "class DataProvider(Protocol):\n"
            "    def get_data(self) -> 'common.DataRecord':\n"
            "        ...\n"
        ),
    },
    {
        "name": "multi_import_statement_variety",
        "input_code": (
            "from common.config import Config\n"
            "import nlp.dispatcher\n"
            "from datasource.scraper.extractors import Extractor\n"
            "__all__ = ['ai.common.Config', 'Extractor']\n"
        ),
        "expected_output": (
            "from common.config import Config\n"
            "import nlp.dispatcher as nlp\n"
            "from scraper.extractors import Extractor\n"
            "__all__ = ['common.Config', 'Extractor']\n"
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────
# Non-target examples (must NOT be rewritten)
# ─────────────────────────────────────────────────────────────────────────

NON_TARGET_EXAMPLES: list[dict[str, str]] = [
    {
        "name": "sql_query_with_ai_reference",
        "code": 'query = "SELECT * FROM ai_tables WHERE ai_id = 1"\n',
        "description": "SQL string containing 'ai_' underscore pattern should NOT be rewritten",
    },
    {
        "name": "log_message_with_ai_reference",
        "code": 'logger.info("error in ai module: %s", exception)\n',
        "description": "Log message containing 'ai' should NOT be rewritten (not a module path)",
    },
    {
        "name": "comment_with_ai_reference",
        "code": "# This uses ai.common but should not rewrite the comment\npass\n",
        "description": "Comment containing 'ai.' should NOT be rewritten (comments are not code)",
    },
    {
        "name": "docstring_with_narration_about_ai",
        "code": '"""This function uses the ai module for processing."""\npass\n',
        "description": "Docstring narration should NOT be rewritten (not a type annotation)",
    },
    {
        "name": "string_with_partial_module_name",
        "code": 'description = "Using ai.serialization internally"\n',
        "description": "String containing module path not in annotation context should NOT be rewritten",
    },
]


__all__ = [
    "CORPUS",
    "NON_TARGET_EXAMPLES",
]
