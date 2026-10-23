# User Preferences

## Build preferences

This machine may run Linux or Windows. Detect the platform before choosing shell commands; do not assume Linux.

When building C++/CMake projects, prefer parallel builds.

Recommended build parallelism:
- Use all available CPU cores unless memory pressure is high, capped at a maximum of 64 jobs.
- Determine the core count dynamically:
  - Linux: `nproc`
  - Windows PowerShell: `$env:NUMBER_OF_PROCESSORS`
  - Windows cmd: `%NUMBER_OF_PROCESSORS%`
  - Git Bash: `nproc` if available, otherwise `$NUMBER_OF_PROCESSORS`
- If it exceeds 64, cap it at 64.
- Default CMake build parallelism: `cmake --build build -j N`; with the Visual Studio generator use `cmake --build build --parallel N`.
- Default Make/Ninja parallelism: `make -j N` / `ninja -j N`

If a build fails due to memory exhaustion, reduce parallelism to 8 jobs or fewer.

## Output language

- Reply in Simplified Chinese only. Do not mix languages.
- Keep code, commands, file paths, identifiers, model/API names, and error messages verbatim; translate only natural-language prose. When quoting an error, keep the original text and put the Chinese explanation after it.
- The thinking/reasoning process must also be in Chinese.

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->
