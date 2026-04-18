"""Pytest configuration for the AI test suite."""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: end-to-end tests that exercise real data and may be skipped "
        "when caches are missing.",
    )
