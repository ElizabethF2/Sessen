import os, shlex

def bool_string_to_bool(b, default=False):
  b = b.lower()
  if b in ('true', 'yes', 'on'):
    return True
  if b in ('false', 'no', 'off'):
    return False
  try:
    return bool(float(b))
  except ValueError:
    pass
  return default

def _load_raw(path):
  try:
    with open(path, 'r') as f:
      return list(f)
  except FileNotFoundError:
    pass
  try:
    with open(os.path.join(__file__, path), 'r') as f:
      return list(f)
  except FileNotFoundError:
    pass
  return []

def load(path='config.txt'):
  global _cached_config
  try:
    return _cached_config
  except NameError:
    config = {}
    for line in _load_raw(path):
      try:
        key = line.split()[0]
        value = line[len(key):].strip()
        config[key] = value
      except IndexError:
        pass
    _cached_config = config
    return config

def get(key, default=None):
  config = load()
  try:
    return config[key]
  except KeyError:
    if default is not None:
      return default
    raise

def get_int(key, default=None):
  try:
    return int(get(key, default=default))
  except ValueError:
    return default

def get_float(key, default=None):
  try:
    return float(get(key, default=default))
  except ValueError:
    return default

def get_bool(key, default=False):
  value = get(key, default=default)
  try:
    return bool_string_to_bool(value)
  except AttributeError:
    return value

def get_list(key, default=[]):
  value = get(key, default=default)
  if value == default:
    return value
  return shlex.split(value)
