import os
import config, extension_manager

_cache = {}
permisions_folder = os.path.join(os.path.dirname(__file__), 'Permissions')

def get_path_by_name(name):
  return os.path.join(permisions_folder, name+'.txt')

def load(name):
  while True:
    try:
      with open(get_path_by_name(name), 'r') as f:
        return f.read()
    except FileNotFoundError:
      try:
        os.mkdir(permisions_folder)
      except FileExistsError:
        pass
      try:
        data = _default_permissions.replace('$EXTENSIONNAME', name)
        with open(get_path_by_name(name), 'x') as f:
          f.write(data)
        return data
      except FileExistsError:
        pass

def clean_datastore_path(p):
  if p == '':
    return ''
  if p[0] != ' ':
    return None
  if p[-1] != '/':
    p += '/'
  return p[1:]

def clean_file_path(p):
  if len(p) < 1:
    return None
  p = os.path.expandvars(p)
  if os.path.abspath(p) != p:
    return None
  if not os.path.isfile(p) and p[-len(os.path.sep):] != os.path.sep:
    p += os.path.sep
  return p

def parse(name, data):
  use_sandbox = True
  strict_mode = config.get_bool('strict_mode')
  allowed_urls = []
  blocked_urls = []
  allowed_extensions = []
  allowed_read_datastore = []
  allowed_write_datastore = ['shared/', 'extensions/'+name+'/']
  allowed_read_files = []
  allowed_write_files = []
  allowed_write_files_ensure_exists = []

  ext_path, sys_path = extension_manager.get_extension_paths(name)
  if sys_path:
    allowed_write_files.append(sys_path)
  else:
    allowed_write_files.append(ext_path)

  for line in data.splitlines():
    line = line.strip()
    if line.startswith('allow_url '):
      allowed_urls.append(line[10:])
    elif line.startswith('block_url '):
      blocked_urls.append(line[10:])
    elif line.startswith('use_sandbox '):
      use_sandbox = config.bool_string_to_bool(line[12:], default=True)
    elif line.startswith('strict_mode '):
      strict_mode = config.bool_string_to_bool(line[12:], default=False)
    elif line.startswith('allow_extension '):
      allowed_extensions.append(line[16:])
    elif line.startswith('allow_datastore_write'):
      path = clean_datastore_path(line[21:])
      if path is not None:
        allowed_write_datastore.append(path)
    elif line.startswith('allow_datastore'):
      path = clean_datastore_path(line[15:])
      if path is not None:
        allowed_read_datastore.append(path)
    elif line.startswith('allow_file '):
      path = clean_file_path(line[11:])
      if path is not None:
        allowed_read_files.append(path)
    elif line.startswith('allow_file_write '):
      path = clean_file_path(line[17:])
      if path is not None:
        allowed_write_files.append(path)
    elif line.startswith('allow_file_write_ensure_exists '):
      path = clean_file_path(line[31:])
      if path is not None:
        allowed_write_files_ensure_exists.append(path)
  return {
          'allowed_urls': allowed_urls,
          'blocked_urls': blocked_urls,
          'use_sandbox': use_sandbox,
          'strict_mode': strict_mode,
          'allowed_extensions': allowed_extensions,
          'allowed_read_datastore': allowed_read_datastore,
          'allowed_write_datastore': allowed_write_datastore,
          'allowed_read_files': allowed_read_files,
          'allowed_write_files': allowed_write_files,
          'allowed_write_files_ensure_exists': allowed_write_files_ensure_exists,
         }

def get(name):
  try:
    return _cache[name]
  except KeyError:
    data = load(name)
    permissions = parse(name, data)
    _cache[name] = permissions
    return permissions

def purge_cache(name=None):
  if name:
    del _cache[name]
  else:
    _cache.clear()

_default_permissions = """
# Edit this file to set permissions for $EXTENSIONNAME
# Below are examples of permissions that can be set.
# All permissions are case-sensitive and should be lower case.
# Lines that do not start with a valid permission will be ignored.
#
# allow_url http://example.com/.+
# Allows web requests to any url matching the regex pattern http://example.com/.+
#
# block_url http://example.com/.+
# Block web requests to any url matching the regex pattern http://example.com/.+
# If a request has a url that matches both a blocked and allowed pattern, it will be blocked.
#
# allow_datastore extension/SomeOtherExtension
# Allows read-only access to extension/SomeOtherExtension
#
# allow_datastore
# Allows read-only access to all datastore paths
#
# allow_datastore_write extension/SomeOtherExtension
# Allows reading and writing to extension/SomeOtherExtension
#
# allow_datastore_write
# Allows reading and writing to all datastore paths
#
# allow_file /example
# Allows read-only access to files and folders in /example. 
# The path must be an absolute path.
#
# allow_file_write /example
# Allows reading and writing files in /example.
# The path must be an absolute path.
#
# allow_file_write_ensure_exists /example
# Allows reading and writing files in /example.
# The path will be created if it does not exist. 
# This ensures that files in the given path will persist after the sandbox is closed which
# is not true of paths created in the sandbox.
# The path must be an absolute path.
#
# allow_extension AnotherExtensionName
# Allow this extension to talk to AnotherExtensionName
#
# use_sandbox yes
# Run the extension in the sandbox. If no value is supplied, the default value is yes.
# The value of this permission is case-insensitive and can be yes, no, true, false, 1 or 0
#
# strict_mode yes
# Run the extension using strict mode. If no value is supplied, the default value is no.
# Strict mode only affects sandboxed extensions. It places further restrictions on extensions
# but will prevent most extensions not specifically designed to run in strict mode from working.
# The value of this permission is case-insensitive and can be yes, no, true, false, 1 or 0

"""
