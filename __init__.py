#!/usr/bin/env python3

import os
import math
import json
import bpy
import gc
import logging
import socket
import re

# Support reloading
if 'ur_script' in locals():
  import importlib
  ur_script = importlib.reload(ur_script)
else:
  from . import ur_script

bl_info = {
  'name': 'Binder',
  'author': 'Owen Trueblood',
  'version': (0, 0, 1),
  'blender': (2, 77, 0),
  'location': '',
  'description': 'Connects Blender to a Universal Robots arm',
  'category': 'System',
  'support': 'COMMUNITY',
}

logging.basicConfig(filename='/tmp/binder.log')
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

default_configuration = {
  'robot': {
    'script_port': 30002, # Accepts script strings for execution
    'host': None, # IP address of the robot
  }
}

# Configuration is stored in a JSON formatted file in a Blender user resource directory
def get_configuration_path():
  return os.path.join(bpy.utils.user_resource(resource_type='CONFIG', create=True), 'binder-config.json')

def load_configuration():
  config_path = get_configuration_path()

  if not os.path.isfile(config_path):
    save_configuration(default_configuration)
    return default_configuration

  with open(config_path, 'r') as config_file:
    return json.loads(config_file.read())

def save_configuration(config):
  config_path = get_configuration_path()

  with open(config_path, 'w') as config_file:
    config_file.write(json.dumps(config, indent=2))

class Robot(object):
  def __init__(self, host, port):
    self.host = host
    self.port = port

    self.sock = None

  def connect(self):
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    self.sock.connect((self.host, self.port))

  def send(self, data):
    # Create a connection if one does not already exist
    if self.sock == None:
      self.connect()

    self.sock.send(bytes(data, encoding='utf8'))

  def send_script(self, script_text):
    # Clean the script formatting
    script_lines = map(lambda line: line.rstrip(), script_text.split())
    clean_script = '\n'.join(script_lines) + '\n'

    self.send(clean_script)

class ExportUR5AnimationOperator(bpy.types.Operator):
  """Exports animation to UR Script"""
  bl_idname = 'ur5.export'
  bl_label = 'Export to UR5'
  bl_options = { 'REGISTER' }

  loop = bpy.props.BoolProperty(name="Loop Animation", default=False)

  def invoke(self, context, event):
    self.config = load_configuration()

    # Pop up the window with our operators options before executing
    return context.window_manager.invoke_props_dialog(self, width=500)

  def execute(self, context):
    scene = context.scene
    output_type = 'urscript'

    armature_obj = bpy.data.objects['Armature']
    bpy.context.scene.objects.active = armature_obj

    bpy.ops.object.mode_set(mode='POSE')

    joint_names = ['Base', 'Shoulder', 'Elbow', 'Wrist1', 'Wrist2', 'Wrist3']
    axis_index = {
      'Base': 2,
      'Shoulder': 1,
      'Elbow': 1,
      'Wrist1': 1,
      'Wrist2': 2,
      'Wrist3': 1,
    }
    
    # (multiplier, offset)
    axis_correction = {
      'Base': (1, 0),
      'Shoulder': (-1, -math.pi/2),
      'Elbow': (-1, 0),
      'Wrist1': (-1, -math.pi/2),
      'Wrist2': (-1, 0),
      'Wrist3': (-1, 0),
    }

    start_frame_index = scene.frame_current

    frame_angles = []
    
    for frame_index in range(scene.frame_start, scene.frame_end):
      scene.frame_set(frame_index)

      joint_angles_by_name = {}
      for pose_bone in armature_obj.pose.bones:
        joint_angles_by_name[pose_bone.name] = self.get_local_orientation(pose_bone)

      angles = []
      for name in joint_names:
        bl_angle = joint_angles_by_name[name][axis_index[name]]
        direction, offset = axis_correction[name]
        robot_angle = direction * bl_angle + offset

        angles.append(robot_angle)

      frame_angles.append(angles)

    if output_type == 'json':
      with open('/tmp/export.json', 'w') as export_file:
        export_file.write(json.dumps(frame_angles))
    elif output_type == 'urscript':
      time_for_control = 1.0 / scene.render.fps # Seconds

      script = ur_script.URScript()
      script.function('blender_move')
      script.movej(frame_angles[0])

      if self.loop:
        script.while_loop('True')

      for angles in frame_angles:
        script.servoj(angles, time_for_control)
      
      if self.loop:
        # End for the while loop
        script.end()

      # End for the move function
      script.end()

    # Set the current frame back to what it was originally
    scene.frame_set(start_frame_index)

    config = load_configuration()
    robot = Robot(config['robot']['host'], config['robot']['script_port'])

    log.info('Setup robot at {}:{}'.format(robot.host, robot.port))

    if output_type == 'urscript':
      # FIXME: put this in a proper log directory
      with open('/tmp/export.urscript', 'w') as script_file:
        script_file.write(script.text)

      robot.send_script(script.text)
      log.info('Sent script to robot')

    return {'FINISHED'}

  def get_local_orientation(self, pose_bone):
    local_orientation = pose_bone.matrix_channel.to_euler()

    if pose_bone.parent is None:
      return (local_orientation.x, local_orientation.y, local_orientation.z)
    else:
      # Calculate the local orientation of the bone
      my_orientation = pose_bone.matrix_channel.copy()
      parent_orientation = pose_bone.parent.matrix_channel.copy()

      my_orientation.invert()
      orientation = (my_orientation * parent_orientation).to_euler()

      return (orientation.x, orientation.y, orientation.z)

def register():
  bpy.utils.register_class(ExportUR5AnimationOperator)
  log.info('registered add-on')

def unregister():
  bpy.utils.unregister_class(ExportUR5AnimationOperator)
  log.info('unregistered add-on')

if __name__ == '__main__':
  register()
