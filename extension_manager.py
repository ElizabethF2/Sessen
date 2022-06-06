import sys, os, subprocess, threading, time, platform
import config, permissions, api_backend, api_server, sessen, sandbox, tempdir

_running_extensions = {}
_lock = threading.Lock()

custom_args = {}
extensions_folder = 'Extensions'

SANDBOX_SCRIPTS = [os.path.join(os.path.dirname(__file__), i) for i in ('sandboxed_libs', 'sandbox')]
sessen.is_hosted = True

STOP_EXTENSION_TIMEOUT = 5

def get_extension_paths(name):
  if name == '__pycache__':
    return None
  path = os.path.realpath(os.path.join(extensions_folder, name))
  p = os.path.join(path,'__init__.py')
  if os.path.exists(p):
    return p, path
  p = path + '.py'
  if os.path.exists(p):
    return p, None
  return None, None

def prune_stopped_extensions():
  for name in [k for k,v in filter(lambda i: i[1] and i[1].poll() is not None, _running_extensions.items())]:
    with _lock:
      _running_extensions.pop(name)
      api_backend._cleanup(name)

def non_sandboxed_extension_thread(ext_path, name):
  threading.current_thread().extension_name = name
  sessen.import_from_path(ext_path, name)

def start_extension(name, exclusive=False, force_sandbox=False):
  prune_stopped_extensions()
  with _lock:
    if name not in _running_extensions:
      ext_path, sys_path = get_extension_paths(name)
      if ext_path:
        secret = api_backend._secure_token()
        api_backend._register_ext_name(secret, name)
        api_backend._extension_options_set(secret, 'exclusive', exclusive)
        api_backend._extension_options_set(secret, 'custom_args', custom_args)
        perms = permissions.get(name)
        if force_sandbox or perms['use_sandbox']:
          id = 'Sessen_Extension_' + name

          ext_env = dict(os.environ)
          ext_env['SESSEN_NAME'] = name
          ext_env['SESSEN_SECRET'] = secret
          if platform.system() == 'Windows':
            pipes = []
          else:
            pipes = api_server.setup_pipes()
            ext_env['SESSEN_PIPE0'] = pipes[0]
            ext_env['SESSEN_PIPE1'] = pipes[1]
          ext_env['SESSEN_EXT_PATH'] = ext_path
          if sys_path:
            ext_env['SESSEN_SYS_PATH'] = sys_path
          if perms['strict_mode']:
            ext_env['SESSEN_STRICT_MODE'] = '1'
          if config.get_bool('no_exception_logging', default=False):
            ext_env['SESSEN_NO_EXCEPTION_LOGGING'] = '1'
          ext_env['SESSEN_BREAKPOINT'] = config.get('breakpoint_handler', default='sdb.breakpoint')
          ext_env['SESSEN_TEMP'] = os.path.join(tempdir.get_or_create_temp_dir(), name)

          _running_extensions[name] = sandbox.run_python(
                ['-u', 'extension_host.py', name],
                id,
                readable_paths = SANDBOX_SCRIPTS + perms['allowed_read_files'],
                writable_paths = pipes + perms['allowed_write_files'],
                writable_paths_ensure_exists = [ext_env['SESSEN_TEMP']] + perms['allowed_write_files_ensure_exists'],
                env=ext_env,
                cwd=SANDBOX_SCRIPTS[0])

          if platform.system() == 'Windows':
            api_server.initialize_pipes_from_process(_running_extensions[name])
        else:
          if sys_path not in sys.path:
            sys.path.append(sys_path)
          thread = threading.Thread(target=non_sandboxed_extension_thread, args=(ext_path,name), daemon=True).start()
          _running_extensions[name] = None

def start_autostart_extensions(force_sandbox=False):
  for name in config.get_list('autostart'):
    start_extension(name, force_sandbox=force_sandbox)

def ask_extension_to_stop(name):
  api_backend._exit_trigger(name)

def stop_extension_after_timeout(name, end_time):
  proc = _running_extensions.pop(name)
  if proc:
    try:
      proc.wait(max(0, end_time-time.time()))
    except subprocess.TimeoutExpired:
      proc.terminate()

def stop_extensions():
  with _lock:
    for name in list(_running_extensions.keys()):
      ask_extension_to_stop(name)
    end_time = time.time() + STOP_EXTENSION_TIMEOUT
    for name in list(_running_extensions.keys()):
      stop_extension_after_timeout(name, end_time)
  tempdir.cleanup_temp_dir()
