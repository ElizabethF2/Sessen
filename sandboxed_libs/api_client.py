import threading, queue, json, uuid, platform, sys, os

_results = {}
_lock = threading.Lock()

def _init():
  global _client_pipe
  if not os.environ.get('SESSEN_SECRET'):
    # Only initialize the client if we're sandboxed
    return

  pipes = os.environ.get('SESSEN_PIPE0'), os.environ.get('SESSEN_PIPE1')
  if platform.system() == 'Windows':
    _client_pipe = sys.stdout
    server_pipe = sys.stdin
  else:
    client_path, server_path = pipes
    if os.environ.get('SESSEN_STRICT_MODE'):
      import preflight
      preflight.PATH_EXCEPTIONS.extend(pipes)
    _client_pipe = open(client_path, 'w')
    server_pipe = open(server_path, 'r')
  in_thread = threading.Thread(target=_input_worker, args=(server_pipe,), daemon=True)
  in_thread.start()

def _parse_exception(exception):
  try:
    return eval(exception)
  except NameError:
    if exception.startswith('NameError('):
      return exception
  return Exception(exception)

def _invoke(func, args, kwargs):
  id = str(uuid.uuid4())
  res_q = queue.Queue()
  i = {'func': func, 'args': args, 'kwargs': kwargs, 'id': id}
  try:
    with _lock:
      _results[id] = res_q
      _client_pipe.write(json.dumps(i)+'\n')
      _client_pipe.flush()
  except TypeError:
    breakpoint()
  r, ex = res_q.get()
  if ex:
    raise _parse_exception(ex)
  return r

def _input_worker(server_pipe):
  while True:
    rres = json.loads(server_pipe.readline())
    with _lock:
      res_q = _results.pop(rres['id'])
    res_q.put((rres['result'], rres['exception']))


def __getattr__(func):
  if func[0] != '_':
    return lambda *a, **k: _invoke(func, a, k)


_init()
