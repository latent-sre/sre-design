"""Node.js collector — a config-parse tech-stack slice for a fourth stack (after Java, .NET, Python).

Parses `package.json` directly (no AST, no new dependency) so a Node service's TechStack is
fact-grounded — framework + runtime + runtime dependencies — instead of the presence-only DERIVED
roll-up the manifest detector gives it. Endpoint/egress/resiliency extraction needs a JavaScript AST
(tree-sitter-javascript) and is the documented follow-up, mirroring how the Python slice started.
"""
