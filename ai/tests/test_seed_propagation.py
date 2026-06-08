import random

import numpy as np

from common.config import Config
from ai.common.seed import propagate_global_seed


def test_propagate_global_seed_python_and_numpy_consistent() -> None:
    cfg = Config()
    cfg.global_seed = 12345

    propagate_global_seed(cfg)
    a1 = random.random()
    n1 = np.random.rand()

    # Re-seed and sample again to ensure deterministic repeatability
    propagate_global_seed(cfg)
    a2 = random.random()
    n2 = np.random.rand()

    assert a1 == a2
    assert n1 == n2
