import http.server, socketserver, threading, ssl, socket
import config, api_backend

class RequestHandler(http.server.BaseHTTPRequestHandler):
  def handle_one_request(self):
    try:
      self.raw_requestline = self.rfile.readline(65537)
      if len(self.raw_requestline) > 65536:
          self.requestline = ''
          self.request_version = ''
          self.command = ''
          self.send_error(414)
          return
      if not self.raw_requestline:
          self.close_connection = 1
          return
      if not self.parse_request():
          return
      api_backend._connection_route(self)
      self.wfile.flush()
    except socket.timeout:
      self.close_connection = 1
      return

  def log_message(self, format, *args):
    if config.get_bool('print_http_requests', default=True):
      print('%s - - [%s] %s' %
            (self.address_string(),
             self.log_date_time_string(),
             format%args))

class MultiThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
  daemon_threads = True

def serve_forever(bind=None, port=None):
  if port is None:
    port = config.get_int('port', default = 9292)
  if bind is None:
    bind = config.get_int('bind', default = '')
  httpd = MultiThreadedServer((bind,port), RequestHandler)

  if config.get_bool('use_ssl', default = True):
    context = ssl.create_default_context()
    httpd.socket = ssl.wrap_socket(httpd.socket,
                                   certfile=config.get('certfile', default='cert.pem'),
                                   keyfile=config.get('keyfile', default='key.pem'),
                                   server_side=True)

  try:
    httpd.serve_forever()
  except KeyboardInterrupt:
    pass
  return httpd
