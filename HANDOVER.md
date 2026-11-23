# Handover: Instance Checker

## What it is

A Blender **extension** (add-on) that finds mesh objects that are copies of each
other, makes them share one mesh (linked data, like Alt+D) and back, and reports
how much memory that saves. It lives in the 3D Viewport sidebar (**N › Instances**).
Each object keeps its own modifiers, materials and transform.

It is an original project, not a fork, so there is no upstream to merge from.
It was called *Copy Instancer* before the first release; that name was never
published.

## What you need

- **Blender 5.3** (the only supported version). The scripts find it through
  `--blender PATH`, `$BLENDER`, `blender` on `PATH`, or the default install
  (`/Applications/Blender.app/...` on macOS,
  `C:\Program Files\Blender Foundation\Blender 5.3\blender.exe` on Windows).
- **Python 3.11+** on the host to run the helper scripts (they only launch Blender;
  `tests/check_versions.py` needs `tomllib`).
- `git` and, for releases, push access to
  `https://github.com/mttfntn/instance-checker-blender` (public).

Third-party code: none is bundled. The add-on uses **numpy**, which ships with
Blender (BSD-3-Clause), and Blender's own `bpy` / `mathutils` (GPL).

## How the code is organized

| Path | What it is |
|---|---|
| `instance_checker/__init__.py` | Registers the three modules below, in order. |
| `instance_checker/matching.py` | Copy detection: topology key, attribute and vertex-group signatures, shape match (with the applied-transform fit), grouping, memory estimate. No `bpy.ops`, no UI, changes nothing. |
| `instance_checker/properties.py` | Scene settings and the scan list (`scene.instance_checker`). Objects and meshes are stored **by name**. |
| `instance_checker/operators.py` | `scan()`, `instance_group()`, `make_copies()` and the six operators (`bpy.ops.instance_checker.*`). |
| `instance_checker/ui.py` | The sidebar panel and the group list. |
| `instance_checker/blender_manifest.toml` | Extension manifest: id, version, **supported Blender range**, license. |
| `LICENSE` | GPL-3.0-or-later. Copied into the zip at build time. |
| `tests/run.py` | Starts Blender headless with a **throwaway profile** and runs a script in it. |
| `tests/test_instance_checker.py` | The test suite (64 checks). Default script of `tests/run.py`. |
| `tests/compare_behaviour.py` | Runs two versions on 72 generated cases and diffs the results. |
| `tests/check_installed_package.py` | Installs a built zip in a scratch profile and uses it. |
| `tests/check_versions.py` | Checks that every place naming the supported Blender version agrees. |
| `tools/build.py` | Reproducible build of `dist/instance_checker-<version>.zip`, with a content digest. |
| `.github/workflows/ci.yml` | CI on Linux, Windows and macOS; release on `vX.Y.Z` tags. |
| `.github/scripts/get_blender.py` | Downloads Blender for CI: mirrors, retries, pinned SHA-256. |
| `README.md` | User docs. |
| `HANDOVER.md`, `AGENTS.md` | This file and its compact twin for AI assistants. Not shipped. |
| `CONTRIBUTING.md`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` | Community files. |

## How the main feature works

1. **Scan** (`operators.scan` → `matching.find_groups`):
   - Objects that already share a mesh count once per mesh. Meshes with shape
     keys, linked objects and empty meshes are left out.
   - Meshes are bucketed by `topology_key`: vertex/edge/face/corner counts, the
     number of material slots and a hash of the corner, face-size and edge arrays.
     These are read through the `.corner_vert` / `.edge_verts` attributes, which is
     much faster than `mesh.loops` / `mesh.edges` (see "Things to know").
   - In a bucket, each mesh joins the first cluster whose reference has the same
     vertex-group weights, the same attributes (floats within *Tolerance*;
     selection, hide and UV-pin state ignored) and a matching shape.
     `match_shape` first compares local positions directly, then (with *Match
     Applied Transforms*) fits a rotation + uniform scale + translation with the
     Umeyama method and accepts it if every vertex lands within tolerance.
     Reflections are rejected. The result is a 4×4 matrix *T* from the reference
     mesh to the member's mesh.
   - `store_result` copies the groups into `scene.instance_checker.groups`.
2. **Instance** (`operators.instance_group`):
   - Skips members that were renamed/deleted, whose mesh changed since the scan,
     that need a transform change but are animated or constrained, or (with
     *Verify Result*) that need one, have modifiers and aren't evaluated.
   - Records each member's evaluated world positions, then sets
     `obj.data = reference`. If *T* isn't the identity, sets
     `matrix_world = old_matrix @ T` and puts its children's world matrices back.
     Material slots whose material would change are switched to *Object* link
     with the old material.
   - *Verify Result* re-evaluates and reverts every object whose geometry moved by
     more than `max(10 × tolerance, 1e-5 × size)` (`_same_result`).
   - Replaced meshes with no users left are removed. The list is re-scanned.
3. **Make copies** (`operators.make_copies`): `obj.data = obj.data.copy()` per
   object; when every user of a mesh is a target, the first keeps the original.

## How to make a change

1. Edit the code in `instance_checker/`.
2. Add or update a check in `tests/test_instance_checker.py`. For a bug fix, the
   check must fail without the fix.
3. Run `python tests/run.py`. Everything must pass.
4. If the change should not alter behaviour, compare with the previous version
   (below).
5. To try it in Blender: `python tools/build.py`, then install the zip
   (Preferences › Get Extensions › ⌄ › Install from Disk). Use a separate profile
   if you can, not your production one.
6. Small commits with clear messages; push to `main`; check the Actions run.

Rules for this codebase:

- No docstrings on Operator / Panel / UIList / PropertyGroup classes: Blender
  shows class docstrings as tooltips. Use `#` comments; tooltips come from
  `bl_description` and property `description`s.
- New Blender classes must be added to the module's `classes` tuple.
- Never store `PointerProperty`s to objects or meshes in the scan list: each one
  counts as a user, which broke *Make Copies* and *Remove Unused Meshes* during
  development. Store names (`properties._local` looks them up).
- Properties drawn with `layout.prop(s, "name")` are only referenced by string.

## How to run the tests

```
python tests/run.py                              # the suite, on instance_checker/
python tests/run.py --addon path/to/package_dir  # the same suite on another copy
python tests/check_versions.py                   # no Blender needed
python tools/build.py --check                    # build + reproducibility check
python tests/check_installed_package.py dist/instance_checker-1.0.0.zip
```

Expected: `RESULT: PASS (instance_checker)` with 64 `ok` lines. `tests/run.py`
starts Blender with `-b --factory-startup` and points every `BLENDER_USER_*`
folder and `HOME` at a temporary directory, so it never touches your
preferences, installed add-ons or a running Blender.

### Comparing behaviour with the previous version

```
git worktree add ../ic_old v1.0.0        # or any commit
python tests/compare_behaviour.py ../ic_old/instance_checker
git worktree remove ../ic_old
```

It first runs the current code twice (must give 0 differences: the output is
deterministic), then prints every difference between the two versions. For
commits before the rename, pass `../ic_old/copy_instancer`; the scripts take the
package name from the folder.

## How to make a release

1. Bump `version` in `instance_checker/blender_manifest.toml` (e.g. `1.0.1`).
2. Nothing to change in `README.md`: its badges read GitHub and the manifest.
3. Run the tests, commit, push to `main`, and wait for CI to pass on all three platforms.
4. Create an **annotated** tag; its message becomes the release notes:
   ```
   git tag -a v1.0.1 -m "Short title

   - change one
   - change two"
   git push origin v1.0.1
   ```
5. CI tests on Linux, Windows and macOS; then the release job checks the tag
   matches the manifest version, builds the zip and publishes the release with
   it. Re-running the job replaces the zip and notes instead of failing.

To support a newer Blender: change `blender_version_min` / `blender_version_max`
in the manifest, `VERSION`, `SERIES` and the three file names and SHA-256s in
`.github/scripts/get_blender.py` (from `blender-<version>.sha256` on
download.blender.org), the cache keys in `ci.yml`, the Windows path in
`tests/run.py` and the version named in the docs and the bug form.
`python tests/check_versions.py` lists anything you missed.

## Things to know

- **Copies are matched by vertex order.** Two meshes with the same shape but a
  different vertex order are not copies for this add-on.
- **`.corner_vert` / `.edge_verts` attributes** read in one `foreach_get` take
  about 0.01 ms for a 31k-vertex mesh, against 6 ms through `mesh.loops`.
  Meshes without faces or edges don't have them (`_int_attribute` returns an
  empty array).
- **Excluded collections are not evaluated**: `evaluated_get()` returns an object
  whose `is_evaluated` is False and whose `to_mesh()` has no modifiers, so a
  verification there compares nothing useful.
- **Blender 5.3 attribute names**: UV pin is `.pn.<uv>`, UV selection is
  `.uv_select_vert/edge/face`. `.vs.` / `.es.` (UV selection in Blender 4.x
  files) are still ignored, in case an old file carries them.
- **`read_factory_settings` keeps registered classes** but disables installed
  extensions; the tests register the add-on once and reset scenes with it.
- `matrix_world` is stale until `view_layer.update()`.
- The memory estimate sums attribute sizes; it ignores vertex groups and
  Blender's caches, so treat it as a comparison, not an exact number.
- Measured on an Apple Silicon Mac, Blender 5.3.0, 100 copies of a
  31,658-vertex mesh (median of 3): Scan 0.98 s (5.28 s with vertex groups,
  which are read vertex by vertex in Python), Instance All 0.25 s.
- `download.blender.org` sometimes refuses CI machines (HTTP 403); the download
  script falls back to official mirrors and checks the pinned SHA-256.
- CI uploads no artifacts: the account's artifact quota is shared with other
  repos. The release job rebuilds the zip; the build is reproducible.

## Known limits

- Copies with a different vertex order, mirrored copies and copies with
  non-uniform scale applied are not detected.
- Meshes with shape keys and library-linked objects are skipped.
- Applied-transform copies whose custom normals or other vector attributes were
  transformed too don't match: attributes are compared as they are.
- *Verify Result* accepts up to 10 × Tolerance of movement; a near-copy that is
  within tolerance changes shape by up to that much when instanced.
- The list doesn't notice changes until the next scan; objects renamed in
  between are reported, not followed.
- Tested on Blender 5.3.0 on macOS locally; Linux, Windows and macOS in CI.
