# Static operational signals

Evidence scope: `STATIC_EXTRACTED` syntax and configuration evidence only. These records help an
SRE find likely process controls, network and datastore calls, deployment settings, migrations,
and health checks. They are not runtime evidence, do not prove production topology, and are not
automatically safe runbook commands.

| Category | Location | Why it was selected | Static excerpt |
|---|---|---|---|
| `process.exec` | `src/sre_kb/atlas/overlays.py:437-451` | starts an operating-system process | `subprocess.run( # noqa: S603 - fixed executable/argv, no shell [ git, "-C", str(root.resolve()), "log", "--format=", "--name-only", "-z",...` |
| `process.exec` | `src/sre_kb/clone.py:37-40` | starts an operating-system process | `subprocess.run( # noqa: S603 ["git", "clone", "--quiet", "--depth", "1", "--", target, str(clone_dest)], # noqa: S607 capture_output=True...` |
| `process.exec` | `src/sre_kb/llm/provider.py:92-96` | starts an operating-system process | `subprocess.run( # noqa: S603 self._run_args, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=se...` |
| `process.exec` | `src/sre_kb/publish/forge/github.py:93-95` | starts an operating-system process | `subprocess.run( # noqa: S603 cmd, capture_output=True, text=True, timeout=_GIT_TIMEOUT_S, env=env )` |
| `network.client` | `src/sre_kb/publish/forge/github.py:107-117` | calls an outbound network API | `urllib.request.Request( # noqa: S310 url, data=json.dumps(payload).encode(), method="POST", headers={ "Authorization": f"Bearer {token}",...` |
