def f_to_s(v):
  return'{0:.5f}'.format(float(v))

def list_to_array(vals):
  return '[{}]'.format(','.join([f_to_s(v) for v in vals]))

class URScript(object):
  def __init__(self):
    self.text = ''

    # Starts inside of a function
    self.indent_level = 0

  def add_line(self, text):
    tabs = ''.join('\t' for i in range(0, self.indent_level))
    self.text += '{}{}\n'.format(tabs, text.strip())

  def function(self, name, args=[]):
    self.add_line('def {}({}):'.format(name, ', '.join(args)))
    self.indent_level += 1

  def end(self):
    if self.indent_level == 0:
      raise Exception('No structure to end')

    self.indent_level -= 1
    self.add_line('end')

  def set_tool_digital_out(self, index, state):
    self.add_line('set_tool_digital_out({}, {})'.format(index, state))

  def while_loop(self, condition):
    self.add_line('while {}:'.format(condition))
    self.indent_level += 1

  def servoj(self, angles, t=0.008, lookahead_time=0.1, gain=300):
    if not len(angles) == 6:
      raise Exception('Incorrect number of joint angles (need 6)')

    # Not used by the function
    a = 0
    v = 0
    
    self.add_line('servoj({}, {}, {}, {}, {}, {})'.format(list_to_array(angles), *[f_to_s(v) for v in [a, v, t, lookahead_time, gain]]))

  def movej(self, angles, a=1.4, v=1.05, t=0, r=0):
    if not len(angles) == 6:
      raise Exception('Incorrect number of joint angles (need 6)')

    self.add_line('movej({}, {}, {}, {}, {})'.format(list_to_array(angles), f_to_s(a), f_to_s(v), f_to_s(t), f_to_s(r)))

