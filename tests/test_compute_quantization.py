"""Tests for int8/int4 quantization and affine transformations.

Covers quantization-aware training hooks, dtype preservation, scale/zero_point
storage, and quantized model loading.

Reference: docs/design/phase11/sections/20-tests.md §11.20
"""

import pytest


class TestQuantization:
    """Test suite for quantization and low-precision model support."""

    def test_quantized_model_loads_with_correct_dtype(self):
        """int8 model loads with int8 weights; dtype preserved at all layers.
        
        TODO: implement when Phase 11 lands
        """
        pass

    def test_quantization_aware_training_hooks(self):
        """QAT config wired correctly; checkpoints save scale/zero_point tensors.
        
        TODO: implement when Phase 11 lands
        """
        pass

    def test_int4_quantization_dynamic_range(self):
        """int4 quantized model respects dynamic range; no over/underflow.
        
        TODO: implement when Phase 11 lands
        """
        pass
