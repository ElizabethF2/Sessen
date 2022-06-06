import sys, os, time, argparse, threading, logging, ctypes
sys.path.append(os.path.join(os.path.dirname(__file__), 'sandboxed_libs'))
import http_server, api_server, timeoutable, extension_manager, config, permissions

def sleep_until_interupt():
  MAX_SLEEP = 2**32//1000
  try:
    while True:
      time.sleep(MAX_SLEEP)
  except KeyboardInterrupt:
    pass

def parse_custom_args(unknown):
  args = {}
  for idx, arg in enumerate(sys.argv):
    if len(arg) > 1 and arg[0] == '@':
      try:
        value = sys.argv[idx+1]
        args[arg[1:]] = value if value[0]!='@' else None
      except IndexError:
        args[arg[1:]] = None
  return args

def setup_logger():
  logger = logging.getLogger('sessen')
  logger.addHandler(timeoutable.TimeoutableFileHandler('log.log'))
  log_level = config.get('log_level', default='INFO')
  try:
    log_level = int(log_level)
  except ValueError:
    pass
  logger.setLevel(log_level)

def is_admin():
  try:
    return (os.getuid() == 0)
  except AttributeError:
    return (ctypes.windll.shell32.IsUserAnAdmin() != 0)

def main():
  parser = argparse.ArgumentParser(description='Sessen')
  parser.add_argument('--run', '-r', help='Exclusively run the extension whose name is passed to this argument')
  parser.add_argument('--extensions_folder', '-e', help='Specify a different path for the Extensions folder')
  parser.add_argument('--permissions_folder', '-a', help='Specify a different path for the Permissions folder')
  parser.add_argument('--config', '-c', help='Specify a different path for the config file')
  parser.add_argument('--no-server', '-n', help='Disable the HTTP server', action='store_true')
  parser.add_argument('--bind', '-b', help='Specify which address the HTTP server should bind to')
  parser.add_argument('--port', '-p', help='Specify which port the HTTP server should use')
  parser.add_argument('--force-sandbox', '-f', help='Force all extensions to run sandboxed', action='store_true')
  args, unknown = parser.parse_known_args()
  extension_manager.custom_args = parse_custom_args(unknown)

  if is_admin():
    import warnings
    warnings.warn('Running as an admin/root account. Re-run using a normal user account for improved security.')

  if args.config:
    config.load(args.config)

  setup_logger()

  if args.extensions_folder:
    extension_manager.extensions_folder = args.extensions_folder
  if args.permissions_folder:
    permissions.permissions_folder = args.permissions_folder
  if args.run:
    extension_manager.start_extension(args.run, exclusive=True, force_sandbox=args.force_sandbox)
  else:
    extension_manager.start_autostart_extensions(force_sandbox=args.force_sandbox)
  print('Press Ctrl+C to exit')
  if not args.no_server:
    http_server.serve_forever(bind=args.bind, port=args.port)
  else:
    sleep_until_interupt()
  print('Stopping Extensions...')
  extension_manager.stop_extensions()

if __name__ == '__main__':
  main()
