"""Run the shared decision-core vectors against the Python implementation."""

from vector_runner import load_vectors, run_vector
import pytest


@pytest.mark.parametrize(
    "name,vec",
    [(f"{n}:{v['name']}", v) for n, v in load_vectors()],
    ids=lambda p: p if isinstance(p, str) else "",
)
def test_vector(name, vec):
    run_vector(name, vec)
