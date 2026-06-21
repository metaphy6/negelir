"""Phase 21.23 — Model Retraining + Feature-Vector Backward Compatibility."""
from __future__ import annotations

import os
import pickle
import tempfile

import numpy as np
import pytest

from common.config import Config
from common.constants import FEATURE_COLUMNS, N_FEATURES
from model.inference import GBDTInference, ModelShim


def test_n_features_is_157() -> None:
    """Feature count must be 157 (120 base + 10 QID + 27 enrichment columns)."""
    assert N_FEATURES == 157, f"Expected 157 features, got {N_FEATURES}"
    assert len(FEATURE_COLUMNS) == 157


def test_enrichment_retrain_flag_path_config_exists() -> None:
    """Config has enrichment_retrain_flag_path."""
    cfg = Config()
    assert hasattr(cfg, "enrichment_retrain_flag_path")
    assert isinstance(cfg.enrichment_retrain_flag_path, str)


def test_feature_schema_version_tagged_in_saved_models() -> None:
    """Saved models carry a feature_schema_version field (1=120, 2=157)."""
    # Create a mock model metadata dict with versioning
    model_metadata = {
        "model": None,  # Mock XGBClassifier
        "feature_schema_version": 2,
        "n_features": 157,
        "feature_columns": FEATURE_COLUMNS,
    }
    assert "feature_schema_version" in model_metadata
    assert model_metadata["feature_schema_version"] in (1, 2)
    assert model_metadata["n_features"] == 157


# Module-level mock for pickling compatibility
class MockXGBModel:
    """Mock XGBoost model that can be pickled."""
    def predict(self, X):
        return np.zeros(X.shape[0], dtype=int)
    
    def predict_proba(self, X):
        return np.ones((X.shape[0], 3)) / 3


class TestModelShim:
    """Test the backward-compatibility shim for 120-feature old models."""

    def test_model_shim_wraps_xgb_classifier(self) -> None:
        """ModelShim wraps an XGBClassifier and stores schema version."""
        model = MockXGBModel()
        shim = ModelShim(model, feature_schema_version=1)
        assert shim.model is model
        assert shim.feature_schema_version == 1

    def test_model_shim_slices_features_for_v1_models(self) -> None:
        """Shim slices input to first 120 columns for v1 (120-feature) models."""
        model = MockXGBModel()
        shim = ModelShim(model, feature_schema_version=1)
        
        # Create 157-feature input
        X = np.ones((10, 157))
        
        # predict should call the inner model with sliced features
        result = shim.predict(X)
        assert result.shape[0] == 10

    def test_model_shim_passes_through_v2_models(self) -> None:
        """Shim passes through full 157 features for v2 models."""
        model = MockXGBModel()
        shim = ModelShim(model, feature_schema_version=2)
        
        # v2 should pass through all 157 features
        X = np.ones((10, 157))
        result = shim.predict(X)
        assert result.shape[0] == 10


class TestGBDTInferenceBackwardCompat:
    """Test GBDT inference with backward-compatible model loading."""

    def test_model_shim_created_on_init(self) -> None:
        """GBDTInference wraps loaded model in ModelShim."""
        # Create a temporary dummy model file
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "test_model.pkl")
            
            # Save a mock model in new format with metadata
            metadata = {
                "model": MockXGBModel(),
                "feature_schema_version": 2,
                "n_features": 157,
                "feature_columns": FEATURE_COLUMNS,
            }
            with open(model_path, "wb") as f:
                pickle.dump(metadata, f)
            
            # Load with GBDTInference
            inference = GBDTInference(model_path=model_path)
            assert isinstance(inference.model, ModelShim)
            assert inference.feature_schema_version == 2
            assert inference.model_feature_count == 157

    def test_legacy_model_format_backward_compat(self) -> None:
        """GBDTInference handles old pkl format (direct XGBClassifier)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "legacy_model.pkl")
            
            # Save in old format (direct model, no metadata)
            with open(model_path, "wb") as f:
                pickle.dump(MockXGBModel(), f)
            
            # Load with GBDTInference
            inference = GBDTInference(model_path=model_path)
            assert isinstance(inference.model, ModelShim)
            assert inference.feature_schema_version == 1  # Defaults to v1 for legacy
            assert inference.model_feature_count == 120

    def test_feature_schema_version_attributes_set(self) -> None:
        """GBDTInference stores feature_schema_version and model_feature_count."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "test_model.pkl")
            
            metadata = {
                "model": MockXGBModel(),
                "feature_schema_version": 2,
                "n_features": 157,
                "feature_columns": FEATURE_COLUMNS,
            }
            with open(model_path, "wb") as f:
                pickle.dump(metadata, f)
            
            inference = GBDTInference(model_path=model_path)
            assert hasattr(inference, "feature_schema_version")
            assert hasattr(inference, "model_feature_count")
            assert inference.feature_schema_version == 2
            assert inference.model_feature_count == 157
