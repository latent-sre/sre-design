# Third-party notices

This repository uses the following direct dependencies for read-only structural code discovery.
They run **in-process** through Python APIs. The integration does not invoke their CLIs, start a
daemon, register target-provided grammars, or expose rewrite operations.

| Dependency | Reviewed version | SPDX license | Purpose |
|---|---:|---|---|
| `ast-grep-py` | 0.45.0 | MIT | In-process structural matching for supported code and Bash |
| `tree-sitter-bash` | 0.25.1 | MIT | Bash concrete syntax trees and queries |
| `tree-sitter-sql` | 0.3.11 | MIT | SQL concrete syntax trees and queries |
| `tree-sitter-yaml` | 0.7.2 | MIT | YAML concrete syntax trees and queries |

The reviewed machine-readable record is
[`evidence/structural-search.cdx.json`](evidence/structural-search.cdx.json). The generated atlas
license inventory remains the source for the repository's complete Python dependency list.

`tree-sitter-dockerfile` is intentionally not a dependency: its 0.2.0 release has no Windows wheel.
Dockerfile support is a narrow local, read-only instruction parser and does not execute Docker.

## MIT notices

### ast-grep-py

Copyright (c) 2022 Herrington Darkholme

### tree-sitter-bash

Copyright (c) 2017 Max Brunsfeld

### tree-sitter-sql

Copyright (c) 2021 Derek Stride

### tree-sitter-yaml

Copyright (c) 2024 tree-sitter-grammars contributors  
Copyright (c) 2019-2021 Ika

The following license text applies to each dependency listed above:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software
> and associated documentation files (the "Software"), to deal in the Software without
> restriction, including without limitation the rights to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or
> substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
> BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
> NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
> DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

