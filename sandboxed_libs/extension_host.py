import sys, os, types, importlib.util, ast, time, importlib, platform
sys.path.extend([os.path.dirname(__file__), os.path.join('..', 'sandbox')])
import api_client, sessen, preflight

def handle_exception(exc_type, exc_value, exc_traceback):
  if issubclass(exc_type, KeyboardInterrupt):
    return sys.__excepthook__(exc_type, exc_value, exc_traceback)
  logger.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

def handle_exception_in_thread(args):
  handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

def main():
  global logger
  if not os.environ.get('SESSEN_NO_EXCEPTION_LOGGING'):
    import threading
    logger = sessen.getLogger()
    sys.excepthook = handle_exception
    threading.excepthook = handle_exception_in_thread

  ext_path = os.environ.get('SESSEN_EXT_PATH')
  name = sessen.get_name()
  secret = sessen._get_secret()
  strict_mode = os.environ.get('SESSEN_STRICT_MODE')
  breakpoint_handler = os.environ.get('SESSEN_BREAKPOINT')
  temp_dir = os.environ.get('SESSEN_TEMP')
  sessen.is_hosted = True

  sessen._start_exit_watcher()

  if strict_mode:
    code = sessen.get_file(ext_path)
    ext_path = ''
    preflight.enable_all_safeguards()
  else:
    sys_path = os.environ.get('SESSEN_SYS_PATH')
    preflight.enable_default_safeguards()
    if sys_path:
      sys.path.append(sys_path)
      os.chdir(sys_path)

  os.environ['PYTHONBREAKPOINT'] = breakpoint_handler
  os.environ['TEMP'] = temp_dir
  os.environ['TMPDIR'] = temp_dir

  if strict_mode:
    sessen.import_from_code(code, name)
  else:
    sessen.import_from_path(ext_path, name)

  if sessen._should_wait_for_exit_event:
    sessen.exit_event.wait()

if __name__ == '__main__':
  main()
