# ckanext-unfold Audit

Full review of the archive-preview plugin at version 3.0.1 (commit `46fa35e`, "fix: fix local resource download"): security, correctness, performance, test coverage, user experience, architecture and packaging. Findings are ranked by severity within each area and reference the exact file and line.

- **Target at audit time:** CKAN 2.12, Python >= 3.11 (widened since to CKAN >= 2.11, Python >= 3.10; see below)
- **Scope:** 1,455 lines of Python across 13 modules, 2 templates, 1 JS module, SCSS, config, CI, packaging
- **Audited:** 15 September 2026

**Since the audit:** the supported floor was widened from CKAN 2.12 to CKAN >= 2.11. `ckan.lib.files` (file-keeper storage) is imported behind a try/except in `adapters/base.py`, since it does not exist before 2.12; uploads on 2.11 go through the legacy local-path and download-fallback branches BUG-1's fix already added. `datetime.UTC` (Python >= 3.11 only) was replaced with `datetime.timezone.utc` in `formatting.py`, since CKAN 2.11's only published Docker image is Python 3.10. CI now runs both `2.12`/Python 3.14 and `2.11`/Python 3.10; pyright runs only against 2.12, since it cannot resolve `ckan.lib.files` against a real 2.11 install even behind the runtime guard.

## Summary

The plugin does one job well: it turns fifteen archive formats into a jstree file listing with a Redis cache, and the recent 2.12 refactor made the remote-fetch path noticeably safer (size limits, streaming, zip tail-range fetch). Since the audit, all four of the original pre-release blockers have been fixed: the upload-path crash, the zip-tail-fetch limit on large archives, the stored cross-site scripting hole through archive entry names (the widget now renders entry names and metadata as plain DOM text instead of the API returning markup at all). CI now runs against CKAN 2.11 and 2.12 with linting enabled, and the test suite covers the actions, the Redis cache, the plugin hooks and every adapter instead of asserting only node counts.

| Area                 | Critical | High | Medium | Low | Total |
|----------------------|---------:|-----:|-------:|----:|------:|
| Bugs                 | 0        | 0    | 1      | 1   | 2     |
| Performance          | 0        | 1    | 2      | 2   | 5     |
| Tests & CI           | 0        | 1    | 0      | 0   | 1     |
| UX & accessibility   | 0        | 0    | 0      | 1   | 1     |
| Architecture         | 0        | 0    | 1      | 1   | 2     |
| **All**              | **0**    | **2**| **4**  | **5**  | **11**|

Findings closed since the audit are removed from this document rather than kept as dead entries; a status note on a still-open finding records any partial progress.

Severity scale:

- **Critical** – exploitable by any user against other users
- **High** – breaks the feature or leaks data in realistic setups
- **Medium** – wrong under common inputs, or a real maintenance cost
- **Low** – polish, dead code, minor inconsistency

---

## Bugs

### BUG-6 · Medium · Cache invalidation misses most edit paths

`plugin.py:69-86`, `utils.py:172-193`, `ckan/lib/uploader.py:335, 554`

Three separate problems. The `url_type == "url"` comparison never matches because CKAN stores an empty string for link resources, so the "skip when URL unchanged" branch is dead. `before_resource_update` fires only from `resource_update` and `resource_patch`; edits through `package_update`, `package_patch`, harvesters and the dataset form never invalidate, leaving a stale tree for up to 24 hours. And the key is the resource id alone, so a changed password or format serves the old tree.

**Fix:** Also implement `IPackageController.after_dataset_update` and compare resource url, last_modified and format against the previous state; include a hash of the inputs that affect the result in the Redis key; add a `ckan unfold clear-cache [resource-id]` CLI command.

### BUG-7 · Low · Config description contradicts its validator

`config_declaration.yaml:22-30`, `ckan/logic/validators.py:143-149`

The description of `expand_nodes_threshold` says "Set to 0 to always collapse nodes", but `is_positive_integer` rejects anything below 1, so CKAN refuses to start with that value.

**Fix:** Use `int_validator` with a non-negative check, or change the documentation to "set to 1".

---

## Performance

### PERF-1 · High · Fetch and parse run synchronously inside the web request

`logic/action.py:36`, `adapters/base.py:18, 131`, `adapters/zip.py:49-62`

Every uncached view blocks a web worker for a download of up to 50 MB with a 60-second socket timeout, then a full parse. The zip tail strategy can issue up to six sequential requests for one archive (64 KiB, 256 KiB, 1 MiB, 4 MiB, 16 MiB, then the whole file), each re-downloading a larger suffix. Typical uWSGI and gunicorn harakiri limits are 30 seconds, below the plugin's own timeout, so slow origins produce worker kills rather than an error message. A handful of concurrent first-time views of large archives is enough to exhaust a small worker pool.

**Fix:** Compute the tree in a CKAN background job enqueued on view creation and on cache invalidation; have the JS poll a lightweight status action. Make the timeout configurable and keep it below the worker timeout. As an interim step, populate the cache at `resource_view_create` time so the first page view is warm.

### PERF-2 · Medium · Whole archive is buffered in memory, even for local files

`adapters/base.py:138-148, 160`, `adapters/zip.py:31-34`, `adapters/tar.py:64`

Remote content is collected as a chunk list and then joined, doubling peak memory at 50 MB per request. Local uploads go through `storage.content()`, which reads all bytes, although file-keeper storages offer `stream()`. A local zip is read in full and wrapped in `BytesIO` when a seekable file handle would let `zipfile` read only the central directory.

**Fix:** Hand adapters a seekable file object (a `SpooledTemporaryFile` for remote, the storage stream or path for local) instead of bytes; zipfile, tarfile, rarfile and py7zr all accept one.

### PERF-3 · Medium · Cache stores and re-hydrates the fattest representation

`utils.py:136-154`, `logic/action.py:41-45`

Each cached node serializes constant fields (`state`, `a_attr`, `li_attr`, `children`) alongside the data, roughly 200 bytes per node. The 15,004-node test fixture becomes about 3 MB of JSON that is parsed into dataclasses on every page view, then copied again by `asdict` in `_serialize_node`. The action could return the cached string directly.

**Fix:** Cache the final serialized payload (optionally compressed) and return it verbatim; if the size threshold must be applied per request, store it as a flag rather than rewriting every node.

### PERF-5 · Low · Redis "singleton" wraps an already-pooled client and never closes

`utils.py:117-169`

`connect_to_redis()` returns a client backed by a connection pool, so the class-level caching adds nothing and the `close()` method is never called. The lazily-created connection is safe under prefork servers only because nothing touches it before fork; that is luck, not design.

**Fix:** Call `connect_to_redis()` per operation, or keep the wrapper but drop the cached connection.

### PERF-6 · Low · Search runs a substring test over three fields for every node

`assets/js/unfold-init-jstree.js:116-123`

The custom `search_callback` matches against id, size and modified date. Matching sizes like "1.2" or dates is rarely useful and triples the work; matching the full path via `node.id` is the useful part. Fine at the current scale, worth noting if lazy loading is adopted since jstree's search then needs the `search.ajax` option.

**Fix:** Match on path only unless there is a known need; document the behaviour in the placeholder ("Search paths").

---

## Tests & CI

### TEST-2 · High · Most of the plugin has no tests at all

`tests/test_unfold.py`

**Status: largely fixed in the working tree.** New modules cover the actions (`test_action.py`: full and lazy modes, paging, search, error payloads, foreign and unknown view ids, private-dataset authorization), HTML escaping in `_serialize_node` (`test_serialize.py`), the Redis cache and cache hits in `get_archive_index` (`test_cache.py`), `can_view` and every cache-invalidation hook (`test_plugin.py`), adapter lookup, the signal protocol and the small helpers (`test_utils.py`), and in `test_unfold.py`: size enforcement on the full-download path (declared size, Content-Length, streaming abort, unparsable size), HTTP errors, the tabledesigner rejection, the password zip fixture, generated 7z archives with encrypted entries and headers, `ensure_dir_entries`, and every format on truncated, garbage and empty input. Still untested: validators against the database, template rendering and the JavaScript module.

All four tests exercise one path: `adapter(…, filepath=url).build_archive_tree()` over a mocked HTTP server. Nothing covers:

- the `get_archive_structure` action: authorization, missing or foreign `view_id`, the `{"error"}` shape, the expand threshold;
- `_serialize_node` and HTML escaping (SEC-1 would have a failing test today);
- `UnfoldCacheManager` save / get / delete / TTL, and cache hits in `get_archive_tree`;
- plugin hooks: `can_view`, every branch of `before_resource_update`, `before_resource_delete`;
- size enforcement: Content-Length rejection, streaming abort, missing Content-Length, string `size` metadata;
- zip tail growth when the central directory exceeds 64 KiB, and a server that ignores Range;
- password-protected RAR (correct and wrong password), 7z with encrypted headers, and the `test_archive_pass.zip` fixture, which is checked in but never used;
- corrupt or truncated input per format, the tabledesigner rejection, the signal protocol (adapter / None / False), `ensure_dir_entries`, `printable_file_size`, `get_icon_by_format`, validators, config helpers;
- template rendering and any JavaScript.

**Fix:** Add action-level tests with `call_action` and factories first (they cover the most code per test), then adapter edge cases with hand-built archives generated in the test, then a coverage floor in CI.

---

## UX & accessibility

### UX-5 · Low · Right-click menu only ever offers Expand / Collapse

`assets/js/unfold-init-jstree.js:131-182`, `types.py:20`

No built-in adapter sets `a_attr.href`, so "Open URL" and "Copy URL" never appear; the context menu setting ends up controlling a menu with one item that duplicates a click. "Copy URL" also gives no feedback and silently fails on non-HTTPS pages where `navigator.clipboard` is unavailable. The whole href machinery only matters for custom adapters, which the README example shows but the option description does not explain.

**Fix:** Hide the context menu when no node has an href, or add useful items (copy path, download entry once supported), and show a toast after copy.

---

## Architecture

### ARCH-4 · Medium · Errors are HTTP 200 with an "error" key, and nothing is logged

`logic/action.py:37-38`; every module defines `log` and never uses it

Failures are returned as `{"error": "…"}` inside a successful API response, so API clients cannot distinguish a listing from a failure without inspecting the type of `result`. Each module creates a logger and none of them emits a line, so an operator investigating "the preview does not work" has no server-side trace at all.

**Fix:** Log every caught exception with resource id at WARNING; return a structured error (`{"error": {"code": "password_required", "message": …}}`) so the JS can branch, or raise `ValidationError` for caller mistakes.

### ARCH-6 · Low · Format detection relies solely on the resource "format" string

`utils.py:209, 220`, `adapters/__init__.py:6-22`

CKAN users type formats freely, so `TGZ`, `GZ`, `application/zip` and `Zip Archive` all miss the registry and `can_view` returns false, while a `.tar.gz` labelled `TAR` is routed to the plain tar adapter and fails.

**Fix:** Normalize with CKAN's `resource_formats` table, fall back to the URL extension, and add aliases (`tgz`, `tbz2`, `txz`, MIME types).

---

## Suggested order of work

Sequenced so each step makes the next one safer. CI and all four of the audit's original pre-release blockers (the upload-path crash, the zip-tail-fetch limit, the stored XSS hole, and the dead File URL option) are already fixed; what is left is iteration work, not blockers.

3. **Cache and jobs** (BUG-6, PERF-1, PERF-3): invalidation on dataset update, cached payload, background computation. Two to three days.

---

## How this was verified

Every Python, template, JavaScript, SCSS, config and CI file in the repository was read in full, along with the git history since the 2.12 refactor and the parts of CKAN 2.12 the plugin calls into (uploader classes, view dictization, validators, the edit-view templates). No CKAN runtime was available in the audit environment, so the test suite and pyright were not executed; ruff was installed and run. Claims that depended on runtime behaviour were checked individually:

- jstree 3.3.16 defaults to `force_text: false` and assigns node text via `innerHTML` (grep of the vendored bundle).
- `datetime(*(1980, 0, 0, 0, 0, 0))` raises `ValueError`, and `zipfile` produces exactly that tuple for a zero date field (reproduced with a generated archive).
- `resource_view_dictize` merges the view's `config` into the returned dict.
- CKAN writes `url_type = ""` for link resources.
- `is_positive_integer` rejects zero.
- The edit-view page renders the preview outside the form element, so the inert submit button cannot submit the view form (checked and therefore not listed as a bug).
- The generated SOURCES.txt contains no `.gif` or `.png` entries.
- The vendored jstree CSS references `../../../32px.png`.

Findings marked as likely rather than reproduced: worker-timeout figures in PERF-1 are typical defaults, not measurements from this deployment.
