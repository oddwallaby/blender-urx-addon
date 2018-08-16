# Blender URx Addon

Control Universal Robots robots from within Blender.

## To Use

1. Load **scenes/UR5_Start_Scene.blend** in Blender. It contains a model of the UR5 robot that is rigged and set up with joint constraints matching the real machine.
2. Move the object named "IK Target" to position the robot. It is set as the target for the robot rigging's inverse kinematics. It is possible to move the joints of the robot individually if inverse kinematics is disabled.
3. Animate the target (and consequently the robot). Watch the animation and triple check that there are no unexpected glitches (which could cause the robot to move in an unexpected manner).
4. Run the Blender operator "Export to Universal Robots arm". Select whether the animation should be looped (warning! If the start and end positions differ the robot may try to move very rapidly between them). Hitting "OK" will cause the robot to start moving!

