"""
refine.py - Fase 3: Refinamento Final do Personagem
=====================================================
Correcções desta versão:
  - Olhos: centro empurrado 70% do raio para fora da cabeça (orient.normalized)
  - T-shirt branca/cinza clara, calças azul navy, sapatos castanhos
  - Tom de pele quente medio africano (#8B5A2B)
  - Smooth shading + Subdivision Surface
  - Rig verificado / criado (20 ossos)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--input",  "-i", default="")
    p.add_argument("--output", "-o", default="/tmp/char_out")
    return p.parse_args(argv)


ARGS   = parse_args()
OUTDIR = Path(ARGS.output)
OUTDIR.mkdir(parents=True, exist_ok=True)

report: dict = {
    "phase": "refine",
    "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "blender": bpy.app.version_string,
    "success": False,
    "steps": [],
    "errors": [],
    "warnings": [],
    "output_files": [],
    "mat_assignments": [],
    "eye_method": "unknown",
}


def log(msg: str, level: str = "INFO") -> None:
    prefix = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗"}.get(level, "·")
    print(f"[{prefix}] {msg}", flush=True)
    if level == "ERROR":
        report["errors"].append(msg)
    elif level == "WARN":
        report["warnings"].append(msg)


def step(name: str) -> None:
    log(f"── {name}")
    report["steps"].append(name)


def save_report() -> None:
    report["end_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = OUTDIR / "refine_report.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    log(f"Relatorio escrito -> {path}")


# ── Materiais ────────────────────────────────────────────────────────────────

def srgb2lin(c: float) -> float:
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def hex2rgba(h: str, a: float = 1.0) -> tuple:
    h = h.lstrip("#")
    return (srgb2lin(int(h[0:2], 16) / 255),
            srgb2lin(int(h[2:4], 16) / 255),
            srgb2lin(int(h[4:6], 16) / 255), a)


def mat_pbr(name, base_hex, roughness=0.5, metallic=0.0,
            subsurface=0.0, specular=0.5, alpha=1.0):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = hex2rgba(base_hex, alpha)
    bsdf.inputs["Roughness"].default_value  = roughness
    bsdf.inputs["Metallic"].default_value   = metallic
    for sp in ("Specular IOR Level", "Specular"):
        if sp in bsdf.inputs:
            bsdf.inputs[sp].default_value = specular
            break
    if subsurface > 0:
        for ss in ("Subsurface Weight", "Subsurface"):
            if ss in bsdf.inputs:
                bsdf.inputs[ss].default_value = subsurface
                break
        for sc in ("Subsurface Radius",):
            if sc in bsdf.inputs:
                bsdf.inputs[sc].default_value = (1.0, 0.2, 0.1)
                break
    if alpha < 1.0:
        m.blend_method = "BLEND"
        for al in ("Alpha",):
            if al in bsdf.inputs:
                bsdf.inputs[al].default_value = alpha
                break
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m


def smooth_obj(obj, angle_deg=60.0):
    if obj.type != "MESH":
        return
    for poly in obj.data.polygons:
        poly.use_smooth = True
    obj.data.update()
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if not any(m.type == "SMOOTH_BY_ANGLE" for m in obj.modifiers):
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle_deg))
    except Exception:
        try:
            obj.data.use_auto_smooth = True
            obj.data.auto_smooth_angle = math.radians(angle_deg)
        except Exception:
            pass


def assign_mat(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def classify_obj(obj, body):
    n = obj.name.lower()
    if any(k in n for k in ("eye", "iris", "cornea", "sclera", "pupil")):
        return "eye"
    if any(k in n for k in ("teeth", "tooth", "gum")):
        return "teeth"
    if "tongue" in n:
        return "tongue"
    if any(k in n for k in ("hair", "brow", "lash", "haircard")):
        return "hair"
    if "nail" in n:
        return "nail"
    if any(k in n for k in (
        "cloth", "shirt", "top", "skirt", "pant", "belt",
        "dress", "boot", "shoe", "jacket", "coat",
        "trouser", "jeans", "sock", "glove",
        "proxy", "mhclo", "clothes",
    )):
        return "cloth"
    if obj != body:
        n_body = len(body.data.vertices)
        n_obj  = len(obj.data.vertices)
        ratio  = n_obj / max(n_body, 1)
        if 0.04 < ratio < 0.65:
            try:
                oc  = [body.matrix_world @ v.co for v in obj.data.vertices]
                bc  = [body.matrix_world @ v.co for v in body.data.vertices]
                omn = min(v.z for v in oc); omx = max(v.z for v in oc)
                bmn = min(v.z for v in bc); bmx = max(v.z for v in bc)
                mg  = (bmx - bmn) * 0.08
                if omn >= bmn - mg and omx <= bmx + mg:
                    return "cloth"
            except Exception:
                pass
    return "skin"


# ── Grupos de vértices para posição dos olhos ────────────────────────────────

def get_group_centroid(obj, group_name):
    if group_name not in obj.vertex_groups:
        return None
    gidx = obj.vertex_groups[group_name].index
    bpy.context.view_layer.update()
    dep   = bpy.context.evaluated_depsgraph_get()
    ev    = obj.evaluated_get(dep)
    emesh = ev.to_mesh()
    wm    = obj.matrix_world
    coords = []
    for v in obj.data.vertices:
        for g in v.groups:
            if g.group == gidx and g.weight > 0:
                idx = v.index
                co  = emesh.vertices[idx].co if idx < len(emesh.vertices) else v.co
                coords.append(wm @ co)
                break
    ev.to_mesh_clear()
    if not coords:
        return None
    return Vector((
        sum(c.x for c in coords) / len(coords),
        sum(c.y for c in coords) / len(coords),
        sum(c.z for c in coords) / len(coords),
    ))


def find_eye_centers(body, head_cz, head_r, face_y):
    cL = get_group_centroid(body, "helper-l-eye")
    cR = get_group_centroid(body, "helper-r-eye")
    if cL and cR:
        log(f"  Olhos via helper groups")
        report["eye_method"] = "helper_vertex_groups"
    else:
        cL = get_group_centroid(body, "joint-l-eye")
        cR = get_group_centroid(body, "joint-r-eye")
        if cL and cR:
            log(f"  Olhos via joint groups")
            report["eye_method"] = "joint_vertex_groups"
        else:
            eye_z = head_cz + head_r * 0.10
            sep   = head_r * 0.52
            sr    = head_r * 0.130
            ey    = face_y - sr * 0.30
            cL = Vector(( sep / 2, ey, eye_z))
            cR = Vector((-sep / 2, ey, eye_z))
            log("  Olhos via proporcao (fallback)", "WARN")
            report["eye_method"] = "proportional_fallback"

    tL = get_group_centroid(body, "joint-l-eye-target")
    tR = get_group_centroid(body, "joint-r-eye-target")
    oL = (tL - cL).normalized() if tL else Vector((0, -1, 0))
    oR = (tR - cR).normalized() if tR else Vector((0, -1, 0))
    return cL, cR, oL, oR


# ═════════════════════════════════════════════════════════════════════════════
# 1. CARREGAR BLEND
# ═════════════════════════════════════════════════════════════════════════════

step("Carregar blend")

input_path = Path(ARGS.input) if ARGS.input else None
if not input_path or not input_path.exists():
    for c in ["character.blend", "character.glb", "character.fbx", "character.obj"]:
        p = OUTDIR / c
        if p.exists():
            input_path = p
            break

if not input_path or not input_path.exists():
    log("Nenhum ficheiro de entrada encontrado", "ERROR")
    save_report(); sys.exit(1)

log(f"Entrada: {input_path} ({input_path.stat().st_size // 1024} KB)")
ext = input_path.suffix.lower()

if ext == ".blend":
    bpy.ops.wm.open_mainfile(filepath=str(input_path))
elif ext == ".glb":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(input_path))
elif ext == ".fbx":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(input_path),
                              automatic_bone_orientation=True,
                              ignore_leaf_bones=True)
elif ext == ".obj":
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.obj(filepath=str(input_path))
else:
    log(f"Formato nao suportado: {ext}", "ERROR")
    save_report(); sys.exit(1)

scene      = bpy.context.scene
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
all_arms   = [o for o in bpy.data.objects if o.type == "ARMATURE"]
log(f"Cena: {len(all_meshes)} meshes, {len(all_arms)} armaduras")

if not all_meshes:
    log("Nenhuma mesh encontrada", "ERROR")
    save_report(); sys.exit(1)

body = max(all_meshes, key=lambda o: len(o.data.vertices))
log(f"Corpo: '{body.name}' ({len(body.data.vertices)} vertices, {len(body.vertex_groups)} grupos)")

bpy.context.view_layer.update()
bw = [body.matrix_world @ v.co for v in body.data.vertices]
body_minz = min(v.z for v in bw)
body_maxz = max(v.z for v in bw)
body_h    = body_maxz - body_minz

head_cz    = body_minz + body_h * 0.930
head_r     = body_h * 0.068
shoulder_z = body_minz + body_h * 0.802
bust_z     = body_minz + body_h * 0.720
waist_z    = body_minz + body_h * 0.590
hip_z      = body_minz + body_h * 0.530
elbow_z    = body_minz + body_h * 0.620
wrist_z    = body_minz + body_h * 0.420
ankle_z    = body_minz + body_h * 0.058

hv = [body.matrix_world @ v.co for v in body.data.vertices
      if (body.matrix_world @ v.co).z > body_minz + body_h * 0.80]
face_y = min(v.y for v in hv) if hv else -(head_r * 0.80)

log(f"Altura: {body_h:.3f} m | face_y: {face_y:.4f}")
log(f"Grupos: {[vg.name for vg in body.vertex_groups[:12]]}")
report["body_height_m"] = round(body_h, 4)
report["loaded_meshes"] = len(all_meshes)
report["vertex_groups"] = [vg.name for vg in body.vertex_groups]


# ═════════════════════════════════════════════════════════════════════════════
# 2. SMOOTH SHADING
# ═════════════════════════════════════════════════════════════════════════════

step("Smooth shading")
for obj in all_meshes:
    smooth_obj(obj, 60.0)
log(f"Smooth: {len(all_meshes)} meshes")


# ═════════════════════════════════════════════════════════════════════════════
# 3. SUBDIVISION SURFACE
# ═════════════════════════════════════════════════════════════════════════════

step("Subdivision Surface")
SKIP_SUBDIV = ("hair", "belt", "card", "eye", "teeth", "tongue", "nail", "cornea")
for obj in all_meshes:
    if any(k in obj.name.lower() for k in SKIP_SUBDIV):
        continue
    if not any(m.type == "SUBSURF" for m in obj.modifiers):
        mod = obj.modifiers.new("Subdivision", "SUBSURF")
        mod.levels = 1; mod.render_levels = 2
        mod.subdivision_type = "CATMULL_CLARK"
log("Subdivision aplicada")


# ═════════════════════════════════════════════════════════════════════════════
# 4. PALETA DE MATERIAIS
# ═════════════════════════════════════════════════════════════════════════════

step("Paleta de materiais")
MATS = {
    # Pele castanha quente media
    "skin":       mat_pbr("Skin_Final",   "#8B5A2B", roughness=0.58, subsurface=0.20, specular=0.35),
    "face":       mat_pbr("Face_Final",   "#9B6535", roughness=0.55, subsurface=0.26, specular=0.38),
    # Roupa — cores BEM distintas entre si e da pele
    "tshirt":     mat_pbr("TShirt_Final", "#D0CFC8", roughness=0.94, specular=0.02),   # branco/cinza claro
    "pants":      mat_pbr("Pants_Final",  "#1E2D45", roughness=0.90, specular=0.03),   # azul navy
    "shoes":      mat_pbr("Shoes_Final",  "#3D1A0A", roughness=0.60, specular=0.30),   # castanho couro
    "cloth":      mat_pbr("Cloth_Final",  "#4A4A4A", roughness=0.92, specular=0.02),   # fallback cinza
    # Cabelo
    "hair":       mat_pbr("Hair_Final",   "#1E0E04", roughness=0.70, specular=0.30),
    # Olhos
    "eye_sclera": mat_pbr("Eye_Sclera",  "#F2EDE4", roughness=0.03, specular=0.90),
    "eye_iris":   mat_pbr("Eye_Iris",    "#3B2008", roughness=0.04, specular=0.85),
    "eye_pupil":  mat_pbr("Eye_Pupil",   "#060302", roughness=0.00, specular=0.98),
    "eye_cornea": mat_pbr("Eye_Cornea",  "#FFFFFF",  roughness=0.00, specular=1.0, alpha=0.05),
    # Outros
    "teeth":      mat_pbr("Teeth_Final", "#EDE8DC", roughness=0.20, specular=0.65),
    "nail":       mat_pbr("Nails_Final", "#C4846A", roughness=0.18, specular=0.70),
}
log(f"Paleta: {len(MATS)} materiais")


# ═════════════════════════════════════════════════════════════════════════════
# 5. REMOVER OLHOS EXISTENTES
# ═════════════════════════════════════════════════════════════════════════════

step("Remover olhos existentes")
EYE_KW    = ("eye", "sclera", "iris", "cornea", "pupil")
eye_names = [o.name for o in bpy.data.objects
             if o.type == "MESH" and any(k in o.name.lower() for k in EYE_KW)]
for name in eye_names:
    ref = bpy.data.objects.get(name)
    if ref:
        bpy.data.objects.remove(ref, do_unlink=True)
        log(f"  Removido: {name}")

# Reconstruir — evita ReferenceError em referencias invalidas
all_meshes = [o for o in bpy.data.objects if o.type == "MESH"]
log(f"Meshes apos remocao: {len(all_meshes)}")


# ═════════════════════════════════════════════════════════════════════════════
# 6. ATRIBUIR MATERIAIS
# ═════════════════════════════════════════════════════════════════════════════

step("Atribuir materiais")
cls_counts: dict = {}

# Ordenar por numero de vertices desc — corpo primeiro, roupa a seguir
sorted_meshes = sorted(all_meshes, key=lambda o: len(o.data.vertices), reverse=True)

for idx, obj in enumerate(sorted_meshes):
    cls    = classify_obj(obj, body)
    n_v    = len(obj.data.vertices)
    cls_counts[cls] = cls_counts.get(cls, 0) + 1

    if cls == "eye":
        assign_mat(obj, MATS["eye_sclera"])
    elif cls == "teeth":
        assign_mat(obj, MATS["teeth"])
    elif cls == "tongue":
        assign_mat(obj, MATS["skin"])
    elif cls == "hair":
        assign_mat(obj, MATS["hair"])
    elif cls == "nail":
        assign_mat(obj, MATS["nail"])
    elif cls == "cloth":
        try:
            vz = [obj.matrix_world @ v.co for v in obj.data.vertices]
            cz = sum(v.z for v in vz) / len(vz)
            mz = min(v.z for v in vz)
            if mz < body_minz + body_h * 0.08:
                sub_mat = MATS["shoes"];  mn = "shoes"
            elif cz > hip_z:
                sub_mat = MATS["tshirt"]; mn = "tshirt"
            else:
                sub_mat = MATS["pants"];  mn = "pants"
        except Exception:
            sub_mat = MATS["cloth"];  mn = "cloth"
        assign_mat(obj, sub_mat)
        log(f"  CLOTH '{obj.name}' ({n_v}v) -> {mn}")
        report["mat_assignments"].append({"obj": obj.name, "mat": mn})
        continue
    else:  # skin
        mat = MATS["face"] if obj == body else MATS["skin"]
        assign_mat(obj, mat)

    log(f"  {cls.upper():8s} '{obj.name}' ({n_v}v)")
    report["mat_assignments"].append({"obj": obj.name, "mat": cls})

log(f"Classificacoes: {cls_counts}")


# ═════════════════════════════════════════════════════════════════════════════
# 7. OLHOS ANATOMICOS
#    Centro calculado via grupos de vertices + offset para fora da cabeca
# ═════════════════════════════════════════════════════════════════════════════

step("Olhos anatomicos")

cL_j = get_group_centroid(body, "joint-l-eye")
cR_j = get_group_centroid(body, "joint-r-eye")
if cL_j and cR_j:
    sclera_r = (cR_j - cL_j).length * 0.30
    log(f"  Raio interocular: {sclera_r:.4f} m")
else:
    sclera_r = head_r * 0.130
    log(f"  Raio proporcional: {sclera_r:.4f} m")

iris_r  = sclera_r * 0.56
pupil_r = sclera_r * 0.28

cL, cR, oL, oR = find_eye_centers(body, head_cz, head_r, face_y)

for side, raw_center, orient in [("L", cL, oL), ("R", cR, oR)]:

    # CORRECÇÃO PRINCIPAL: empurrar centro 70% do raio para fora da cabeca
    # Os grupos de vertices ficam dentro da geometria —
    # este offset garante que a esclera fica visivel na superficie.
    eye_center = Vector(raw_center) + orient.normalized() * sclera_r * 0.70

    log(f"  Olho {side}: raw={[round(x,3) for x in raw_center]} "
        f"-> centro={[round(x,3) for x in eye_center]}")

    # Esclera (esfera branca)
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r,
        location=eye_center)
    sc = bpy.context.active_object
    sc.name = f"Eye_Sclera_{side}"
    assign_mat(sc, MATS["eye_sclera"])
    smooth_obj(sc, 60)

    # Iris (disco castanho)
    iris_pos = eye_center + orient.normalized() * sclera_r * 0.86
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=64, radius=iris_r, depth=sclera_r * 0.04,
        location=iris_pos)
    ir = bpy.context.active_object
    ir.name = f"Eye_Iris_{side}"
    if orient.length > 1e-6:
        ir.rotation_euler = orient.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(ir, MATS["eye_iris"])
    smooth_obj(ir, 60)

    # Pupila (disco preto)
    pupil_pos = eye_center + orient.normalized() * sclera_r * 0.88
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=pupil_r, depth=sclera_r * 0.02,
        location=pupil_pos)
    pu = bpy.context.active_object
    pu.name = f"Eye_Pupil_{side}"
    if orient.length > 1e-6:
        pu.rotation_euler = orient.to_track_quat("-Z", "Y").to_euler()
    bpy.ops.object.transform_apply(rotation=True)
    assign_mat(pu, MATS["eye_pupil"])

    # Cornea (esfera quasi-transparente, brilhante)
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=64, ring_count=32, radius=sclera_r * 1.02,
        location=eye_center)
    co = bpy.context.active_object
    co.name = f"Eye_Cornea_{side}"
    assign_mat(co, MATS["eye_cornea"])
    smooth_obj(co, 60)

log(f"Olhos criados via: {report['eye_method']}")


# ═════════════════════════════════════════════════════════════════════════════
# 8. RIG
# ═════════════════════════════════════════════════════════════════════════════

step("Verificar / criar rig")
all_arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]

if all_arms:
    arm = all_arms[0]
    nb  = len(arm.data.bones)
    log(f"Armadura existente: '{arm.name}' — {nb} ossos")
    report["rig_source"] = "imported"; report["rig_bones"] = nb
    if not any(m.type == "ARMATURE" for m in body.modifiers):
        mod = body.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    hb = arm.data.bones.get("Head") or arm.data.bones.get("head")
    if hb:
        for obj in bpy.data.objects:
            if obj.type == "MESH" and "hair" in obj.name.lower() and obj.parent != arm:
                obj.parent = arm; obj.parent_type = "BONE"; obj.parent_bone = hb.name
else:
    log("Sem armadura — a criar rig de 20 ossos")
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=True, location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = "Armature"; arm_obj.data.name = "Skeleton"
    eb = arm_obj.data.edit_bones
    for b in list(eb): eb.remove(b)
    BONES = [
        ("Hips",       (0,      0, hip_z),          (0,      0, waist_z),                None),
        ("Spine",      (0,      0, waist_z),         (0,      0, waist_z + 0.14),         "Hips"),
        ("Spine1",     (0,      0, waist_z + 0.14),  (0,      0, bust_z),                 "Spine"),
        ("Chest",      (0,      0, bust_z),           (0,      0, shoulder_z),             "Spine1"),
        ("Neck",       (0,      0, shoulder_z),       (0,      0, head_cz - head_r),       "Chest"),
        ("Head",       (0,      0, head_cz - head_r),(0,      0, head_cz + head_r * 1.1), "Neck"),
        ("UpperLeg_L", (-0.090, 0, hip_z),           (-0.090, 0, hip_z * 0.55),           "Hips"),
        ("LowerLeg_L", (-0.090, 0, hip_z * 0.55),   (-0.090, 0, ankle_z + 0.06),         "UpperLeg_L"),
        ("Foot_L",     (-0.090, 0, ankle_z + 0.06),  (-0.075, -0.08, ankle_z),            "LowerLeg_L"),
        ("UpperLeg_R", (0.090,  0, hip_z),           (0.090,  0, hip_z * 0.55),           "Hips"),
        ("LowerLeg_R", (0.090,  0, hip_z * 0.55),   (0.090,  0, ankle_z + 0.06),         "UpperLeg_R"),
        ("Foot_R",     (0.090,  0, ankle_z + 0.06),  (0.075,  -0.08, ankle_z),            "LowerLeg_R"),
        ("Shoulder_L", (-0.080, 0, shoulder_z),      (-0.180, 0, shoulder_z),             "Chest"),
        ("UpperArm_L", (-0.180, 0, shoulder_z),      (-0.260, 0, elbow_z),                "Shoulder_L"),
        ("LowerArm_L", (-0.260, 0, elbow_z),         (-0.280, 0, wrist_z),                "UpperArm_L"),
        ("Hand_L",     (-0.280, 0, wrist_z),         (-0.285, 0, wrist_z - 0.09),         "LowerArm_L"),
        ("Shoulder_R", (0.080,  0, shoulder_z),      (0.180,  0, shoulder_z),             "Chest"),
        ("UpperArm_R", (0.180,  0, shoulder_z),      (0.260,  0, elbow_z),                "Shoulder_R"),
        ("LowerArm_R", (0.260,  0, elbow_z),         (0.280,  0, wrist_z),                "UpperArm_R"),
        ("Hand_R",     (0.280,  0, wrist_z),         (0.285,  0, wrist_z - 0.09),         "LowerArm_R"),
    ]
    created = {}
    for bname, head, tail, parent in BONES:
        bone = eb.new(bname); bone.head = Vector(head); bone.tail = Vector(tail)
        if parent and parent in created: bone.parent = created[parent]
        created[bname] = bone
    bpy.ops.object.mode_set(mode="OBJECT")
    report["rig_source"] = "created"; report["rig_bones"] = len(BONES)
    log(f"Armadura criada: {len(BONES)} ossos")
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True); arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    try:
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        log("Pesos automaticos aplicados")
    except Exception as exc:
        log(f"Pesos automaticos: {exc}", "WARN")
        body.parent = arm_obj
        mod = body.modifiers.new("Armature", "ARMATURE"); mod.object = arm_obj


# ═════════════════════════════════════════════════════════════════════════════
# 9. ILUMINACAO
# ═════════════════════════════════════════════════════════════════════════════

step("Iluminacao")
for obj in list(bpy.data.objects):
    if obj.type == "LIGHT": bpy.data.objects.remove(obj, do_unlink=True)

center = Vector((0, 0, body_h * 0.55))

def add_light(name, loc, energy, size, color):
    bpy.ops.object.light_add(type="AREA", location=loc)
    lt = bpy.context.active_object
    lt.name = name; lt.data.energy = energy
    lt.data.size = size; lt.data.color = color
    lt.rotation_euler = (center - Vector(loc)).to_track_quat("-Z","Y").to_euler()

add_light("Key",  ( 2.2, -3.0,  1.8), 1600, 2.0, (1.00, 0.95, 0.88))
add_light("Fill", (-2.0, -1.5,  1.2),  700, 3.5, (0.86, 0.91, 1.00))
add_light("Rim",  ( 0.2,  3.0,  2.2),  900, 1.5, (1.00, 0.98, 0.94))
add_light("Top",  ( 0.0,  0.0,  3.5),  400, 4.0, (1.00, 1.00, 1.00))
log("Iluminacao four-point")


# ═════════════════════════════════════════════════════════════════════════════
# 10. CAMARA
# ═════════════════════════════════════════════════════════════════════════════

step("Camara")
for obj in list(bpy.data.objects):
    if obj.type == "CAMERA": bpy.data.objects.remove(obj, do_unlink=True)

bpy.ops.object.camera_add(location=(0, -3.8, body_h * 0.54))
cam = bpy.context.active_object
cam.name = "Camera_Final"; cam.data.type = "PERSP"; cam.data.lens = 85
cam.rotation_euler = (center - Vector(cam.location)).to_track_quat("-Z","Y").to_euler()
scene.camera = cam

world = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
scene.world = world; world.use_nodes = True
wn = world.node_tree.nodes; wl = world.node_tree.links; wn.clear()
bg = wn.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.03, 0.03, 0.05, 1.0)
bg.inputs["Strength"].default_value = 0.15
wo = wn.new("ShaderNodeOutputWorld")
wl.new(bg.outputs["Background"], wo.inputs["Surface"])


# ═════════════════════════════════════════════════════════════════════════════
# 11. RENDER
# ═════════════════════════════════════════════════════════════════════════════

step("Render")
scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x = 1024; scene.render.resolution_y = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.display.shading.light = "STUDIO"
scene.display.shading.color_type = "MATERIAL"
scene.display.shading.show_specular_highlight = True
scene.display.shading.show_shadows = True
for sl in ("paint.sl", "outdoor.sl", "rim.sl"):
    try: scene.display.shading.studio_light = sl; break
    except Exception: continue

preview_path = str(OUTDIR / "character_final_preview.png")
scene.render.filepath = preview_path
try:
    bpy.ops.render.render(write_still=True)
    if Path(preview_path).exists():
        log(f"Preview: {Path(preview_path).stat().st_size // 1024} KB")
        report["output_files"].append("character_final_preview.png")
except Exception as exc:
    log(f"Render falhou: {exc}", "WARN")


# ═════════════════════════════════════════════════════════════════════════════
# 12. BLEND FINAL
# ═════════════════════════════════════════════════════════════════════════════

step("Blend final")
blend_final = str(OUTDIR / "character_final.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_final)
    report["output_files"].append("character_final.blend")
    log(f"Blend -> {blend_final}")
except Exception as exc:
    log(f"Blend falhou: {exc}", "WARN")


# ═════════════════════════════════════════════════════════════════════════════
# 13. GLB FINAL
# ═════════════════════════════════════════════════════════════════════════════

step("Exportar GLB final")
glb_final = str(OUTDIR / "character_final.glb")
try:
    bpy.ops.export_scene.gltf(
        filepath=glb_final, export_format="GLB",
        export_apply=True, export_materials="EXPORT",
        export_texcoords=True, export_normals=True,
        export_skins=True, export_animations=False,
        export_morph=True, export_yup=True,
    )
    log("GLB exportado (completo)")
except TypeError:
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_final, export_format="GLB",
            export_apply=True, export_skins=True,
        )
        log("GLB exportado (minimo)")
    except Exception as exc2:
        log(f"GLB falhou: {exc2}", "ERROR"); save_report(); sys.exit(1)
except Exception as exc:
    log(f"GLB falhou: {exc}", "ERROR"); save_report(); sys.exit(1)

if Path(glb_final).exists():
    kb = Path(glb_final).stat().st_size // 1024
    log(f"GLB final: {kb} KB")
    report["output_files"].append("character_final.glb")
    report["glb_final_kb"] = kb
else:
    log("GLB final nao encontrado", "ERROR"); save_report(); sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
# 14. RELATORIO
# ═════════════════════════════════════════════════════════════════════════════

step("Relatorio")
tv = sum(len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH")
tm = len([o for o in bpy.data.objects if o.type == "MESH"])
report.update({
    "success": len(report["errors"]) == 0,
    "meshes": tm, "vertices": tv,
    "materials": len(bpy.data.materials),
    "rig_bones": report.get("rig_bones", 0),
})
report["output_files"].append("refine_report.json")
save_report()

print("\n" + "=" * 60)
print("REFINE - FASE 3 COMPLETA")
print("=" * 60)
print(f"  Blender  : {bpy.app.version_string}")
print(f"  Meshes   : {tm}  |  Vertices: {tv}")
print(f"  Rig      : {report.get('rig_bones',0)} ossos ({report.get('rig_source','?')})")
print(f"  Olhos    : {report.get('eye_method','?')}")
for fn in report["output_files"]:
    fp = OUTDIR / fn; sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:44s}  {sz // 1024} KB")
if report["errors"]:
    print(f"\n  ERROS: {report['errors']}"); sys.exit(1)
print("=" * 60)
print("-> Produto final: character_final.glb")
