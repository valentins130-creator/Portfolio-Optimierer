import numpy as np
import pytest

from portfolio_optimizer.data import DEMO_ASSETS, DEMO_CORR


@pytest.fixture
def demo_model():
    """(mu, cov) der Demo-Assetklassen, annualisiert."""
    mu = np.array([m for m, _ in DEMO_ASSETS.values()])
    vol = np.array([v for _, v in DEMO_ASSETS.values()])
    return mu, DEMO_CORR * np.outer(vol, vol)


@pytest.fixture
def rng():
    return np.random.default_rng(12345)
