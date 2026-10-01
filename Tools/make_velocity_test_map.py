# Builds /Game/VelocityTest: physics cubes falling in front of the default camera, to exercise the velocity pass.
# Run it in a test project, for example:
#   UnrealEditor-Cmd.exe <Project>.uproject -run=pythonscript -script="<path>/make_velocity_test_map.py"
# then start the game on /Game/VelocityTest and check the LogArmASR lines (log LogArmASR Verbose).
import unreal

MAP = "/Game/VelocityTest"

level_editor = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

level_editor.new_level(MAP)

cube = unreal.load_asset("/Engine/BasicShapes/Cube")
material = unreal.load_asset("/Engine/BasicShapes/BasicShapeMaterial")

# Cubes at increasing heights keep falling through the view for several seconds (no floor).
for i in range(40):
    x = 1200.0 + (i % 5) * 150.0
    y = -400.0 + (i % 7) * 130.0
    z = 400.0 + i * 450.0
    actor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(x, y, z), unreal.Rotator(i * 13.0, i * 7.0, 0.0))
    mesh = actor.static_mesh_component
    mesh.set_mobility(unreal.ComponentMobility.MOVABLE)
    mesh.set_static_mesh(cube)
    mesh.set_material(0, material)
    mesh.set_simulate_physics(True)

actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 500), unreal.Rotator(-45.0, 30.0, 0.0))
actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 300), unreal.Rotator(0, 0, 0))
actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 0, 150), unreal.Rotator(0, 0, 0))

level_editor.save_current_level()
unreal.log("VelocityTest map saved")
