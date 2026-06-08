"""Go collector — a config-parse tech-stack slice for a fifth stack (after Java, .NET, Python, Node).

Parses `go.mod` directly (no AST, no new dependency) so a Go service's TechStack is fact-grounded —
web framework + runtime + direct module dependencies — instead of the presence-only DERIVED roll-up
the manifest detector gives it. HTTP route/egress/resiliency extraction needs a Go AST
(tree-sitter-go) and is the documented follow-up, mirroring the Node and Python slices.
"""
