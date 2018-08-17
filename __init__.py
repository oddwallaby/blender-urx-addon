#!/usr/bin/env python3

import os
import math
import json
import bpy
import gc
import logging
import socket
import re
import ipaddress

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

# Keymaps are stored here to track for unregistering
addon_keymaps = []

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

    self.sock.sendall(bytes(data, encoding='utf8'))

  def movej(self, angles):
    script = ur_script.URScript()
    script.function('blender_move')
    script.movej(angles)
    script.end()

    self.send(script.text)

def get_local_orientation(pose_bone):
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

def pose_to_ur_joint_angles(bones):
  joint_names = ['Base', 'Shoulder', 'Elbow', 'Wrist1', 'Wrist2', 'Wrist3']

  # Pick which axis is revolute for each joint
  axis_index = {
    'Base': 2,
    'Shoulder': 1,
    'Elbow': 1,
    'Wrist1': 1,
    'Wrist2': 2,
    'Wrist3': 1,
  }
  
  # Match direction and start angle for arm
  # (multiplier, offset)
  axis_correction = {
    'Base': (1, 0),
    'Shoulder': (-1, -math.pi/2),
    'Elbow': (-1, 0),
    'Wrist1': (-1, -math.pi/2),
    'Wrist2': (-1, 0),
    'Wrist3': (-1, 0),
  }

  joint_angles_by_name = {}
  for bone in bones:
    joint_angles_by_name[bone.name] = get_local_orientation(bone)

  joint_angles = []
  for name in joint_names:
    bl_angle = joint_angles_by_name[name][axis_index[name]]
    direction, offset = axis_correction[name]
    joint_angle = direction * bl_angle + offset

    joint_angles.append(joint_angle)

  return joint_angles

def fix_overrotation(fps, current_angle, last_angle):
  def under_speedlimit(current_speed):
    robot_speed_limit = math.radians(191) # radians / second
    speed_limit = robot_speed_limit * 1.02
    return current_speed < speed_limit

  if last_angle == None:
      # FIXME: ideally the first last_angle would be the starting angle for this joint on the robot
      return current_angle

  log.info('{} {} {}'.format(fps, current_angle, last_angle))

  current_speed = math.fabs(current_angle - last_angle) * fps

  if not under_speedlimit(current_speed):
    log.info('Speed limit violated')

    if last_angle < 0 and current_angle > 0:
      # Crossed from negative to positive
      return -2 * math.pi + current_angle
    elif last_angle > 0 and current_angle < 0:
      return 2 * math.pi + current_angle
    else:
      # We are going too fast and it is not because of over-rotation
      # This is a bad animation
      raise Exception('Over speed limit')

  return current_angle

def is_valid_ip(address):
  try:
    ipaddress.ip_address(address)
    return True
  except ValueError:
    return False

def get_robot_ip(self):
  config = load_configuration()
  return config['robot']['host']

def set_robot_ip(self, ip):
  if not is_valid_ip(ip):
    self.error = 'Invalid IP address'
    return

  config = load_configuration()

  if config['robot']['host'] != ip:
    config['robot']['host'] = ip
    save_configuration(config)

class URxExportAnimationOperator(bpy.types.Operator):
  """Exports animation to UR Script and sends to robot arm"""
  bl_idname = 'urx.export'
  bl_label = 'Export to Universal Robots arm'
  bl_options = { 'REGISTER' }

  loop = bpy.props.BoolProperty(name="Loop Animation", default=False)
  robot_ip_address = bpy.props.StringProperty(name="Robot IP Address", get=get_robot_ip, set=set_robot_ip)

  def invoke(self, context, event):
    # Pop up the window with our operators options before executing
    return context.window_manager.invoke_props_dialog(self, width=500)

  def execute(self, context):
    # Check if an error was set in a getter/setter
    if hasattr(self, 'error'):
      self.report({'ERROR'}, self.error)
      return {'CANCELLED'}

    scene = context.scene

    output_type = 'urscript'

    armature_obj = bpy.data.objects['Armature']
    #bpy.context.scene.objects.active = armature_obj

    #bpy.ops.object.mode_set(mode='POSE')

    start_frame_index = scene.frame_current

    last_joint_angles = [None] * 6
    frame_angles = []
    for frame_index in range(scene.frame_start, scene.frame_end):
      scene.frame_set(frame_index)
      joint_angles = pose_to_ur_joint_angles(armature_obj.pose.bones)

      # Fix overrotation
      for i, current_angle in enumerate(joint_angles):
        if i == 0:
          last_angle = last_joint_angles[i]
          joint_angles[i] = fix_overrotation(scene.render.fps, current_angle, last_angle)

      frame_angles.append(joint_angles)
      last_joint_angles = joint_angles

    log.info('Sending {} angles'.format(len(frame_angles)))

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

      script.set_tool_digital_out(0, False)

      for frame_index, angles in enumerate(frame_angles):
        if frame_index == 150:
          script.set_tool_digital_out(0, True)

        script.servoj(angles, time_for_control)

      script.set_tool_digital_out(0, False)
      
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

      robot.send(script.text)
      log.info('Sent script to robot')

    return {'FINISHED'}

class URxMoveToPoseOperator(bpy.types.Operator):
  """Moves robot arm to current pose"""
  bl_idname = 'urx.moveto'
  bl_label = 'URx Move to Pose'
  bl_options = { 'REGISTER' }

  def invoke(self, context, event):
    self.config = load_configuration()
    return self.execute(context)

  def execute(self, context):
    armature_obj = bpy.data.objects['Armature']
    #bpy.context.scene.objects.active = armature_obj
    bpy.ops.object.mode_set(mode='POSE')

    robot = Robot(self.config['robot']['host'], self.config['robot']['script_port'])
    robot.movej(pose_to_ur_joint_angles(armature_obj.pose.bones))

    log.info('Moved robot to pose')

    return {'FINISHED'}

def get_centroid(points):
  if len(points) == 0:
    return None

  x_total, y_total, z_total = points[0]

  for point in points[1:]:
    x, y, z = point

    x_total += x
    y_total += y
    z_total += z

  l = len(points)

  return (x_total / l, y_total / l, z_total / l)

# Adapted from https://blender.stackexchange.com/a/689
def get_spline_points(spline):
  points = []

  if len(spline.bezier_points) >= 2:
    resolution = spline.resolution_u + 1
    segments = len(spline.bezier_points)

    if not spline.use_cyclic_u:
      segments -= 1

    for i in range(segments):
      inext = (i + 1) % len(spline.bezier_points)

      knot1 = spline.bezier_points[i].co
      handle1 = spline.bezier_points[i].handle_right
      handle2 = spline.bezier_points[inext].handle_left
      knot2 = spline.bezier_points[inext].co

      curve_points = bpy.mathutils.geometry.interpolate_bezier(knot1, handle1, handle2, knot2, resolution)
      points.extend(curve_points)

  return points

def points_from_curve(obj_path):
  bpy.data.objects[obj_path.name].select = True
  bpy.ops.object.convert(target='MESH', keep_original=True)
  new_obj = bpy.context.object
  points = list(map(lambda p: (p.co.x, p.co.y, p.co.z), new_obj.data.vertices))
  bpy.context.scene.objects.unlink(new_obj)
  return points

def distance(a, b):
  x0, y0, z0 = a
  x1, y1, z1 = b
  return math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)

def group_contiguous_segments(segments):
  if len(segments) <= 1:
    return segments

  # If a point is less than this far away from another point then it might as well be the same point
  def close_enough(a, b):
    return distance(a, b) < 0.01

  polylines = []
  current_polyline = []

  segments_remaining = segments[:]

  while len(segments_remaining) > 0:
    # While we still have segments to sort

    # Use a temp list to avoid mutating while iterating over the main list
    segments_that_will_remain = []

    # If this is still false after checking all segments then we need to start a new polyline
    extended_this_polyline = False

    for segment in segments_remaining:
      start, end = segment

      if len(current_polyline) == 0:
        # Start the new poly line with whatever we get first
        current_polyline.append(start)
        current_polyline.append(end)
        extended_this_polyline = True
      else:
        first_point = current_polyline[0]
        last_point = current_polyline[-1]

        # If this segment is attached to the current poly line at either end then add it on
        if close_enough(last_point, start):
          current_polyline.append(end)
          extended_this_polyline = True
        elif close_enough(last_point, end):
          current_polyline.append(start)
          extended_this_polyline = True
        elif close_enough(first_point, start):
          current_polyline.insert(0, end)
          extended_this_polyline = True
        elif close_enough(first_point, end):
          current_polyline.insert(0, start)
          extended_this_polyline = True
        else:
          segments_that_will_remain.append(segment)

    if not extended_this_polyline:
      # None of the segments were able to fit so we must need to start a new poly line
      polylines.append(current_polyline)
      current_polyline = []
    else:
      segments_remaining = segments_that_will_remain

  # TODO: Minimize the distance between successive poly lines

  if len(current_polyline) > 0:
    polylines.append(current_polyline)

  return polylines

def toolpath_from_polylines(polylines):
  off_x = 0
  off_y = 0
  off_z = 0.5

  toolpath = []

  for polyline in polylines:
    # Move to above the first line
    first_x, first_y, first_z = polyline[0]
    toolpath.append((first_x + off_x, first_y + off_y, first_z + off_z))

    # Move along this polyline
    toolpath += polyline

    # Rise above the end of the polyline
    last_x, last_y, last_z = toolpath[-1]
    toolpath.append((last_x + off_x, last_y + off_y, last_z + off_z))

  return toolpath

def mesh_segments(mesh_obj):
  segments = []

  for edge in mesh_obj.data.edges:
    start_i = edge.vertices[0]
    end_i = edge.vertices[1]

    x1, y1, z1 = mesh_obj.data.vertices[end_i].co
    x2, y2, z2 = mesh_obj.data.vertices[start_i].co

    segments += [((x1, y1, z1), (x2, y2, z2))]
  
  return segments

def mesh_to_toolpath(mesh_obj):
  segments = mesh_segments(mesh_obj)
  contiguous_sections = group_contiguous_segments(segments)
  return toolpath_from_polylines(contiguous_sections)

def curve_from_points(name, points):
  # Adapted from https://blender.stackexchange.com/a/6751
  curve_data = bpy.data.curves.new(name, type='CURVE')
  curve_data.dimensions = '3D'
  curve_data.resolution_u = 2

  polyline = curve_data.splines.new('POLY')

  # Add the points to the curve
  polyline.points.add(len(points) - 1)
  for i, point in enumerate(points):
    x, y, z = point
    polyline.points[i].co = (x, y, z, 1)

  # Create a curve object with the toolpath where the original object is
  curve_object = bpy.data.objects.new(name, curve_data)

  return curve_object

class GenerateLightPathOperator(bpy.types.Operator):
  """Object to light path"""
  bl_idname = "binder.object_to_toolpath"
  bl_label = "Object to light path"
  bl_options = {"REGISTER", "UNDO"}

  def execute(self, context):
    # Validate selection
    for obj in bpy.context.selected_objects:
      if not obj.type == 'MESH':
        self.report({'ERROR'}, 'Selection must only include meshes')
        return {'CANCELLED'}

    toolpaths = [mesh_to_toolpath(mesh) for mesh in bpy.context.selected_objects]

    # Build script for light path

    script = ur_script.URScript()
    script.function('blender_move')

    complete_toolpath = []
    for toolpath in toolpaths:
      x0, y0, z0 = toolpath[0]
      script.movej()

    script.end()

    return {'FINISHED'}

def register():
  bpy.utils.register_class(URxExportAnimationOperator)
  bpy.utils.register_class(URxMoveToPoseOperator)
  #bpy.utils.register_class(GenerateLightPathOperator)

  # Register our keyboard shortcuts
  wm = bpy.context.window_manager
  kc = wm.keyconfigs.addon

  if kc:
    km = wm.keyconfigs.addon.keymaps.new(name='Window', space_type='EMPTY', region_type='WINDOW')
    kmi = km.keymap_items.new(URxMoveToPoseOperator.bl_idname, type='TAB', value='PRESS', alt=True)
    addon_keymaps.append((km, kmi))
    log.info('Keymaps registered')

  log.info('Registered add-on')

def unregister():
  bpy.utils.unregister_class(URxExportAnimationOperator)
  bpy.utils.unregister_class(URxMoveToPoseOperator)
  #bpy.utils.unregister_class(GenerateLightPathOperator)

  # Unregister our keyboard shortcuts
  for km, kmi in addon_keymaps:
    km.keymap_items.remove(kmi)

  addon_keymaps.clear()

  log.info('Unregistered keymaps')

  log.info('Unregistered add-on')

if __name__ == '__main__':
  register()
