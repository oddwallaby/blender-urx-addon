import sys
import socket
import select
from threading import Thread
from struct import unpack

def get_www_routable_ip():
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.connect(('8.8.8.8', 80))
  address = s.getsockname()[0]
  s.close()
  return address

class Server(object):
  def __init__(self, port):
    self.port = port
    self.running = True

  def run(self):
    self.thread = Thread(target=self.serve)
    self.thread.daemon = True
    self.thread.start()

  def stop(self):
    self.running = False
    self.thread.join()

  def serve(self):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((get_www_routable_ip(), self.port))
    sock.listen(0)

    print('Waiting for connection')

    while self.running:
      clients_available, _, _ = select.select([sock], [], [], 1)

      if len(clients_available) > 0:
        client, _ = sock.accept()

        print('Client connected')

        buffer = []

        while self.running and not client == None:
          data = client.recv(1)

          if not data:
            # Client disconnected
            pass
          else:
            buffer += data

            if len(buffer) == 28:
              print(unpack('>iiiiiii', bytes(buffer)))

def main():
  if not len(sys.argv) == 2:
    print('Usage: {} port'.format(sys.argv[0]))
    sys.exit(1)

  port = int(sys.argv[1])

  server = Server(port)
  server.run()

  try:
    while True:
      yield
  except KeyboardInterrupt:
    server.stop()

if __name__ == "__main__":
  main()
