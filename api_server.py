import threading, queue, os, uuid, json
import api_backend, sandbox, tempdir

MAX_LENGTH = 1073741824

_lock = threading.Lock()

def setup_pipes():
  name = 'SESSEN-PIPE-'+str(uuid.uuid4())
  client_path = os.path.join(tempdir.get_temp_dir(), name+'-CLIENT')
  server_path = os.path.join(tempdir.get_temp_dir(), name+'-SERVER')
  os.mkfifo(client_path)
  os.mkfifo(server_path)
  pipes = [client_path, server_path]
  threading.Thread(target=initialize_unix_pipe, args=pipes, daemon=True).start()
  return pipes


def initialize_unix_pipe(client_path, server_path):
  client_pipe = open(client_path, 'r')
  server_pipe = open(server_path, 'w')
  input_worker(client_pipe, server_pipe)


def initialize_pipes_from_process(proc):
  in_thread = threading.Thread(target=input_worker, args=(proc.stdout,proc.stdin), daemon=True)
  in_thread.start()


def input_worker(client_pipe, server_pipe):
  is_text = hasattr(client_pipe, 'encoding')
  while True:
    try:
      buf = client_pipe.readline(MAX_LENGTH)
      if not buf:
        return
      i = json.loads(buf if is_text else buf.decode())
      t = threading.Thread(target=api_call_worker, args=(i,server_pipe), daemon=True)
      t.start()
    except (json.decoder.JSONDecodeError, ValueError, TypeError) as ex:
      pass


def api_call_worker(i, server_pipe):
  try:
    id = i['id']
  except (KeyError, TypeError):
    print("DBG BAD JSON", i)
    return
  r, ex = None, None
  try:
    func_name = i['func']
    if func_name[0] == '_':
      raise RuntimeError("Sanboxed extensions can't call private functions in the API backend")
    func = getattr(api_backend, func_name)
    r = func(*i['args'], **i['kwargs'])
  except Exception as e:
    ex = repr(e)
  with _lock:
    j = json.dumps({'id': id, 'result': r, 'exception': ex})+'\n'
    server_pipe.write(j if hasattr(server_pipe, 'encoding') else j.encode())
    server_pipe.flush()
