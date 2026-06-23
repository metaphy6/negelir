"""Negelir — ML model and feature engineering.

Pivot v3 component: model (moved from ai/model/ in Phase 22.4).

Public API: feature engineering, model inference, device management.
"""

__all__ = [
    # Feature engineering
    "inject_noise",
    "extract_features_for_match",
    # Model operations
    "Model",
    # Device/compute
    "DeviceManager",
    "DeviceTelemetry",
]
