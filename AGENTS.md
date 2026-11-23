# AGENTS.md: Instance Checker

Blender 5.3 extension: finds mesh objects that are copies (same topology, same shape
up to rotation/uniform scale/move, same attributes), makes them share one mesh and
back, reports memory saved. Package `instance_checker/`, no dependencies beyond
Blender (numpy ships with it). Not a fork. Human docs: HANDOVER.md.

## Commands

```
python tests/run.py                                # suite: 64 checks, must all pass
python tests/run.py --addon PKG_DIR                # same suite on another copy (pkg name = folder name)
python tests/check_versions.py                     # supported-version consistency, no Blender
python tools/build.py --check                      # dist/instance_checker-<ver>.zip + digest + CRLF repro check
python tests/check_installed_package.py dist/instance_checker-*.zip   # install in scratch profile, use it
python tests/compare_behaviour.py OLD_PKG_DIR      # 72 cases, NEW twice then OLD vs NEW
```
Blender lookup: `--blender`, `$BLENDER`, `PATH`, `/Applications/Blender.app/Contents/MacOS/Blender`,
`C:\Program Files\Blender Foundation\Blender 5.3\blender.exe`.
All scripts run Blender with `-b --factory-startup` and temp `BLENDER_USER_*` + `HOME`.
Never test in the user's running Blender or real profile (also not through an MCP connection).

## Architecture

- `matching.py` (pure reads): `find_groups(objects, tol, allow_transform) -> ScanResult(groups, skipped)`.
  `topology_key` (counts + material slot count + sha1 of `.corner_vert`, `loop_total`, `.edge_verts`) buckets;
  `attribute_signature` (all attributes except position/topology/`.select*`/`.hide*`/`.uv_select*`/`.pn.`/`.vs.`/`.es.`),
  `vertex_group_signature`, `match_shape` (direct, else `similarity_transform` = Umeyama, reflections rejected)
  cluster. `Member.matrix` = ref-local → member-local. `mesh_bytes` = sum of attribute sizes + face offsets.
- `properties.py`: `scene.instance_checker` (`IC_Settings`), `groups` of `IC_Group` with `members` of `IC_Member`.
  Stored by NAME (`obj_name`, `mesh_name`, `reference_name`); `.obj/.mesh/.reference` are Python properties via `_local`.
- `operators.py`: `scan`, `store_result`, `instance_group(context, group, verify, tol, remove_orphans) -> (done, failed)`,
  `make_copies(objects) -> n`. Operators `instance_checker.scan / select_group / instance_group / instance_all /
  make_copies(target=SELECTED|GROUP) / report`; `index=-1` = active row.
- `ui.py`: `IC_PT_panel` (VIEW_3D › UI › "Instances"), `IC_UL_groups`.
- Manifest: `blender_version_min = "5.3.0"`, `blender_version_max = "5.4.0"`, id `instance_checker`, version 1.0.0.

## Rules and pitfalls

- No docstrings on bpy classes (tooltips); use `#` comments. Add new classes to `classes`.
- No ID `PointerProperty` in the scan list: it adds users (broke Make Copies "keep one original" and orphan removal).
- `obj.evaluated_get(dg).is_evaluated` is False for objects in excluded collections: their `to_mesh()` has no modifiers.
  Instancing with a transform change + modifiers + unevaluated is refused when verify is on.
- Verify tolerance = `max(10*tol, 1e-5*extent)` world units; Tolerance is capped at 0.01 (hard `max`).
- Read topology via `mesh.attributes[".corner_vert"/".edge_verts"].data.foreach_get("value")` (fast path, ~600x
  faster than `mesh.loops`); attribute missing when the mesh has no faces/edges.
- Blender 5.3 attribute types: no `SHORT2`; `FLOAT4` is 16 bytes; `FLOAT4X4` `value` has len 4 (rows) → 16 floats.
- `read_factory_settings` keeps registered classes, disables installed extensions.
- Print to console through `_print_safely` (cp1252 Windows consoles raised UnicodeEncodeError on mesh names).
- Installed module name is `bl_ext.user_default.instance_checker`; code never imports itself by name.
- LICENSE lives at the repo root only; `tools/build.py` copies it into the zip.

## Verification done for v1.0.0

- Baseline = first commit (as written, named copy_instancer): 45/45 original checks.
- Fixed, each with a regression check: FLOAT4 size (32 → 128 bytes), Tolerance cap (1.0 let a 0.5 change through
  verify), silent skip of renamed/deleted objects, unverifiable instancing in excluded collections, Print Report
  UnicodeEncodeError on cp1252. Final suite: 64/64 now; on the baseline exactly those 8 checks fail, 56 pass.
- `compare_behaviour.py`: NEW vs NEW 0 diffs; baseline vs NEW 0 diffs over 72 cases (246 groups, 239 applied-transform
  members, 34 runs with reverts). A deliberately broken verify gives 182 diffs (comparison is sensitive).
- Speed (median of 3, 100 × 31,658-vertex meshes, M-series Mac): Scan 2.05 → 0.98 s; with vertex groups 9.16 → 5.28 s;
  Instance All 0.27 → 0.25 s.
- Build reproducible: CRLF copy + other mtimes → same content digest; same zip hash across builds.
- Installed zip checked in a scratch profile (`check_installed_package.py`).

## Release checklist

1. Bump `version` in the manifest. 2. Tests pass; commit; push `main`; CI green on all 3 OS.
3. `git tag -a vX.Y.Z -m "notes"` (annotated; message = release notes); `git push origin vX.Y.Z`.
4. CI: test matrix → release job (fetch tag, tag == manifest version, build, `gh release create`, or upload --clobber
   + edit if it exists).

## Git

- `origin` = https://github.com/mttfntn/instance-checker-blender (public), branch `main` only. No CI step pushes.
- Commit author: Matteo Fontana <matteofontana@mttfntn.com>. Small commits; a bug fix goes before its test.
- `.gitignore` keeps out `dist/`, caches and local setup (`.mcp.json`, `.claude/`, editor folders).
