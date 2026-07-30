import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from providers.registry import ProviderRegistry


@pytest.fixture
def registry():
    return ProviderRegistry()


def test_prefix_routing_ejgz(registry):
    assert registry.get_provider_for_trailer("EJGZ381046") == "phillips"


def test_prefix_routing_ss(registry):
    assert registry.get_provider_for_trailer("SS006051") == "skybitz"


def test_prefix_routing_tl(registry):
    assert registry.get_provider_for_trailer("TL658260") == "skybitz"


def test_prefix_routing_pla(registry):
    assert registry.get_provider_for_trailer("2436976PLA") == "fus1on"


def test_prefix_routing_7328(registry):
    assert registry.get_provider_for_trailer("7328718") == "fus1on"


def test_unknown_prefix(registry):
    assert registry.get_provider_for_trailer("XXXX_UNKNOWN") is None
