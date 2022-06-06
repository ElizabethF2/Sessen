import sys as _sys, os as _os, threading as _threading, re as _re, binascii as _binascii, urllib.request as _request, logging as _logging, platform as _platform, ssl as _ssl
import permissions as _permissions, extension_manager as _extension_manager, config as _config, time as _time, sandbox.util as _util
_datastore = __import__(_config.get('datastore_driver', default = 'sqlite_datastore'))

_EPERM = 1

try:
  import requests as _requests
except ImportError:
  _requests = None

_secret2ext_name = {}
_ext_name2secret = {}
_connections = {}
_connection_lock = _threading.Lock()
_files = {}
_file_lock = _threading.Lock()
_extension_options = {}
_inboxes = {}
_inbox_lock = _threading.Lock()
_exit_events = {}
_logging_lock = _threading.Lock()

def _b2a(b):
  return _binascii.b2a_base64(b, newline=False).decode()

def _a2b(a):
  return _binascii.a2b_base64(a)

def _secure_token():
  return _b2a(_os.urandom(24))

def _register_ext_name(secret, ext_name):
  _secret2ext_name[secret] = ext_name
  _ext_name2secret[ext_name] = secret
  _extension_options[secret] = {}

def _get_ext_name(secret):
  return _secret2ext_name[secret]

def _get_secret(ext_name):
  return _ext_name2secret[ext_name]

def _cleanup(name):
  secret = _ext_name2secret.pop(name)
  _secret2ext_name.pop(secret)
  with _connection_lock:
    for handle in list(_connections.keys()):
      if _connections[handle]['ext_name'] == name:
        _connections.pop(handle)
  with _file_lock:
    for handle in list(_files.keys()):
      if _files[handle]['ext_name'] == name:
        _files.pop(handle)
  try:
    _exit_events.pop(name)
  except KeyError:
    pass

def _extension_options_set(secret, option, value):
  _extension_options[secret][option] = value

def extension_options_get(secret, option):
  return _extension_options[secret][option]

def _connection_route(request):
  sp = request.path.split('/')
  name = sp[1]
  _extension_manager.start_extension(name)
  if name not in _ext_name2secret:
    request.send_error(404)
    return
  route = '/'+'/'.join(sp[2:])
  connection = None
  retry_count = _config.get_int('connection_retry_count', default=50)
  retry_delay = _config.get_float('connection_retry_delay', default=0.1)
  handler_available_but_busy = False
  while not connection:
    for _ in range(retry_count):
      with _connection_lock:
        for handle, c in _connections.items():
          if (name == c['ext_name'] and
              _re.match(c['method'], request.command) and
              _re.match(c['route'], route)
             ):
               if c['ready'].is_set():
                 handler_available_but_busy = True
               else:
                 connection = c
                 connection['request'] = request
                 connection['done'] = _threading.Event()
                 connection['ready'].set()
                 break
      if connection:
        break
      _time.sleep(retry_delay)
    if not handler_available_but_busy or not _config.get_bool('busy_connection_waiting', default=True):
      break
  if connection:
    connection['done'].wait()
    with _connection_lock:
      _connections.pop(handle)
  elif handler_available_but_busy:
    request.send_response(503)
    request.send_header('Retry-After', str(_config.get_int('busy_connection_retry_delay', 20)))
    request.end_headers()
  else:
    request.send_error(404)
    return None


def connection_get(secret, method, route):
  name = _get_ext_name(secret)
  handle = _secure_token()
  c = {
       'ready': _threading.Event(),
       'method': method,
       'route': route,
       'ext_name': name
      }
  with _connection_lock:    
    _connections[handle] = c
  c['ready'].wait()
  d = {
       'handle': handle,
       'path': c['request'].path[len(name)+1:],
       'method': c['request'].command,
       'method_regex': c['method'],
       'route_regex': c['route'],
       'headers': str(c['request'].headers),
       'client_address': c['request'].client_address,
      }
  return d

def connection_read(handle, length):
  request = _connections[handle]['request']
  return _b2a(request.rfile.read(length))

def connection_begin_response(handle, code, headers):
  request = _connections[handle]['request']
  request.send_response(code)
  for name, value in headers:
    request.send_header(name, value)
  request.end_headers()

def connection_write(handle, buf):
  request = _connections[handle]['request']
  request.wfile.write(_binascii.a2b_base64(buf))

def connection_close(handle):
  connection = _connections[handle]
  connection['done'].set()

def _datastore_validate_path(secret, path, write):
  permissions = _permissions.get(_get_ext_name(secret))
  allowed_paths = [i if i.endswith('/') else i+'/' for i in permissions['allowed_write_datastore']]
  if not write:
    allowed_paths.extend([i if i.endswith('/') else i+'/' for i in permissions['allowed_read_datastore']])
  for allowed_path in allowed_paths:
    if path.startswith(allowed_path):
      return
  raise PermissionError(_EPERM, 'Inaccessible datastore path', path)

def datastore_get(secret, path):
  _datastore_validate_path(secret, path, False)
  return _b2a(_datastore.get(path))

def datastore_set(secret, path, value):
  _datastore_validate_path(secret, path, True)
  return _datastore.set(path, _a2b(value))

def datastore_delete(secret, path):
  _datastore_validate_path(secret, path, True)
  return _datastore.delete(path)

def datastore_keys(secret, path, page):
  _datastore_validate_path(secret, path, False)
  return list(_datastore.keys(path, page))

def datastore_test_and_set(secret, path, value):
  _datastore_validate_path(secret, path, True)
  return _b2a(_datastore.test_and_set(path, _a2b(value)))

def exit_wait(secret):
  name = _get_ext_name(secret)
  e = _exit_events.setdefault(name, _threading.Event())
  e.wait()

def _exit_trigger(name):
  try:
    _exit_events[name].set()
  except KeyError:
    pass

def _file_validate_path(secret, path, write):
  ext_name = _get_ext_name(secret)
  if not _os.path.isabs(path):
    path = _os.path.join(_extension_manager.extensions_folder, ext_name, path)
  path = _os.path.abspath(path)
  permissions = _permissions.get(ext_name)
  allowed_paths = list(permissions['allowed_write_files'])
  if not write:
    allowed_paths.extend(permissions['allowed_read_files'])
  if not permissions['strict_mode']:
    for allowed_path in allowed_paths:
      if _util.path_contains_or_is_in_path(allowed_path, path):
        return path
  else:
    epath = sys_path if sys_path else ext_path
    if _util.path_contains_or_is_in_path(epath, path):
      return epath
  raise PermissionError(_EPERM, 'Inaccessible file path', path)

def _file_validate_mode(mode):
  writable = False
  if type(mode) is not str:
    raise TypeError("open() argument 'mode' must be str, not bytes")
  mode = list(mode)
  if 'b' in mode:
    mode.remove('b')
  if '+' in mode:
    writable = True
    mode.remove('+')
  mode = ''.join(mode)
  if mode == 'r':
    pass
  elif mode in ('w', 'a', 'x'):
    writable = True
  else:
    raise ValueError("invalid mode: '"+mode+'"')
  return writable

def file_open(secret, path, mode, encoding):
  ext_name = _get_ext_name(secret)
  write = _file_validate_mode(mode)
  apath = _file_validate_path(secret, path, write)
  handle = _secure_token()
  with _file_lock:
    _files[handle] = {
      'fh': open(apath, mode, encoding=encoding),
      'ext_name': ext_name,
    }
    return handle

def file_close(handle):
  with _file_lock:
    fh = _files.pop(handle)['fh']
  fh.close()

def file_read(handle, length):
  length = min(length, 1024**2)
  fh = _files[handle]['fh']
  data = fh.read(length)
  if hasattr(fh, 'encoding'):
    data = data.encode(fh.encoding)
  return _b2a(data)

def file_write(handle, data):
  fh = _files[handle]['fh']
  data = _a2b(data)
  if hasattr(fh, 'encoding'):
    data = data.decode(fh.encoding)
  fh.write(data)

def file_flush(handle):
  _files[handle]['fh'].flush()

def file_seek(handle, offset, whence):
  _files[handle]['fh'].seek(offset, whence)

def file_tell(handle):
  return _files[handle]['fh'].tell()

def file_fstat(handle):
  stat = _os.fstat(_files[handle]['fh'].fileno())
  return {a[3:]:getattr(stat,a) for a in filter(lambda i: i.startswith('st_'), dir(stat))}

def file_stat(secret, path):
  apath = _file_validate_path(secret, path, False)
  stat = _os.stat(apath)
  return {a[3:]:getattr(stat,a) for a in filter(lambda i: i.startswith('st_'), dir(stat))}

def file_list(secret, path):
  apath = _file_validate_path(secret, path, False)
  return _os.listdir(apath)

def file_new_folder(secret, path):
  apath = _file_validate_path(secret, path, True)
  _os.mkdir(apath)

def file_delete(secret, path):
  apath = _file_validate_path(secret, path, True)
  if _os.path.isfile(apath):
    _os.remove(apath)
  else:
    _os.rmdir(apath)

def _tag_lines(msg, name):
  name_tag = '['+name+'] '
  lname_tag = len(name_tag)
  width, _ = _os.get_terminal_size()
  tagged_msg = []
  for line in msg.splitlines():
    if (len(line) + lname_tag) > width:
      idx = line.rfind(' ', 0, width-lname_tag)
      if idx == -1:
        tagged_msg.append(name_tag + line[:width-lname_tag])
        tagged_msg.append(name_tag + line[width-lname_tag:])
      else:
        tagged_msg.append(name_tag + line[:idx])
        tagged_msg.append(name_tag + line[idx:])
    else:
      tagged_msg.append(name_tag + line)
  return '\n'.join(tagged_msg)

def log(secret, level, msg):
  name = _get_ext_name(secret)
  msg = _tag_lines(msg, name)
  with _logging_lock:
    logger = _logging.getLogger('sessen')
    logger.log(level, msg)
    if _config.get_bool('print_log', default=True):
      for a in dir(_logging):
        if getattr(_logging, a) == level:
          level = a
          break
      print(level, msg)
  
def _mesages_get_or_create_inbox(name):
  with _inbox_lock:
    try:
      inbox = _inboxes[name]
    except KeyError:
      inbox = {'messages':[], 'got_mail': _threading.Event()}
      _inboxes[name] = inbox
  return inbox

def messages_get(secret):
  ext_name = _get_ext_name(secret)
  inbox = _mesages_get_or_create_inbox(ext_name)
  inbox['got_mail'].wait()
  with _inbox_lock:
    messages = inbox['messages']
    inbox['messages'] = []
    inbox['got_mail'].clear()
  return messages

def messages_list_recipients(secret):
  permissions = _permissions.get(_get_ext_name(secret))
  return permissions['allowed_extensions']

def messages_send(secret, recipient, message):
  if recipient not in messages_list_recipients(secret):
    raise PermissionError(_EPERM, 'Invalid recipient', recipient)
  inbox = _mesages_get_or_create_inbox(recipient)
  with _inbox_lock:
    inbox['messages'].append(message)
    inbox['got_mail'].set()
  _extension_manager.start_extension(recipient)

def _webrequest_validate_path(secret, url):
  permissions = _permissions.get(_get_ext_name(secret))
  allow = False
  for rx in permissions['allowed_urls']:
    if _re.match(rx, url):
      allow = True
  for rx in permissions['blocked_urls']:
    if _re.match(rx, url):
      allow = False
  if not allow:
    raise PermissionError(_EPERM, 'Inaccessible URL', url)

def webrequest(secret, method, url, headers, data, ssl_verify, timeout):
  _webrequest_validate_path(secret, url)
  if type(ssl_verify) is not bool:
    raise TypeError('ssl_verify must be bool')
  if data is not None:
    data = _a2b(data)
  if _requests:
    res = _requests.request(method, url=url, headers=headers, data=data, verify=ssl_verify, timeout=timeout)
    return {
            'url': res.url,
            'response_code': res.status_code,
            'data': _b2a(res.content),
            'headers': dict(res.headers)
           }
  else:
    ctx = None
    if not ssl_verify:
      cxt = ssl.SSLContext()
    req = _request.Request(url, headers=headers, data=data, context=ctx, timeout=timeout)
    req.method = method
    res = _request.urlopen(req)
    return {
            'url': res.geturl(),
            'response_code': res.getcode(),
            'info': str(res.info()),
            'data': _b2a(res.read())
           }
