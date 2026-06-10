"""sre_kb — deterministic engine for building a validated SRE knowledge base.

The engine embeds no LLM; the judgment half runs through the `LLMProvider` seam
(Copilot in VS Code by default, any LLM CLI via `--oracle`) and every output is
re-ground and gated deterministically. See docs/DESIGN.md.
"""

__version__ = "0.0.1"
