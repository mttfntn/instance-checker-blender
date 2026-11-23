"""Find mesh objects that are copies of each other.

Two meshes are considered copies when they have
  * identical topology (same vertex order, edges, faces, corners),
  * the same shape within a tolerance, either directly or up to a
    rotation + uniform scale + translation ("applied transform" copies),
  * identical non-positional data (UVs, colors, creases, material indices,
    sharp flags, vertex-group weights...).

Nothing in here touches the scene; it only reads data and returns groups.
"""

import hashlib
from dataclasses import dataclass, field

import numpy as np

# --------------------------------------------------------------------------
# Low level array access
# --------------------------------------------------------------------------

_INT_TYPES = {"INT", "INT8", "INT32_2D", "INT16_2D"}
_BOOL_TYPES = {"BOOLEAN"}
_SKIP_TYPES = {"STRING"}

# Bytes per element, used for the memory estimate.
_TYPE_BYTES = {
    "FLOAT": 4, "INT": 4, "INT8": 1, "BOOLEAN": 1, "FLOAT2": 8,
    "FLOAT_VECTOR": 12, "FLOAT_COLOR": 16, "BYTE_COLOR": 4, "QUATERNION": 16,
    "INT32_2D": 8, "INT16_2D": 4, "FLOAT4": 16, "FLOAT4X4": 64, "STRING": 1,
}


def mesh_positions(mesh):
    co = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    return co.reshape(-1, 3).astype(np.float64)


def _attr_array(attr):
    """Return the attribute's data as a flat numpy array (or None to skip)."""
    if attr.data_type in _SKIP_TYPES:
        return None
    data = attr.data
    n = len(data)
    if n == 0:
        return np.zeros(0)
    first = data[0]
    # Every non-string type in Blender 5.3 exposes one of these three.
    key = next(k for k in ("vector", "color", "value") if hasattr(first, k))
    if attr.data_type == "FLOAT4X4":
        comp = 16
    else:
        v = getattr(first, key)
        try:
            comp = len(v)
        except TypeError:
            comp = 1
    if attr.data_type in _BOOL_TYPES:
        dtype = bool
    elif attr.data_type in _INT_TYPES:
        dtype = np.int32
    else:
        dtype = np.float32
    arr = np.empty(n * comp, dtype=dtype)
    data.foreach_get(key, arr)
    return arr


def _int_attribute(mesh, name, size):
    """Read an internal int attribute in one call (much faster than going
    through mesh.loops / mesh.edges). Meshes without faces or edges don't
    have the attribute at all: return an empty array then."""
    arr = np.empty(size, dtype=np.int32)
    attr = mesh.attributes.get(name)
    if attr is None:
        return arr[:0]
    attr.data.foreach_get("value", arr)
    return arr


def _topology_arrays(mesh):
    lv = _int_attribute(mesh, ".corner_vert", len(mesh.loops))
    lt = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", lt)
    ev = _int_attribute(mesh, ".edge_verts", len(mesh.edges) * 2)
    return lv, lt, ev


def topology_key(mesh):
    """Hashable key: equal keys <=> identical connectivity (same ordering)."""
    lv, lt, ev = _topology_arrays(mesh)
    h = hashlib.sha1()
    for a in (lv, lt, ev):
        h.update(a.tobytes())
        h.update(b"|")
    return (len(mesh.vertices), len(mesh.edges), len(mesh.polygons),
            len(mesh.loops), len(mesh.materials), h.hexdigest())


def _is_internal_topology_attr(name):
    return name in {"position", ".edge_verts", ".corner_vert", ".corner_edge"}


def attribute_signature(mesh):
    """Dict name -> (domain, type, array) of every non-topology attribute.

    Editor-only state such as selection/hide flags is ignored.
    """
    sig = {}
    for attr in mesh.attributes:
        name = attr.name
        if _is_internal_topology_attr(name):
            continue
        if name.startswith((".select", ".hide", ".uv_select")):
            continue
        # UV pin (.pn.<uv>) and UV selection saved by Blender 4.x (.vs./.es.<uv>)
        if name.startswith((".pn.", ".vs.", ".es.")):
            continue
        arr = _attr_array(attr)
        if arr is None:
            continue
        sig[name] = (attr.domain, attr.data_type, arr)
    return sig


def vertex_group_signature(mesh):
    """Hash of the per-vertex group weights stored on the mesh (index based).

    Weights are rounded to 5 decimals. Returns "" when no vertex has a weight.
    """
    rows = [(v.index, g.group, round(g.weight, 5))
            for v in mesh.vertices for g in v.groups]
    if not rows:
        return ""
    ids = np.array([r[:2] for r in rows], dtype=np.int32)
    weights = np.array([r[2] for r in rows], dtype=np.float32)
    h = hashlib.sha1(ids.tobytes())
    h.update(weights.tobytes())
    return h.hexdigest()


def mesh_bytes(mesh):
    """Rough in-memory size of a mesh's geometry data, in bytes."""
    total = 4 * (len(mesh.polygons) + 1)  # face offsets
    for attr in mesh.attributes:
        total += len(attr.data) * _TYPE_BYTES.get(attr.data_type, 4)
    return total


def _attrs_equal(a, b, tol):
    if a.keys() != b.keys():
        return False
    for name, (dom_a, type_a, arr_a) in a.items():
        dom_b, type_b, arr_b = b[name]
        if dom_a != dom_b or type_a != type_b or arr_a.shape != arr_b.shape:
            return False
        if arr_a.dtype.kind == "f":
            if arr_a.size and np.max(np.abs(arr_a - arr_b)) > tol:
                return False
        elif not np.array_equal(arr_a, arr_b):
            return False
    return True


# --------------------------------------------------------------------------
# Shape matching
# --------------------------------------------------------------------------

def similarity_transform(src, dst):
    """Least-squares s, R, t with dst ~= s * R @ src + t (Umeyama 1991).

    Returns a 4x4 numpy matrix or None. Reflections are excluded.
    """
    n = len(src)
    if n < 3:
        return None
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    xs = src - mu_s
    xd = dst - mu_d
    var_s = (xs * xs).sum() / n
    if var_s < 1e-20:
        return None
    cov = xd.T @ xs / n
    U, S, Vt = np.linalg.svd(cov)
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1.0
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / var_s
    if s <= 1e-12:
        return None
    t = mu_d - s * R @ mu_s
    M = np.eye(4)
    M[:3, :3] = s * R
    M[:3, 3] = t
    return M


def _effective_tol(co, tol):
    if len(co) == 0:
        return tol
    extent = float(np.max(np.abs(co)))
    # float32 coordinates can't be more precise than ~1e-6 relative
    return max(tol, extent * 2e-6)


def match_shape(ref_co, co, tol, allow_transform):
    """Return a 4x4 matrix T (ref-local -> member-local) or None if no match.

    T is the identity for plain copies.
    """
    etol = _effective_tol(co, tol)
    if ref_co.shape != co.shape:
        return None
    if len(co) == 0 or np.max(np.abs(ref_co - co)) <= etol:
        return np.eye(4)
    if not allow_transform:
        return None
    M = similarity_transform(ref_co, co)
    if M is None:
        return None
    mapped = ref_co @ M[:3, :3].T + M[:3, 3]
    if np.max(np.abs(mapped - co)) > etol:
        return None
    return M


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

@dataclass
class MeshInfo:
    mesh: object
    co: np.ndarray
    attrs: dict
    vgroups: str
    objects: list = field(default_factory=list)


@dataclass
class Member:
    obj: object
    mesh: object
    matrix: np.ndarray  # ref-local -> member-local (identity for plain copies)

    @property
    def needs_transform(self):
        return not np.allclose(self.matrix, np.eye(4), atol=1e-7)


@dataclass
class Group:
    reference: object  # bpy.types.Mesh
    members: list      # list[Member]

    @property
    def unique_meshes(self):
        return len({m.mesh.as_pointer() for m in self.members})

    @property
    def status(self):
        if self.unique_meshes == 1:
            return "INSTANCED"
        if self.unique_meshes < len(self.members):
            return "PARTIAL"
        return "COPIES"


@dataclass
class ScanResult:
    groups: list
    skipped: list  # (object, reason)


def _eligible(obj):
    if obj.type != "MESH" or obj.data is None:
        return "not a mesh"
    if obj.library is not None or obj.override_library is not None:
        return "linked from library"
    if obj.data.shape_keys is not None:
        return "has shape keys"
    if len(obj.data.vertices) == 0:
        return "empty mesh"
    return None


def find_groups(objects, tol=1e-4, allow_transform=True):
    """Group objects whose meshes are copies of each other."""
    skipped = []
    meshes = {}  # mesh pointer -> list of objects
    for obj in objects:
        reason = _eligible(obj)
        if reason:
            if obj.type == "MESH" and reason != "empty mesh":
                skipped.append((obj, reason))
            continue
        meshes.setdefault(obj.data.as_pointer(), []).append(obj)

    # Bucket by topology
    buckets = {}
    for objs in meshes.values():
        mesh = objs[0].data
        buckets.setdefault(topology_key(mesh), []).append(objs)

    groups = []
    for bucket in buckets.values():
        if len(bucket) == 1 and len(bucket[0]) == 1:
            continue
        infos = []
        for objs in bucket:
            mesh = objs[0].data
            infos.append(MeshInfo(
                mesh=mesh,
                co=mesh_positions(mesh),
                attrs=attribute_signature(mesh),
                vgroups=vertex_group_signature(mesh)
                if any(o.vertex_groups for o in objs) else "",
                objects=objs,
            ))
        # Prefer the most-used mesh (then by name) as cluster reference
        infos.sort(key=lambda i: (-i.mesh.users, i.mesh.name))

        clusters = []  # list of (ref_info, [(info, matrix)])
        for info in infos:
            for ref, entries in clusters:
                if info.vgroups != ref.vgroups:
                    continue
                if not _attrs_equal(ref.attrs, info.attrs, tol):
                    continue
                M = match_shape(ref.co, info.co, tol, allow_transform)
                if M is not None:
                    entries.append((info, M))
                    break
            else:
                clusters.append((info, [(info, np.eye(4))]))

        for ref, entries in clusters:
            members = [Member(obj=o, mesh=info.mesh, matrix=M)
                       for info, M in entries for o in info.objects]
            if len(members) < 2:
                continue
            members.sort(key=lambda m: m.obj.name)
            groups.append(Group(reference=ref.mesh, members=members))

    groups.sort(key=lambda g: (-(g.unique_meshes - 1) * mesh_bytes(g.reference),
                               g.reference.name))
    return ScanResult(groups=groups, skipped=skipped)


def group_savings(group):
    """Bytes freed by making every member share the reference mesh."""
    return (group.unique_meshes - 1) * mesh_bytes(group.reference)


def format_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= 1024.0
