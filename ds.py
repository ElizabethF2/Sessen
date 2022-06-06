help_text = """
ds.py is a small utility for managing Sessen's datastore from a command line.

It supports the following commands:
  get       - retrieve and print a path
  set       - set a path to a string
  set_int   - set a path to an int
  set_float - set a path to a float
  del       - delete a path
  keys      - print all keys that start with a path
  delkeys   - delete all keys that start with a path
  help      - display this help text
  ?         - same as help

Here are some examples:
  ds.py get extensions/MyExtension/settings
  ds.py set extensions/MyExtension/password "foo bar"
  ds.py set_int extensions/MyExtension/age 92
  ds.py set_float extensions/MyExtension/rate 3.14
  ds.py del extensions/MyExtension/password
  ds.py key shared

ds.py key "" can be used to list every key
"""

def main():
  import sys
  sys.path.append('sandboxed_libs')
  import sessen
  sessen.bypass_path_validation_for_non_extensions()

  if len(sys.argv) < 2 or sys.argv[1] in ('?', 'help'):
    print(help_text)
  elif sys.argv[1] == 'get':
    print(sessen.datastore[sys.argv[2]])
  elif sys.argv[1] == 'set':
    sessen.datastore[sys.argv[2]] = sys.argv[3]
  elif sys.argv[1] == 'set_int':
    sessen.datastore[sys.argv[2]] = int(sys.argv[3])
  elif sys.argv[1] == 'set_float':
    sessen.datastore[sys.argv[2]] = float(sys.argv[3])
  elif sys.argv[1] == 'del':
    del sessen.datastore[sys.argv[2]]
  elif sys.argv[1] == 'keys':
    for k in sessen.datastore.keys(sys.argv[2]):
      print(k)
  elif sys.argv[1] == 'delkeys':
    for k in sessen.datastore.keys(sys.argv[2]):
      del sessen.datastore[k]

if __name__ == '__main__':
  main()
