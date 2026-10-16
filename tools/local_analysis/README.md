# Local analysis integration (Windows)

Source-only bridge to an **already installed** local REA/Ghidra toolchain and offline EmbeddingGemma 2. Nothing runs on checkout. The bridge does not install providers, fetch models, call a hosted model API, or fall back to a cloud service. `download.py` is a separate, explicitly invoked network downloader, not an offline inference command.

## Portable setup

Use PowerShell 7, an existing Node.js 22+ runtime, and an existing compatible Windows Python runtime. Runtime executables, JDK/Ghidra/REA, virtual environments, weights, caches, private configuration and generated evidence are not included. Choose and verify your own compatible existing REA, Ghidra and JDK versions; they are not pinned by this package.

1. Work from this directory. Copy `config.example.json` to ignored `config.local.json`. Replace every placeholder with a verified machine-local absolute path: Node executable, REA CLI JavaScript entry, Ghidra directory, JDK directory and an existing private writable temporary directory. The example contains no credentials and its placeholders are not executable configuration.
2. Set `$env:JARVIS_LOCAL_TOOLS_ROOT = (Get-Location).Path`. This root must contain these source files and your ignored local config. No original installation is modified by setup here.
3. For embedding use, provision a private `embeddinggemma/.venv` yourself. `requirements.txt` contains direct pins; `requirements.lock.txt` preserves the original environment's exact dependency versions, not hashes or a cross-platform guarantee. Review package provenance, availability and compatibility before any separately approved installation. No setup or validation script installs dependencies. If desired, the manual commands are `python -m venv embeddinggemma/.venv` and `embeddinggemma/.venv/Scripts/python.exe -m pip install -r embeddinggemma/requirements.lock.txt`. These commands are **not** part of validation and were not executed for this package.
4. Provide the verified model at `embeddinggemma/model`. Use only official `google/embeddinggemma-2`, pinned revision `914f7f89142e33e77833254d9c9b90c3cef7303b`. The tracked `model-api.json` is only a public id/revision seed, not weight-integrity evidence.

### Optional explicit model acquisition, separate from inference

Review the official model card and applicable Gemma/model terms, access restrictions, redistribution and authorized-use requirements at https://huggingface.co/google/embeddinggemma-2 before acquiring weights. This package grants no model or third-party license and accepts no terms for you. Do not place tokens or private documents in tracked files.

`download.py` requires both `embeddinggemma/model-api.json` (included) and a locally prepared `embeddinggemma/model-tree.json` (not included). Obtain the complete recursive public file listing for the exact pinned revision from:

`https://huggingface.co/api/models/google/embeddinggemma-2/tree/914f7f89142e33e77833254d9c9b90c3cef7303b?recursive=true&expand=false`

Follow any pagination and combine the pages into one JSON array. Preserve each file's `type`, `path`, `size` and available `lfs.oid` fields; use only trusted official metadata and safe repository-relative paths. Then, only after explicitly choosing to download, run `python embeddinggemma/download.py`. It downloads files from the pinned official resolve URL and records local size/SHA-256 checks in ignored `integrity.json`; an LFS digest is compared where supplied. Non-LFS files have a recorded digest and size check, not an independent trusted SHA-256 comparison. The downloader does not generate `model-tree.json` or authenticate gated access for you. No model download was performed during packaging.

## Explicit local usage

From this directory, after the relevant setup above:

```powershell
$env:JARVIS_LOCAL_TOOLS_ROOT = (Get-Location).Path
./run_local_analysis_tools.ps1 -Mode doctor
./run_local_analysis_tools.ps1 -Mode providers
# Only a binary you own or have explicit authorization to analyze:
./run_local_analysis_tools.ps1 -Mode inspect -Target ./fixtures/jarvis-owned.dll -AuthorizedTarget
./run_local_analysis_tools.ps1 -Mode function -Target ./fixtures/jarvis-owned.dll -Procedure jarvis_answer -AuthorizedTarget
# Explicit-input retrieval; create/select your own local JSON file first:
./run_local_analysis_tools.ps1 -Mode embedding-search -Query 'Find relevant text' -Documents ./documents.json -Dimension 256
```

`documents.json` is an illustrative input path, not an included document. Keep real inputs outside Git. Its format is an array of `{ "id": "unique-id", "text": "explicitly selected text" }`. Search permits 1..64 documents, at most 4,000,000 input bytes, ids 1..128 characters, texts 1..5000 characters, query 1..1000 nonblank characters, top-k 1..10 and dimensions 768 or 256. `--code` / bridge `-CodeQuery` selects the code-retrieval prompt. Results are similarity rankings, never safety/legal/publication approval. Evidence can contain local input paths and hashes; keep it private. There is no automatic file discovery.

`node ./create-owned-fixture.mjs` explicitly generates a tiny authored PE64 fixture in ignored `fixtures/`; it does not execute the binary. No fixture binary is shipped or generated by validation. `-Mode mcp` starts the installed local REA MCP server; exposed tools retain their own side-effect boundaries. The bridge's `-AuthorizedTarget` gate covers `inspect`/`function`, not every later MCP tool call. Do not expose a local server to untrusted clients.

## Inference scope and bounds

- `embeddinggemma/run.ps1` / bridge `embedding-smoke` runs the authored text/code smoke suite. `search.py` handles only the supplied text documents. Both use CPU BF16, batch 1, two threads, 256-token truncation including prompts, below-normal Windows process priority, physical headroom >=512 MiB and remaining commit >=3 GiB. Exported vectors are FP32-renormalized.
- `vision_smoke.py` is a separate explicit image/text smoke suite using three authored 256x256 geometric PNGs, CPU FP32, batch 1, two threads, max 1024 tokens, physical headroom >=2.5 GiB and remaining commit >=6 GiB. Audio is disabled; no audio/video suite is included. Its outputs stay ignored.
- **Never use FP16.** Inference uses only local files, offline Hugging Face/Transformers flags, disabled telemetry and `trust_remote_code=False`. No remote inference/API billing is authorized. Existing runtimes/providers must be separately trusted; the wrapper is not a network sandbox. Download bandwidth and local resource costs are separate from model API billing.
- `wait_and_run.py` is an optional explicit waiter: it checks every 20 seconds, waits indefinitely for 2.2 GB available physical memory, then runs the text smoke once (which applies its additional commit/headroom guards). It does not stop unrelated processes or change system paging. It is not run by validation.

## Bounded source validation

```powershell
./tests/validate.ps1  # Optional -Python / -Node select already existing runtimes
```

Executed for this packaging task: three PowerShell AST parses, five Python source AST parses, pinned metadata and safety-guard presence assertions, JavaScript syntax-only parsing, search `--help`, and nine invalid-input rejection cases before heavy imports (15-second subprocess timeout per case). Temporary validation JSON is created and removed only under `tests/`. No installation, model download, provider invocation, fixture execution, API call, or new actual model inference is claimed. These are packaging/regression checks, not proof of model quality or full runtime compatibility. Existing local runtime and its prior evidence remain untouched.
