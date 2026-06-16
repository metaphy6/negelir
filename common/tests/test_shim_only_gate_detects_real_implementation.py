"""Phase 18.3 — Adversarial tests for shim-only gate.

Ensures the shim-only lint correctly detects and rejects real implementation
patterns that commonly appear in the existing ai/ directory.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from subprocess import run, PIPE

import pytest

# Import the lint module
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "xops"))
from lint.ai_shims_only import validate_file


class TestShimOnlyGateDetectsRealCode:
    """Adversarial tests: verify detection of real implementation patterns."""

    def test_detects_scraper_extraction_code(self) -> None:
        """Should detect: real scraper extraction logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "scraper.py"
            impl_file.write_text(
                'from bs4 import BeautifulSoup\n'
                '\n'
                'def extract_matches(html):\n'
                '    soup = BeautifulSoup(html, "html.parser")\n'
                '    return soup.find_all("div", class_="match")\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_model_training_code(self) -> None:
        """Should detect: real model training logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "model.py"
            impl_file.write_text(
                'import xgboost as xgb\n'
                'from sklearn.preprocessing import StandardScaler\n'
                '\n'
                'class XGBPredictor:\n'
                '    def __init__(self):\n'
                '        self.model = xgb.XGBClassifier()\n'
                '        self.scaler = StandardScaler()\n'
                '\n'
                '    def fit(self, X, y):\n'
                '        X_scaled = self.scaler.fit_transform(X)\n'
                '        self.model.fit(X_scaled, y)\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_nlp_processing_code(self) -> None:
        """Should detect: real NLP processing logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "nlp_processor.py"
            impl_file.write_text(
                'from transformers import AutoTokenizer, AutoModel\n'
                '\n'
                'class NLPProcessor:\n'
                '    def __init__(self, model_name: str):\n'
                '        self.tokenizer = AutoTokenizer.from_pretrained(model_name)\n'
                '        self.model = AutoModel.from_pretrained(model_name)\n'
                '\n'
                '    def process(self, text: str):\n'
                '        tokens = self.tokenizer(text)\n'
                '        embeddings = self.model(**tokens)\n'
                '        return embeddings\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_conditional_imports(self) -> None:
        """Should detect: conditional logic around imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "conditional.py"
            impl_file.write_text(
                'if True:\n'
                '    from datasource.scraper import extract\n'
                'else:\n'
                '    from datasource.extractor import extract\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_initialization_logic(self) -> None:
        """Should detect: module-level initialization code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "init_logic.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'logger = logging.getLogger(__name__)\n'
                'CONFIG = load_config()\n'
                'CACHE = {}\n'
                '\n'
                'def _init_cache():\n'
                '    global CACHE\n'
                '    CACHE = extract.get_all_matches()\n'
                '\n'
                '_init_cache()\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_helper_utilities(self) -> None:
        """Should detect: utility functions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "utils.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'def filter_matches(matches):\n'
                '    """Filter matches by score."""\n'
                '    return [m for m in matches if m["score"] > 0.5]\n'
                '\n'
                'def sort_matches(matches):\n'
                '    """Sort matches by time."""\n'
                '    return sorted(matches, key=lambda m: m["time"])\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_exception_handling(self) -> None:
        """Should detect: exception handling logic."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "error_handler.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'def safe_extract(url):\n'
                '    try:\n'
                '        return extract(url)\n'
                '    except ConnectionError:\n'
                '        return None\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_loop_logic(self) -> None:
        """Should detect: loop constructs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "loop_logic.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'results = []\n'
                'for url in urls:\n'
                '    results.append(extract(url))\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_async_code(self) -> None:
        """Should detect: async function definitions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "async_processor.py"
            impl_file.write_text(
                'import asyncio\n'
                'from datasource.scraper import extract\n'
                '\n'
                'async def process_url(url):\n'
                '    result = await extract(url)\n'
                '    return result\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_with_context_manager(self) -> None:
        """Should detect: with/context manager statements."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "context_manager.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'with open("data.json") as f:\n'
                '    data = json.load(f)\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_detects_multiple_violations_in_one_file(self) -> None:
        """Should detect: file with multiple violations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "multi_violation.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                'import requests  # Disallowed import\n'
                '\n'
                'class Extractor:\n'
                '    def run(self, url):\n'
                '        response = requests.get(url)\n'
                '        return extract(response.text)\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_edge_case_all_as_variable_reference(self) -> None:
        """Should detect: __all__ assigned from variable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "all_var_ref.py"
            impl_file.write_text(
                'from datasource.scraper import extract\n'
                '\n'
                'exports = ["extract"]\n'
                '__all__ = exports\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False

    def test_mixed_valid_and_invalid_imports(self) -> None:
        """Should detect: mix of allowed and disallowed imports."""
        with tempfile.TemporaryDirectory() as tmpdir:
            impl_file = Path(tmpdir) / "mixed_imports.py"
            impl_file.write_text(
                'from common.schemas import Record\n'
                'from datasource.scraper import extract\n'
                'import json  # Disallowed\n'
                'from swarm.predictor import predict\n',
                encoding="utf-8",
            )
            assert validate_file(impl_file) is False
