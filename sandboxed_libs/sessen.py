import sys, os, json, uuid, threading, queue, inspect, re, binascii, pickle, mimetypes, time, urllib.parse, types, atexit, logging, wsgiref.handlers, importlib.util
import api_client

_cached_name = os.environ.get('SESSEN_NAME')
_cached_secret = os.environ.get('SESSEN_SECRET')
is_sandboxed = not not _cached_secret
is_hosted = False

if is_sandboxed:
  api = api_client
  if os.environ.get('SESSEN_STRICT_MODE'):
    mimetypes.guess_type('') # Prepopulate the cached type database since we won't be able to access it once the sandbox is locked
else:
  import api_backend as api
  _old_thread_start = threading.Thread.start
  def _thread_start_shim(self, *args, **kwargs):
    ct = threading.current_thread()
    self.extension_name = ct.extension_name if hasattr(ct, 'extension_name') else None
    return _old_thread_start(self, *args, **kwargs)
  threading.Thread.start = _thread_start_shim

def b2a(b):
  return binascii.b2a_base64(b, newline=False).decode()


def a2b(a):
  return binascii.a2b_base64(a)

def secure_token():
  return b2a(os.urandom(24))

_exit_funcs = {}

exit_event = threading.Event()
_should_wait_for_exit_event = False
def _start_exit_watcher():
  def watcher_thread():
    secret = _get_secret()
    api.exit_wait(secret)
    exit_event.set()
  threading.Thread(target=watcher_thread, daemon=True).start()


def get_name():
  if _cached_name:
    return _cached_name
  current_thread = threading.current_thread()
  if hasattr(current_thread, 'extension_name'):
    return current_thread.extension_name


def _get_secret():
  if is_sandboxed:
    return _cached_secret
  else:
    return api._get_secret(get_name())

def _make_stat(d):
  s = os.stat_result((0,)*os.stat_result.n_sequence_fields)
  for k,v in d.items():
    setattr(s, 'st_'+k, v)
  return s

class File(object):
  def __init__(self, path, mode='r', encoding=None):
    if encoding is None and 'b' not in mode:
      encoding = sys.getdefaultencoding()
    self.handle = api.file_open(_get_secret(), path, mode, encoding)
    self.mode = mode
    if encoding is not None:
      self.encoding = encoding
    self.closed = False

  def __del__(self):
    self.close()

  def __enter__(self):
    return self
  
  def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()

  def close(self):
    if not self.closed:
      api.file_close(self.handle)
      self.closed = True
  
  def fileno(self):
    return self.handle

  def read(self, length=None):
    if length is None:
      buf = b'' if 'b' in self.mode else ''
      while True:
        r = self.read(64*1024)
        if not r:
          return buf
        buf += r

    data = a2b(api.file_read(self.handle, length))
    if hasattr(self, 'encoding'):
      data = data.decode(self.encoding)
    return data

  def write(self, data):
    if hasattr(self, 'encoding'):
      data = data.encode(self.encoding)
    api.file_write(self.handle, data)

  def flush(self):
    api.file_flush(self.handle)

  def seek(self, offset, whence=0):
    api.file_seek(self.handle, offset, whence)

  def tell(self):
    return api.file_tell(self.handle)
  
  def stat(self):
    return _make_stat(api.file_fstat(self.handle))

def open(path, mode, encoding=None):
  return File(path, mode, encoding)

def get_file(path):
  with open(path, 'rb') as f:
    return f.read()

def write_file(path, data, mode='wb'):
  api.file_write(_get_secret(), path, mode, b2a(data))

def listdir(path):
  return api.file_list(_get_secret(), path)

def mkdir(path):
  return api.file_new_folder(_get_secret(), path)

def remove(path):
  return api.file_delete(_get_secret(), path)

def stat(path):
  return _make_stat(api.file_stat(_get_secret(), path))

def fstat(fileno):
  return _make_stat(api.file_fstat(fileno))

def copy(src, dst):
  with open(src, 'rb') as sf:
    with open(dst, 'xb') as df:
      while True:
        buf = sf.read(1024**2)
        if not buf:
          break
        df.write(buf)

def import_from_path(path, name=None):
  if not name:
    name = os.path.splitext(os.path.basename(path))[0]
  spec = importlib.util.spec_from_file_location(name, path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module

def import_from_code(code, name=None):
  module = types.ModuleType(name)
  exec(code, module.__dict__)
  return module

def import_from_path_via_broker(path, name=None):
  if not name:
    name = os.path.splitext(os.path.basename(path))[0]
  code = get_file(path)
  return import_from_code(code, name)

path = import_from_path(sys.modules[os.path.getmtime.__module__].__file__, 'sessen_path_shim')
path.os = sys.modules[__name__]

def bind_on_own_thread(method, route, callback=None):
  global _should_wait_for_exit_event
  _should_wait_for_exit_event = True
  if callback:
    secret = _get_secret()
    def listener(secret, method, route, callback):
      while True:
        d = api.connection_get(secret, method, route)
        t = threading.Thread(target=callback, args=(Connection(d),), daemon=True)
        t.start()
    t = threading.Thread(target=listener, args=(secret, method, route, callback), daemon=True)
    t.start()
  else:
    def decorator(func):
      bind_on_own_thread(method, route, func)
      return func
    return decorator


_bind_lock = threading.Lock()
_bind_routes = {}
def bind(method, route, callback=None):
  global _should_wait_for_exit_event
  _should_wait_for_exit_event = True
  if callback:
    secret = _get_secret()
    with _bind_lock:
      if secret not in _bind_routes:
        _bind_routes[secret] = []
        def route_connections(secret):
          while True:
            d = api.connection_get(secret, '.*', '.*')
            for r in _bind_routes[secret]:
              if re.match(r['route'], d['path']) and re.match(r['method'], d['method']):
                d['method_regex'] = r['method']
                d['route_regex'] = r['route']
                t = threading.Thread(target=r['callback'], args=(Connection(d),), daemon=True)
                t.start()
                break
        t = threading.Thread(target=route_connections, args=(secret,), daemon=True)
        t.start()
    _bind_routes[secret].append({'method': method, 'route': route, 'callback': callback})
  else:
    def decorator(func):
      bind(method, route, func)
      return func
    return decorator

def _parse_headers(h):
  headers = {}
  for line in h.splitlines():
    try:
      name = line[:line.index(':')]
      value = line[len(name)+1:].strip()
      headers.setdefault(name, []).append(value)
    except ValueError:
      pass
  return headers

class Connection(object):
  def __init__(self, d):
    self.__dict__.update(d)
    self.request_headers = _parse_headers(self.headers)
    self._parse_cookies()
    self.client_address = tuple(self.client_address)
    self.response_started = False
    self.response_code = 200
    self.headers = []
    self.args = re.match(self.route_regex, self.path).groupdict()
    parsed_url = urllib.parse.urlparse(self.path)
    self.query = urllib.parse.parse_qs(parsed_url.query)

  def _parse_cookies(self):
    self.cookies = {}
    try:
      for cookies in self.request_headers['Cookie']:
        for cookie in cookies.split(';'):
          name, value = cookie.split('=')
          self.cookies[name.strip()] = value.strip()
    except (KeyError, IndexError):
      pass

  def __del__(self):
    api.connection_close(self.handle)

  def read(self, length):
    return a2b(api.connection_read(self.handle, length))

  def receive_json(self):
    cl = int(self.request_headers['Content-Length'][0])
    buf = b''
    remaining = cl
    while remaining > 0:
      b = self.read(min(4096, remaining))
      if not b:
        break
      buf += b
      remaining -= len(b)
    return json.loads(buf.decode())

  def set_response_code(self, code):
    self.response_code = code
  
  def add_header(self, name, value):
    self.headers.append((name,value))

  def set_cookie(self, name, value, expires = None, max_age = None,
                 domain = None, Path = None, secure = False,
                 http_only = False, same_site = None):
    val = name+'='+value
    if expires:
      if type(expires) is not str:
        expires = wsgiref.handlers.format_date_time(expires)
      val += '; Expires=' + expires
    if secure:
      val += '; Secure'
    if http_only:
      val += '; HttpOnly'
    self.add_header('Set-Cookie', val)

  def get_user_id(self):
    try:
      return self.cookies['_sessen_uid']
    except KeyError:
      expires = time.time() + (10*365*24*60*60) # 10 years from now
      id = str(uuid.uuid4())
      self.set_cookie('_sessen_uid', id, expires=expires)
      return id

  def get_session_id(self):
    try:
      return self.cookies['_sessen_sid']
    except KeyError:
      id = str(uuid.uuid4())
      self.set_cookie('_sessen_sid', id)
      return id

  def _ensure_response_started(self):
    if not self.response_started:
      api.connection_begin_response(self.handle, self.response_code, self.headers)
      self.response_started = True

  def write(self, data, encoding='utf-8'):
    self._ensure_response_started()
    if type(data) is str:
      data = data.encode(encoding)
    api.connection_write(self.handle, b2a(data))

  def send_text(self, text, content_type='text/plain'):
    self.set_response_code(200)
    self.add_header('Content-Type', content_type)
    self.add_header('Content-Length', len(text))
    self.write(text)

  def send_html(self, html):
    self.send_text(html, content_type='text/html')

  def send_json(self, data):
    j = json.dumps(data)
    self.send_text(j, content_type='application/json')

def serve_static_content(path='static'):
  secret = _get_secret()
  route = ('/'+path+'/(?P<path>.+)').replace('//','/')
  static_root = path[1:] if path[0] == os.path.sep else path
  _cache = {}
  def callback(connection):
    path = connection.args['path']
    full_path = os.path.join(static_root, path)
    try:
      try:
        data = _cache[path]
      except KeyError:
        data = get_file(full_path)
        _cache[path] = data
      ctype = mimetypes.guess_type(path)[0]
      connection.send_text(data, ctype=ctype)
    except (FileNotFoundError, PermissionError):
      connection.set_response_code(400)
      connection.write('Not Found!')
  bind('GET', route, callback)

class _Datastore(object):
  sep = '/'

  def join_path(self, *paths):
    path = self.sep.join(paths)
    return re.sub('/+','/',path)

  def extension_path(self, path=None):
    if path:
      return self.join_path('extensions', get_name(), path)
    return self.join_path('extensions', get_name())

  def shared_path(self, path):
    return self.join_path('shared', path)
  
  def __getitem__(self, path):
    return pickle.loads(a2b(api.datastore_get(_get_secret(), path)))

  def get_raw(self, path):
    return a2b(api.datastore_get(_get_secret(), path))

  def __setitem__(self, path, value):
    api.datastore_set(_get_secret(), path, b2a(pickle.dumps(value)))

  def set_raw(self, path, value):
    api.datastore_set(_get_secret(), path, b2a(value))

  def __delitem__(self, path):
    api.datastore_delete(_get_secret(), path)

  def keys(self, path):
    page = 0
    while True:
      k = api.datastore_keys(_get_secret(), path, page)
      for i in k:
        yield i
      if len(k) < 1:
        return
      page += 1

  def test_and_set(self, path, value):
    return pickle.loads(a2b(api.datastore_test_and_set(_get_secret(),
                                                       path,
                                                       b2a(pickle.dumps(value)))))
  def get(self, path):
    try:
      return self[path]
    except KeyError:
      return None

datastore = _Datastore()

# TODO: avoid creating user paths until something is set

class PersistentDatastore(object):
  def __init__(self, path = 'persistent', expires = (365*24*60*60), cleanup_frequency = (15*60)):
    self.path = datastore.extension_path(path) + datastore.sep
    self.expires = expires
    self.cleanup_frequency = cleanup_frequency
    self.last_cleanup = time.time()

  def get_id(self, connection):
    try:
      return connection.get_user_id()
    except AttributeError:
      return connection

  def cleanup(self):
    users_to_delete = []
    target_depth = self.path.count('/') + 1
    for key in datastore.keys(self.path):
      if key.count('/') == target_depth and key.endswith('/last_access'):
        last_access = datastore[key]
        if time.time() - last_access > self.expires:
          id = key[len(self.path):-12]
          users_to_delete.append(id)
    for id in users_to_delete:
      for key in datastore.keys(datastore.join_path(self.path, id)+'/'):
        del datastore[key]
    self.last_cleanup = time.time()

  def maybe_cleanup(self):
    if time.time() - self.last_cleanup >= self.cleanup_frequency:
      self.cleanup()

  def touch_and_get_path(self, connection, path):
    id = self.get_id(connection)
    user_path = datastore.join_path(self.path, id)
    datastore[datastore.join_path(user_path, 'last_access')] = time.time()
    self.maybe_cleanup()
    return datastore.join_path(user_path, 'data', path)

  def get(self, connection, path):
    return datastore[self.touch_and_get_path(connection, path)]

  def set(self, connection, path, value):
    datastore[self.touch_and_get_path(connection, path)] = value
  
  def delete(self, connection, path):
    del datastore[self.touch_and_get_path(connection, path)]

  def keys(self, connection, path):
    user_path = datastore.join_path(self.path, id)
    old_path_len = len(datastore.join_path(user_path, 'data') + datastore.sep)
    for key in datastore.keys(self.touch_and_get_path(connection, path)):
      yield key[old_path_len:]

  def delete_all(self, connection):
    id = self.get_id(connection)
    path = datastore.join_path(self.path, id) + '/'
    for key in datastore.keys(path):
      try:
        del datastore[key]
      except KeyError:
        pass

class SessionDatastore(PersistentDatastore):
  def __init__(self, path = 'session', expires = (3*24*60*60), cleanup_frequency = (15*60)):
    PersistentDatastore.__init__(self, path, expires, cleanup_frequency)

  def get_id(self, connection):
    try:
      return connection.get_session_id()
    except AttributeError:
      return connection

class datastore_lock(object):
  def __init__(self, path, timeout=None):
    self.path = path
    self.timeout = timeout

  def __enter__(self):
    oldest = time.time()
    sleep_duration = 0.001
    while True:
      try:
        old = datastore.test_and_set(self.path, {'last_set':time.time()})
        oldest = min(oldest, old['last_set'])
        if self.timeout and (time.time()-oldest) > self.timeout:
          break
      except KeyError:
        break
      time.sleep(sleep_duration)
      sleep_duration *= 2

  def __exit__(self, *e):
    del datastore[self.path]

class ExtensionDatastore(object):
  def __init__(self):
    self.path = datastore.extension_path()

  def join_path(self, *paths):
    return datastore.join_path(self.path, *paths)

  def __getitem__(self, path):
    return datastore[self.join_path(path)]

  def get_raw(self, path):
    return datastore.get_raw(self.join_path(path))

  def __setitem__(self, path, value):
    datastore[self.join_path(path)] = value

  def set_raw(self, path, value):
    datastore.set_raw(self.join_path(path), value)

  def __delitem__(self, path):
    del datastore[self.join_path(path)]

  def keys(self, path):
    old_path_len = len(self.path + datastore.sep)
    for key in datastore.keys(self.join_path(path)):
      yield key[old_path_len:]

  def test_and_set(self, path, value):
    return datastore.test_and_set(self.join_path(path), value)
  
  def lock(self, path, timeout=None):
    return datastore_lock(self.join_path(path), timeout)

USER_AGENT = 'Sessen Alpha WebRequest API R4'

class webrequest(object):
  def __init__(self, method, url, headers=None, data=None, ssl_verify=True, timeout=None):
    if headers is None:
      headers = {}
      headers['User-Agent'] = USER_AGENT
    if data is not None:
      data = b2a(data)
    d = api.webrequest(_get_secret(), method, url, headers, data, ssl_verify, timeout)
    self.__dict__.update(d)
    self.data = a2b(self.data)
    try:
      self.headers = _parse_headers(self.info)
    except AttributeError:
      pass

  def text(self, encoding=None):
    if encoding:
      return self.data.decode(encoding)
    try:
      ctype = self.headers['Content-Type']
      encoding = ctype[ctype.index('charset=')+8:].strip()
      return self.data.decode(encoding)
    except (KeyError, ValueError, IndexError, LookupError):
      return self.data.decode()

  def json(self):
    return json.loads(self.data)

class websession(object):
  def __init__(self):
    self.cookies = {}
  
  def request(self, *a, **k):
    if 'headers' not in k:
      k['headers'] = {b'User-Agent': USER_AGENT}
    k['headers'][b'cookie'] = ';'.join((k+'='+v for k,v in self.cookies.items()))
    req = webrequest(*a, **k)
    reserved = ['expires', 'path', 'comment', 'domain', 'max-age', 'secure', 'version', 'httponly', 'samesite']
    try:
      for chunk in req.headers['set-cookie'].split(';'):
        try:
          name, value = chunk.split('=')
          name = name.split(',')[-1].strip()
          if name.lower() not in reserved:
            self.cookies[name] = value.strip()
        except ValueError:
          pass
    except KeyError:
      pass
    return req

def get_extension_depth():
  try:
    return inspect.currentframe().f_back.f_globals['_sessen_internal_extension_depth']
  except KeyError:
    return 0


def load_subextension(path, name=None):
  if name is None:
    name = os.path.splitext(os.path.basename(path))[0]
  try:
    current_depth = inspect.currentframe().f_back.f_globals['_sessen_internal_extension_depth']
  except KeyError:
    current_depth = 0
  code = get_file(path)
  module = types.ModuleType(name)
  module.__dict__['_sessen_internal_extension_depth'] = current_depth + 1
  module.__file__ = path
  exec(code, module.__dict__)
  return module


def bypass_path_validation_for_non_extensions():
  global _get_secret
  if not is_sandboxed and len(api._secret2ext_name) < 1:
    _get_secret = lambda *a: None
    api._datastore_validate_path = lambda *a: None
    api._webrequest_validate_path = lambda *a: None
  else:
    raise RuntimeError('bypass_path_validation_for_non_extensions should not be called from an extension')


def running_exclusively():
  return api.extension_options_get(_get_secret(), 'exclusive')


def custom_args():
  return api.extension_options_get(_get_secret(), 'custom_args')


class LoggingHandler(logging.Handler):
  def __init__(self, level=1):
    logging.Handler.__init__(self, level)
    self.secret = _get_secret()
    self.setFormatter(logging.Formatter('[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'))

  def emit(self, record):
    msg = self.format(record)
    api.log(self.secret, record.levelno, msg)

def getLogger(name=None, handler=None, level=1):
  if name:
    name = 'extension.' + get_name() + '.' + name
  else:
    name = 'extension.' + get_name()
  logger = logging.getLogger(name)
  if not hasattr(logger, 'initialized_by_sessen'):
    logger.setLevel(level)
    logger.initialized_by_sessen = True
    if not handler:
      logger.addHandler(LoggingHandler(level))
  return logger

def _postmaster_shared_function_worker(message):
  try:
    ext_name = get_name()
    func_name = message['func']
    if ext_name not in _shared_functions or func_name not in _shared_functions[ext_name]:
      remaining = time.time() - _postmaster_start_times[ext_name]
      if remaining < postmaster_startup_grace_period:
        time.sleep(remaining)
  except (KeyError, AttributeError):
    return

  result = None
  exception = None

  try:
    result = _shared_functions[ext_name][func_name](*message['args'], **message['kwargs'])
  except Exception as ex:
    exception = repr(ex)
  try:
    reply = {'id': message['id'], 'result': result, 'exception': exception}
    api.messages_send(_get_secret(), message['sender'], reply)
  except KeyError:
    pass

def _postmaster_function_call_handler(message):
  try:
    if message['action'] == 'call':
      threading.Thread(target=_postmaster_shared_function_worker, args=(message,), daemon=True).start()
      return True
    elif message['action'] == 'list_functions':
      remaining = time.time() - _postmaster_start_times[get_name()]
      if remaining < postmaster_startup_grace_period:
        time.sleep(remaining)
      reply = {'id': message['id'], 'result': list(_shared_functions[get_name()].keys())}
      api.messages_send(_get_secret(), message['sender'], reply)
      return True
    elif message['action'] == 'has_function':
      result = message['name'] in _shared_functions[get_name()]
      if not result:
        remaining = time.time() - _postmaster_start_times[get_name()]
        if remaining < postmaster_startup_grace_period:
          time.sleep(remaining)
          result = message['name'] in _shared_functions[get_name()]
      reply = {'id': message['id'], 'result': result}
      api.messages_send(_get_secret(), message['sender'], reply)
      return True
  except (KeyError, IndexError, TypeError):
    return False

def _postmaster_function_result_handler(message):
  try:
    result = _shared_function_results[message['id']]
    result.put((message['result'], message['exception']))
    return True
  except KeyError:
    return False

def _postmaster_event_handler(message):
  try:
    if message['action'] == 'fire_event':
      with _postmaster_lock:
        for event_handler in _event_subscriptions[message['name']]:
          threading.Thread(target=event_handler, args=message['args'], daemon=True).start()
      return True
  except KeyError:
    return False

postmaster_startup_grace_period = 5
postmaster_handlers = [_postmaster_function_call_handler,
                       _postmaster_function_result_handler,
                       _postmaster_event_handler]
_postmaster_lock = threading.Lock()
_postmaster_start_times = {}
_shared_functions = {}
_shared_function_results = {}
_event_subscriptions = {}

def _postmaster_worker_thread():
  while True:
    for message in api.messages_get(_get_secret()):
      for handler in postmaster_handlers:
        handled = handler(message)
        if handled:
          break

def _ensure_postmaster_running():
  name = get_name()
  with _postmaster_lock:
    if name not in _postmaster_start_times:
      _postmaster_start_times[name] = time.time()
      threading.Thread(target=_postmaster_worker_thread, daemon=True).start()

def share(func):
  global _should_wait_for_exit_event
  _should_wait_for_exit_event = True
  _ensure_postmaster_running()
  _shared_functions.setdefault(get_name(), {})[func.__name__] = func

def subscribe_to_event(name, handler):
  global _should_wait_for_exit_event
  _should_wait_for_exit_event = True
  _ensure_postmaster_running()
  with _postmaster_lock:
    _event_subscriptions.setdefault(name, set()).add(handler)

def unsubscribe_from_event(name, handler):
  with _postmaster_lock:
    _event_subscriptions[name].remove(handler)

class ExtensionProxyTimeout(Exception):
  pass

def _send_message_and_get_reply(recipient, message, timeout=None):
  _ensure_postmaster_running()
  id = secure_token()
  result = queue.Queue()
  _shared_function_results[id] = result
  message['sender'] = get_name()
  message['id'] = id
  api.messages_send(_get_secret(), recipient, message)
  try:
    result, exception = result.get(timeout=timeout)
  except queue.Empty:
    raise ExtensionProxyTimeout()
  finally:
    _shared_function_results.pop(id)
  if exception:
    raise api_client._parse_exception(exception)
  return result

class ExtensionProxy(object):
  def __init__(self, name, timeout=None):
    self._name = name
    self._timeout = timeout

  def _has_function(self, func):
    return _send_message_and_get_reply(self._name, {'action':'has_function', 'name': func}, timeout=self._timeout)

  def __dir__(self):
    return _send_message_and_get_reply(self._name, {'action':'list_functions'}, timeout=self._timeout)

  def _fire_event(self, target, event_name, args=[]):
    if type(target) is ExtensionProxy:
      target = target._name
    message = {'action':'fire_event', 'name':event_name, 'args':args}
    api.messages_send(target, message, timeout=self._timeout)

  def __getattr__(self, func):
    return lambda *a, **k: _send_message_and_get_reply(self._name,
              {'action':'call', 'func':func, 'args':a, 'kwargs':k}, timeout=self._timeout)


def get_neighbors(timeout=None):
  return [ExtensionProxy(name, timeout=timeout) for name in api.messages_list_recipients(_get_secret())]
