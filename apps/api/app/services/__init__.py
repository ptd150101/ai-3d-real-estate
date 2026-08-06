"""Service package initialization.

Local demo hooks are installed here so both the API process and background worker use
the same deterministic reconstruction behavior.
"""

from .demo_reconstruction_hooks import install_demo_reconstruction_hooks

install_demo_reconstruction_hooks()
