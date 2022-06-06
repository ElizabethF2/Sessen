import os, platform, shutil
import config

def get_temp_dir_and_cleanup_default():
  try:
    return os.path.expandvars(config.get('temp_dir')), False
  except KeyError:
    pass
  if not platform.system() == 'Windows' and os.path.isdir('/tmp'):
    return '/tmp', False
  return os.path.join(os.path.dirname(__file__), 'temp'), True

def get_temp_dir():
  temp_dir, _ = get_temp_dir_and_cleanup_default()
  return temp_dir

def get_or_create_temp_dir():
  temp_dir = get_temp_dir()
  try:
    os.makedirs(temp_dir)
  except FileExistsError:
    pass
  return temp_dir

def cleanup_temp_dir():
  temp_dir, default_do_cleanup = get_temp_dir_and_cleanup_default()
  do_cleanup = config.get_bool('delete_temp_dir_at_exit', default=default_do_cleanup)
  if do_cleanup:
    try:
      shutil.rmtree(temp_dir)
    except FileNotFoundError:
      pass
