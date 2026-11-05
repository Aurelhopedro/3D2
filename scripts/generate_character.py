"""
Medieval Character Generator v2 — mhcore headless + Blender 4.2 LTS
=====================================================================

PIPELINE:
  1. mhcore gera mesh humano feminino/masculino real (sem GUI, sem Qt)
     OBJ passado via variável MHCORE_OBJ
  2. Blender importa o OBJ
  3. Materiais PBR de pele com subsurface scattering
  4. Vestuário medieval: armadura + manto + botas
  5. Olhos anatómicos realistas
  6. Cabelo em mechas NURBS
  7. Iluminação cinematográfica three-point
  8. Render WORKBENCH 1024×1024 (headless garantido)
  9. Export GLB + .blend + relatório JSON

Uso:
    blender -b --python scripts/generate_character.py -- --output /path/output
"""

import sys, os, json, math, time, argparse
import bpy, bmesh
from mathutils import Vector
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# 0. Argumentos
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument("--output", default=os.environ.get("MHCORE_OUTPUT", "/tmp/char_out"))
    return p.parse_args(argv)

ARGS   = parse_args()
OUTDIR = Path(ARGS.output)
OUTDIR.mkdir(parents=True, exist_ok=True)

report = {
    "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "steps": [], "errors": [], "warnings": [], "output_files": [],
}

def log(msg, level="INFO"):
    prefix = {"INFO": "✓", "WARN": "⚠", "ERROR": "✗"}.get(level, "·")
    print(f"[{prefix}] {msg}", flush=True)
    if level == "ERROR": report["errors"].append(msg)
    elif level == "WARN": report["warnings"].append(msg)

def step(name):
    log(f"── {name}")
    report["steps"].append(name)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def srgb2lin(c):
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92

def hex2rgba(h, a=1.0):
    h = h.lstrip("#")
    return (srgb2lin(int(h[0:2],16)/255),
            srgb2lin(int(h[2:4],16)/255),
            srgb2lin(int(h[4:6],16)/255), a)

def mat_pbr(name, base_hex, roughness=0.5, metallic=0.0,
            subsurface=0.0, specular=0.5):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nodes = m.node_tree.nodes
    links = m.node_tree.links
    nodes.clear()
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = hex2rgba(base_hex)
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
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return m

def set_active(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

def apply_mat(obj, mat):
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


# ─────────────────────────────────────────────────────────────────────────────
# 1. LIMPAR CENA
# ─────────────────────────────────────────────────────────────────────────────

step("Clean scene")
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.name = "MedievalCharacter"
log("Scene cleared")


# ─────────────────────────────────────────────────────────────────────────────
# 2. IMPORTAR OBJ DO MHCORE (ou fallback anatómico)
# ─────────────────────────────────────────────────────────────────────────────

step("Load human mesh")

obj_path = Path(os.environ.get("MHCORE_OBJ", ""))
human    = None

if obj_path.exists() and obj_path.suffix.lower() == ".obj":
    try:
        bpy.ops.wm.obj_import(filepath=str(obj_path))
        meshes = sorted(
            [(o, len(o.data.vertices)) for o in bpy.data.objects if o.type == "MESH"],
            key=lambda x: x[1], reverse=True,
        )
        if meshes:
            human = meshes[0][0]
            human.name = "MedievalHuman"
            log(f"mhcore OBJ importado: {len(human.data.vertices)} vértices")
            report["body_source"] = "mhcore_obj"
    except Exception as e:
        log(f"OBJ import falhou: {e}", "WARN")
        human = None

if human is None:
    # Fallback: mesh anatómico de alta qualidade programático
    log("Construindo mesh anatómico (fallback)")
    mesh_data = bpy.data.meshes.new("HumanMesh")
    human = bpy.data.objects.new("MedievalHuman", mesh_data)
    scene.collection.objects.link(human)

    bm = bmesh.new()

    def add_body_part(bm, cx, cy, bz, rx, ry, height, segs=24, smooth_top=False):
        """Cilindro oval anatómico com suavização opcional no topo."""
        rings = []
        for layer in range(5):
            t = layer / 4
            z = bz + height * t
            # Afinar ligeiramente no meio (cintura, tornozelos)
            taper = 1.0 - 0.08 * math.sin(t * math.pi)
            ring = []
            for s in range(segs):
                a = 2 * math.pi * s / segs
                x = cx + rx * taper * math.cos(a)
                y = cy + ry * taper * math.sin(a)
                ring.append(bm.verts.new((x, y, z)))
            rings.append(ring)
        for ri in range(len(rings) - 1):
            for s in range(segs):
                sn = (s + 1) % segs
                bm.faces.new([rings[ri][s], rings[ri][sn],
                              rings[ri+1][sn], rings[ri+1][s]])
        # Tampo inferior
        bc = bm.verts.new((cx, cy, bz))
        for s in range(segs):
            bm.faces.new([bc, rings[0][(s+1)%segs], rings[0][s]])
        # Tampo superior
        tc = bm.verts.new((cx, cy, bz + height))
        for s in range(segs):
            bm.faces.new([tc, rings[-1][s], rings[-1][(s+1)%segs]])

    # Proporções femininas em metros (altura total ~1.70m)
    # Pernas (separadas)
    add_body_part(bm, -0.088, 0, 0.000, 0.062, 0.058, 0.420, segs=20)
    add_body_part(bm,  0.088, 0, 0.000, 0.062, 0.058, 0.420, segs=20)
    # Tornozelos
    add_body_part(bm, -0.088, 0, 0.420, 0.040, 0.038, 0.060, segs=16)
    add_body_part(bm,  0.088, 0, 0.420, 0.040, 0.038, 0.060, segs=16)
    # Ancas / quadris (mais largas — feminino)
    add_body_part(bm, 0, 0, 0.480, 0.195, 0.145, 0.120, segs=28)
    # Cintura (mais estreita)
    add_body_part(bm, 0, 0, 0.600, 0.155, 0.118, 0.100, segs=28)
    # Torso / busto
    add_body_part(bm, 0, 0, 0.700, 0.185, 0.145, 0.230, segs=28)
    # Ombros
    add_body_part(bm, 0, 0, 0.930, 0.195, 0.148, 0.070, segs=28)
    # Pescoço
    add_body_part(bm, 0, 0, 1.000, 0.045, 0.042, 0.090, segs=16)
    # Cabeça (oval vertical)
    add_body_part(bm, 0, 0, 1.090, 0.098, 0.090, 0.195, segs=28, smooth_top=True)
    # Braços
    add_body_part(bm, -0.235, 0, 0.750, 0.048, 0.044, 0.420, segs=16)
    add_body_part(bm,  0.235, 0, 0.750, 0.048, 0.044, 0.420, segs=16)
    # Antebraços
    add_body_part(bm, -0.280, 0, 0.330, 0.038, 0.034, 0.380, segs=14)
    add_body_part(bm,  0.280, 0, 0.330, 0.038, 0.034, 0.380, segs=14)

    bm.to_mesh(mesh_data)
    bm.free()
    mesh_data.update()

    # Smooth shading
    for poly in mesh_data.polygons:
        poly.use_smooth = True
    mesh_data.update()

    log(f"Mesh anatómico: {len(mesh_data.vertices)} vértices")
    report["body_source"] = "programmatic_anatomical"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ESCALAR PARA 1.70m
# ─────────────────────────────────────────────────────────────────────────────

step("Scale to 1.70m")

set_active(human)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.context.view_layer.update()

vz = [v.co.z for v in human.data.vertices]
h0 = max(vz) - min(vz)
if h0 > 0:
    factor = 1.70 / h0
    human.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(scale=True)

bpy.context.view_layer.update()
vz2 = [v.co.z for v in human.data.vertices]
body_min_z = min(vz2)
body_max_z = max(vz2)
body_h = body_max_z - body_min_z

# Colocar base em Z=0
if abs(body_min_z) > 0.001:
    human.location.z = -body_min_z
    bpy.ops.object.transform_apply(location=True)
    bpy.context.view_layer.update()
    vz3 = [v.co.z for v in human.data.vertices]
    body_min_z = min(vz3)
    body_max_z = max(vz3)
    body_h = body_max_z - body_min_z

log(f"Altura final: {body_h:.3f}m")
report["height_m"] = round(body_h, 4)

# Referências anatómicas
head_cz    = body_min_z + body_h * 0.925
head_r     = body_h * 0.072
shoulder_z = body_min_z + body_h * 0.800
waist_z    = body_min_z + body_h * 0.570
bust_z     = body_min_z + body_h * 0.690
hip_z      = body_min_z + body_h * 0.520
ankle_z    = body_min_z + body_h * 0.065
face_y     = -head_r * 0.82


# ─────────────────────────────────────────────────────────────────────────────
# 4. MATERIAL DE PELE PBR
# ─────────────────────────────────────────────────────────────────────────────

step("Skin PBR material")

skin_mat = mat_pbr("Skin", "#C68642", roughness=0.50, metallic=0.0,
                   subsurface=0.22, specular=0.45)
apply_mat(human, skin_mat)
for poly in human.data.polygons:
    poly.use_smooth = True
human.data.update()
log("Material de pele aplicado")


# ─────────────────────────────────────────────────────────────────────────────
# 5. OLHOS ANATÓMICOS
# ─────────────────────────────────────────────────────────────────────────────

step("Build eyes")

sclera_r = head_r * 0.130
eye_sep  = head_r * 0.52
eye_z    = head_cz + head_r * 0.10
sclera_y = face_y - sclera_r * 0.40
iris_r   = sclera_r * 0.58
pupil_r  = sclera_r * 0.32

m_sc = mat_pbr("Sclera", "#F2EDE0", roughness=0.08, specular=0.6)
m_ir = mat_pbr("Iris",   "#4A3020", roughness=0.12, specular=0.5)
m_pu = mat_pbr("Pupil",  "#080505", roughness=0.04, specular=0.9)
m_rf = mat_pbr("Reflex", "#FFFFFF", roughness=0.0,  metallic=0.0)

for side, sx in [("L", eye_sep/2), ("R", -eye_sep/2)]:
    # Esclera
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32, ring_count=16, radius=sclera_r,
        location=(sx, sclera_y, eye_z))
    sc = bpy.context.active_object
    sc.name = f"Eye_Sclera_{side}"
    apply_mat(sc, m_sc)

    # Íris
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=48, radius=iris_r, depth=sclera_r*0.07,
        location=(sx, sclera_y - sclera_r*0.84, eye_z))
    ir = bpy.context.active_object
    ir.name = f"Eye_Iris_{side}"
    ir.rotation_euler = (math.pi/2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    apply_mat(ir, m_ir)

    # Pupila
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32, radius=pupil_r, depth=sclera_r*0.05,
        location=(sx, sclera_y - sclera_r*0.87, eye_z))
    pu = bpy.context.active_object
    pu.name = f"Eye_Pupil_{side}"
    pu.rotation_euler = (math.pi/2, 0, 0)
    bpy.ops.object.transform_apply(rotation=True)
    apply_mat(pu, m_pu)

    # Reflexo
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=8, ring_count=6, radius=sclera_r*0.065,
        location=(sx + iris_r*0.4, sclera_y - sclera_r*0.88, eye_z + iris_r*0.4))
    rf = bpy.context.active_object
    rf.name = f"Eye_Reflex_{side}"
    apply_mat(rf, m_rf)

log("Olhos construídos")


# ─────────────────────────────────────────────────────────────────────────────
# 6. CABELO — cap + mechas NURBS
# ─────────────────────────────────────────────────────────────────────────────

step("Build hair")

hair_mat = mat_pbr("Hair", "#2C1A0E", roughness=0.80, specular=0.3)
cap_r    = head_r * 1.04

# Calota
cap_mesh = bpy.data.meshes.new("HairCap_mesh")
cap_obj  = bpy.data.objects.new("HairCap", cap_mesh)
scene.collection.objects.link(cap_obj)

bm = bmesh.new()
SEGS = 32; RINGS = 12
pole = bm.verts.new((0, 0, head_cz + cap_r))
rings = []
for ri in range(1, RINGS + 1):
    phi = (math.pi * 0.55) * ri / RINGS
    z = head_cz + cap_r * math.cos(phi)
    r = cap_r * math.sin(phi)
    ring = []
    for s in range(SEGS):
        a = 2 * math.pi * s / SEGS
        ring.append(bm.verts.new((r*math.cos(a), r*math.sin(a), z)))
    rings.append(ring)
for s in range(SEGS):
    sn = (s+1) % SEGS
    bm.faces.new([pole, rings[0][s], rings[0][sn]])
for ri in range(len(rings)-1):
    for s in range(SEGS):
        sn = (s+1) % SEGS
        bm.faces.new([rings[ri][s], rings[ri][sn], rings[ri+1][sn], rings[ri+1][s]])
bm.normal_update()
bm.to_mesh(cap_mesh)
bm.free()
cap_mesh.update()
cap_obj.data.materials.append(hair_mat)

# Mechas
FRONT_PHI   = 3 * math.pi / 2
FRONT_RANGE = math.radians(70)
for i in range(32):
    az   = 2 * math.pi * i / 32
    diff = abs(az - FRONT_PHI) % (2*math.pi)
    diff = min(diff, 2*math.pi - diff)
    frontal = diff < FRONT_RANGE
    phi_b = math.pi * (0.28 if frontal else 0.14 + 0.16*(i%5)/4)
    lf    = 0.65 if frontal else 1.0
    bsw   = 0.5  if frontal else 0.0

    rx = cap_r * math.sin(phi_b) * math.cos(az)
    ry = cap_r * math.sin(phi_b) * math.sin(az)
    rz = head_cz + cap_r * math.cos(phi_b)
    tz = shoulder_z - head_r * lf * 0.8

    cd = bpy.data.curves.new(f"Str{i:02d}", "CURVE")
    cd.dimensions = "3D"; cd.bevel_depth = 0.005+0.003*(i%4)
    cd.bevel_resolution = 3; cd.use_fill_caps = True
    sp = cd.splines.new("NURBS"); sp.points.add(9)
    for pi in range(10):
        t = pi / 9
        sp.points[pi].co = (rx*(1+t*0.3), ry*(1+t*0.3)+bsw*cap_r*t*0.35, rz+(tz-rz)*t, 1.0)
    sp.use_endpoint_u = True; sp.order_u = min(4,10)
    so = bpy.data.objects.new(f"Str{i:02d}", cd)
    scene.collection.objects.link(so)
    so.data.materials.append(hair_mat)

log("Cabelo construído")


# ─────────────────────────────────────────────────────────────────────────────
# 7. VESTUÁRIO MEDIEVAL — armadura + manto
# ─────────────────────────────────────────────────────────────────────────────

step("Medieval armor & clothing")

steel_mat  = mat_pbr("Steel",   "#7A7A80", roughness=0.22, metallic=0.95, specular=0.8)
cloth_mat  = mat_pbr("Cloth",   "#3A2A1A", roughness=0.90, specular=0.08)
leather_mat= mat_pbr("Leather", "#2A1A0A", roughness=0.65, specular=0.3)

def armor_cylinder(name, cx, cy, bz, rx, ry, h, segs=24, mat=None):
    md = bpy.data.meshes.new(name+"_mesh")
    ob = bpy.data.objects.new(name, md)
    scene.collection.objects.link(ob)
    bm = bmesh.new()
    rings = []
    for layer in range(3):
        t = layer / 2
        z = bz + h * t
        ring = []
        for s in range(segs):
            a = 2*math.pi*s/segs
            ring.append(bm.verts.new((cx+rx*math.cos(a), cy+ry*math.sin(a), z)))
        rings.append(ring)
    for ri in range(len(rings)-1):
        for s in range(segs):
            sn = (s+1)%segs
            bm.faces.new([rings[ri][s], rings[ri][sn], rings[ri+1][sn], rings[ri+1][s]])
    bc = bm.verts.new((cx, cy, bz))
    for s in range(segs): bm.faces.new([bc, rings[0][(s+1)%segs], rings[0][s]])
    tc = bm.verts.new((cx, cy, bz+h))
    for s in range(segs): bm.faces.new([tc, rings[-1][s], rings[-1][(s+1)%segs]])
    bm.normal_update(); bm.to_mesh(md); bm.free(); md.update()
    for poly in ob.data.polygons: poly.use_smooth = True
    if mat: apply_mat(ob, mat)
    return ob

# Capacete
armor_cylinder("Helmet", 0, 0, head_cz - head_r*0.1, head_r*1.1, head_r*0.95, head_r*1.2, segs=28, mat=steel_mat)
# Couraça
armor_cylinder("Breastplate", 0, 0, waist_z, 0.21, 0.165, bust_z - waist_z + 0.05, segs=28, mat=steel_mat)
# Ombros
armor_cylinder("Pauldron_L", -0.265, 0, shoulder_z - 0.04, 0.085, 0.078, 0.14, segs=20, mat=steel_mat)
armor_cylinder("Pauldron_R",  0.265, 0, shoulder_z - 0.04, 0.085, 0.078, 0.14, segs=20, mat=steel_mat)
# Greaves (caneleiras)
armor_cylinder("Greave_L", -0.088, 0, ankle_z, 0.062, 0.058, waist_z*0.55, segs=20, mat=steel_mat)
armor_cylinder("Greave_R",  0.088, 0, ankle_z, 0.062, 0.058, waist_z*0.55, segs=20, mat=steel_mat)
# Luvas
armor_cylinder("Gauntlet_L", -0.280, 0, body_min_z, 0.040, 0.037, ankle_z*0.5, segs=16, mat=steel_mat)
armor_cylinder("Gauntlet_R",  0.280, 0, body_min_z, 0.040, 0.037, ankle_z*0.5, segs=16, mat=steel_mat)

# Saia / manto
SKIRT_SEGS = 48
sk_mesh = bpy.data.meshes.new("Skirt_mesh")
sk_obj  = bpy.data.objects.new("Skirt", sk_mesh)
scene.collection.objects.link(sk_obj)
bm = bmesh.new()
sk_z  = [waist_z, hip_z, hip_z-body_h*0.12, ankle_z+body_h*0.03, ankle_z]
sk_rx = [0.195, 0.230, 0.255, 0.248, 0.242]
sk_ry = [0.148, 0.172, 0.190, 0.185, 0.180]
sk_rings = []
for zi, z in enumerate(sk_z):
    ring = []
    for s in range(SKIRT_SEGS):
        a = 2*math.pi*s/SKIRT_SEGS
        fold = 1 + 0.03*math.sin(a*8)
        ring.append(bm.verts.new((sk_rx[zi]*math.cos(a)*fold, sk_ry[zi]*math.sin(a)*fold, z)))
    sk_rings.append(ring)
for ri in range(len(sk_rings)-1):
    for s in range(SKIRT_SEGS):
        sn=(s+1)%SKIRT_SEGS
        bm.faces.new([sk_rings[ri][s], sk_rings[ri][sn], sk_rings[ri+1][sn], sk_rings[ri+1][s]])
bm.normal_update(); bm.to_mesh(sk_mesh); bm.free(); sk_mesh.update()
for poly in sk_obj.data.polygons: poly.use_smooth = True
apply_mat(sk_obj, cloth_mat)

log("Armadura + vestuário construídos")


# ─────────────────────────────────────────────────────────────────────────────
# 8. ILUMINAÇÃO THREE-POINT
# ─────────────────────────────────────────────────────────────────────────────

step("Studio lighting")

bpy.ops.object.light_add(type='AREA', location=(2.0, -2.5, 1.5))
key = bpy.context.active_object
key.name = "KeyLight"
key.data.energy = 1200
key.data.size   = 2.0
key.data.color  = (1.0, 0.95, 0.85)
d = Vector((0, 0, body_h/2)) - Vector(key.location)
key.rotation_euler = d.to_track_quat("-Z","Y").to_euler()

bpy.ops.object.light_add(type='AREA', location=(-1.8, -1.8, 1.0))
fill = bpy.context.active_object
fill.name = "FillLight"
fill.data.energy = 500
fill.data.size   = 3.0
fill.data.color  = (0.85, 0.90, 1.0)
d = Vector((0, 0, body_h/2)) - Vector(fill.location)
fill.rotation_euler = d.to_track_quat("-Z","Y").to_euler()

bpy.ops.object.light_add(type='AREA', location=(0, 2.5, 1.8))
rim = bpy.context.active_object
rim.name = "RimLight"
rim.data.energy = 700
rim.data.size   = 1.5
rim.data.color  = (1.0, 0.98, 0.90)
d = Vector((0, 0, body_h*0.75)) - Vector(rim.location)
rim.rotation_euler = d.to_track_quat("-Z","Y").to_euler()

log("Iluminação three-point configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 9. CÂMARA
# ─────────────────────────────────────────────────────────────────────────────

step("Camera")

bpy.ops.object.camera_add(location=(0, -3.8, body_h*0.5))
cam = bpy.context.active_object
cam.name = "PresentationCamera"
cam.data.type = "PERSP"
cam.data.lens = 85
d = Vector((0, 0, body_h*0.5)) - Vector(cam.location)
cam.rotation_euler = d.to_track_quat("-Z","Y").to_euler()
scene.camera = cam
log("Câmara 85mm configurada")


# ─────────────────────────────────────────────────────────────────────────────
# 10. WORLD (céu escuro medieval)
# ─────────────────────────────────────────────────────────────────────────────

scene.world = bpy.data.worlds.new("World")
scene.world.use_nodes = True
wn = scene.world.node_tree.nodes
wl = scene.world.node_tree.links
wn.clear()
bg = wn.new("ShaderNodeBackground")
bg.inputs["Color"].default_value = (0.03, 0.04, 0.07, 1.0)
bg.inputs["Strength"].default_value = 0.25
wo = wn.new("ShaderNodeOutputWorld")
wl.new(bg.outputs["Background"], wo.inputs["Surface"])


# ─────────────────────────────────────────────────────────────────────────────
# 11. RENDER PREVIEW (WORKBENCH — headless garantido)
# ─────────────────────────────────────────────────────────────────────────────

step("Render preview")

scene.render.engine              = 'BLENDER_WORKBENCH'
scene.render.resolution_x        = 1024
scene.render.resolution_y        = 1024
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.display.shading.light      = 'STUDIO'
scene.display.shading.color_type = 'MATERIAL'
scene.display.shading.show_specular_highlight = True

preview_path = str(OUTDIR / "character_preview.png")
scene.render.filepath = preview_path

try:
    bpy.ops.render.render(write_still=True)
    if Path(preview_path).exists():
        log(f"Preview OK: {Path(preview_path).name}")
        report["output_files"].append("character_preview.png")
    else:
        log("Preview não encontrado após render", "WARN")
except Exception as e:
    log(f"Preview falhou (não crítico): {e}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 12. GUARDAR .BLEND
# ─────────────────────────────────────────────────────────────────────────────

step("Save .blend")

blend_path = str(OUTDIR / "character.blend")
try:
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    log(f"Blend gravado")
    report["output_files"].append("character.blend")
except Exception as e:
    log(f"Blend falhou: {e}", "WARN")


# ─────────────────────────────────────────────────────────────────────────────
# 13. EXPORTAR GLB
# ─────────────────────────────────────────────────────────────────────────────

step("Export GLB")

glb_path = str(OUTDIR / "character.glb")
try:
    bpy.ops.export_scene.gltf(
        filepath=glb_path,
        export_format='GLB',
        export_apply=True,
        export_materials='EXPORT',
        export_texcoords=True,
        export_normals=True,
        export_animations=False,
        export_skins=False,
        export_attributes=True,
        export_yup=True,
    )
except Exception as e:
    log(f"GLB export completo falhou: {e}", "WARN")
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format='GLB',
            export_apply=True,
        )
    except Exception as e2:
        log(f"GLB export minimal falhou: {e2}", "ERROR")
        sys.exit(1)

if Path(glb_path).exists():
    sz = Path(glb_path).stat().st_size / 1024
    log(f"GLB exportado: {sz:.1f} KB")
    report["output_files"].append("character.glb")
else:
    log("GLB não encontrado", "ERROR")
    sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# 14. RELATÓRIO
# ─────────────────────────────────────────────────────────────────────────────

step("Write report")

report["end_time"]        = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
report["success"]         = len(report["errors"]) == 0
report["blender_version"] = bpy.app.version_string
report["character_type"]  = "medieval_warrior"
report["body_source"]     = report.get("body_source", "unknown")

rp = str(OUTDIR / "character_report.json")
with open(rp, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)
log(f"Relatório escrito")
report["output_files"].append("character_report.json")

# ─── Sumário final ───────────────────────────────────────────────────────────
print("\n" + "="*60)
print("MEDIEVAL CHARACTER v2 — COMPLETO")
print("="*60)
for fn in report["output_files"]:
    fp = OUTDIR / fn
    sz = fp.stat().st_size if fp.exists() else 0
    print(f"  {fn:40s}  {sz/1024:.1f} KB")
print(f"\nPassos:    {len(report['steps'])}")
print(f"Erros:     {len(report['errors'])}")
print(f"Avisos:    {len(report['warnings'])}")
print(f"Fonte:     {report.get('body_source')}")
if report["errors"]:
    print("\nERROS:")
    for e in report["errors"]:
        print(f"  - {e}")
    sys.exit(1)
print("="*60)
