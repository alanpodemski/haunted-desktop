"""Build public/models/creature.glb from Mixamo FBX downloads.

Put the files in assets/mixamo/ (not committed):
    character.fbx   the character, With Skin (any pose)
    run.fbx crawl.fbx walk.fbx drag.fbx   gaits, Without Skin (In Place or not)
    idle.fbx scream.fbx                   Without Skin
    peek.fbx flee.fbx                     optional
Run:  blender -b -P blender/mixamo.py

Every animation is retargeted by bone name onto the character's armature (Mixamo rigs share names), renamed
to the file's stem, and exported as one glb with Draco. creature.json gets each clip's duration and, for the
gaits, the ground speed. A clip with root motion gets its speed from how far the hips travel and the travel is
then removed (the hips' linear drift is subtracted, the bob and sway stay). An in-place clip gets the speed at
which the planted (lowest) foot slides backwards under the body. Either way the runtime moves the root at that
speed and the feet do not skate.
"""
import json
import os
import statistics

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, 'assets', 'mixamo')
OUT = os.path.join(ROOT, 'public', 'models')
CLIPS = ['run', 'crawl', 'walk', 'drag', 'idle', 'scream', 'attack', 'peek', 'flee']
GAITS = {'run', 'crawl', 'walk', 'drag'}


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False, ignore_leaf_bones=True)
    return [o for o in bpy.data.objects if o not in before]


def armature_of(objs):
    return next(o for o in objs if o.type == 'ARMATURE')


def ground_speed(arm, action, fps):
    """median backward speed of the lowest foot, i.e. the one carrying the weight"""
    feet = [b for b in arm.pose.bones if b.name.lower().endswith(('leftfoot', 'rightfoot', 'lefttoebase', 'righttoebase'))]
    hands = [b for b in arm.pose.bones if b.name.lower().endswith(('lefthand', 'righthand'))]
    contacts = feet + hands      # a crawl plants hands too
    arm.animation_data.action = action
    f0, f1 = (int(round(v)) for v in action.frame_range)
    prev = None
    speeds = []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        pts = [(arm.matrix_world @ b.head) for b in contacts]
        low = min(range(len(pts)), key=lambda i: pts[i].z)
        if prev is not None and prev[0] == low:
            d = pts[low] - prev[1]
            speeds.append((d.x ** 2 + d.y ** 2) ** 0.5 * fps)
        prev = (low, pts[low])
    return statistics.median(speeds) if speeds else 0.0


def fcurves(action):
    """all F-curves of an action (Blender 5 layered actions, or the legacy list)"""
    if hasattr(action, 'layers'):
        return [fc for L in action.layers for st in L.strips for cb in st.channelbags for fc in cb.fcurves]
    return list(action.fcurves)


def hips_of(arm):
    return next(b for b in arm.pose.bones if b.name.lower().endswith('hips'))


def strip_root_motion(arm, action, fps):
    """metres per second the hips travel over the clip; removes that travel from the hips' location curves"""
    hips = hips_of(arm)
    arm.animation_data.action = action
    f0, f1 = (int(round(v)) for v in action.frame_range)
    sc = bpy.context.scene
    sc.frame_set(f0); a = (arm.matrix_world @ hips.head).copy()
    sc.frame_set(f1); b = (arm.matrix_world @ hips.head).copy()
    dist = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
    if dist < 0.05:
        return None
    path = f'pose.bones["{hips.name}"].location'
    for fc in fcurves(action):
        if fc.data_path != path:
            continue
        k = fc.keyframe_points
        v0, v1 = k[0].co.y, k[-1].co.y
        t0, t1 = k[0].co.x, k[-1].co.x
        for kp in k:
            u = (kp.co.x - t0) / (t1 - t0)
            d = (v1 - v0) * u
            kp.co.y -= d; kp.handle_left.y -= d; kp.handle_right.y -= d
        fc.update()
    return dist / ((f1 - f0) / fps)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    char_objs = import_fbx(os.path.join(SRC, 'character.fbx'))
    arm = armature_of(char_objs)
    arm.name = 'Creature'
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)       # the character file's own take

    fps = scene.render.fps / scene.render.fps_base
    meta = {}
    for name in CLIPS:
        path = os.path.join(SRC, f'{name}.fbx')
        if not os.path.exists(path):
            print(f'[mixamo] no {name}.fbx, skipping')
            continue
        objs = import_fbx(path)
        src_arm = armature_of(objs)
        action = src_arm.animation_data.action
        action.name = name
        action.use_fake_user = True
        for o in objs:
            bpy.data.objects.remove(o, do_unlink=True)
        if not arm.animation_data:
            arm.animation_data_create()
        f0, f1 = action.frame_range
        meta[name] = {'duration': (f1 - f0) / fps}
        if name in GAITS:
            v = strip_root_motion(arm, action, fps)
            meta[name]['speed'] = round(v if v is not None else ground_speed(arm, action, fps), 3)
            meta[name]['rootMotion'] = v is not None
        # one NLA track per clip so the glTF exporter writes each as its own animation
        track = arm.animation_data.nla_tracks.new()
        track.name = name
        track.strips.new(name, int(f0), action)
        track.mute = True
    arm.animation_data.action = None

    # materials: keep Mixamo's textures; name eye materials so the runtime can make them catch the light
    for o in char_objs:
        if o.type != 'MESH':
            continue
        for slot in o.material_slots:
            m = slot.material
            if m and 'eye' in m.name.lower() and not m.name.startswith('Eyes'):
                m.name = 'Eyes_' + m.name

    os.makedirs(OUT, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=os.path.join(OUT, 'creature.glb'), export_format='GLB',
        export_animations=True, export_animation_mode='NLA_TRACKS', export_skins=True,
        export_draco_mesh_compression_enable=True, export_image_format='JPEG',
        export_yup=True, export_apply=False,
    )
    json.dump(meta, open(os.path.join(OUT, 'creature.json'), 'w'), indent=2)
    print('[mixamo] wrote creature.glb', meta)


main()
