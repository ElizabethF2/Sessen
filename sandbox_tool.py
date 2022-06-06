import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), 'sandboxed_libs'))
import sandbox, extension_manager, tempdir

def get_input():
  return input('> ').lower()[:1]

def view_paths():
  paths = sandbox.get_python_paths() + extension_manager.SANDBOX_SCRIPTS + [tempdir.get_temp_dir()]
  print('Sandboxed extensions will have read-only access to the following paths:\n')
  for path in paths:
    print(path)
  print('')
  print('If any of these paths contain files you don\'t want extensions to be able to see')
  print('or if the paths themselves contain information you don\'t want extensions to')
  print('know (e.g. your username), consider moving the files and/or updating your')
  print('settings.')

def delete_sandboxes():
  print('Deleting sandboxes...')
  sandbox.delete_all_sandboxes()
  print('Sandboxes deleted.')

def main():
  has_delete = hasattr(sandbox, 'delete_all_sandboxes')

  print('Please select an option. The options available vary depending on your platform.')
  print('Press Ctrl + C at any time to quit.')
  print('1) View paths used by the sandbox')
  if has_delete:
    print('2) Delete all sandboxes')
  print('')

  inp = get_input()

  if inp == '1':
    view_paths()
  elif has_delete and inp == '2':
    delete_sandboxes()
  else:
    print('\nInvalid selection.')

if __name__ == '__main__':
  main()
