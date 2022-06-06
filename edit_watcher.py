import sys, os, subprocess, signal, ctypes, platform, threading, time, re

kernel32, inotify, watchdog = None, None, None
if hasattr(ctypes, 'windll') and hasattr(ctypes.windll.kernel32, 'FindFirstChangeNotificationW'):
  kernel32 = ctypes.windll.kernel32
else:
  try:
    import inotify.adapters
  except ModuleNotFoundError:
    import watchdog.observers, watchdog.events

FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_ATTRIBUTES = 0x00000004
FILE_NOTIFY_CHANGE_SIZE = 0x00000008
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
INVALID_HANDLE_VALUE = -1
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000

EVENTS_TO_WATCH = ['IN_CREATE', 'IN_MOVED_FROM', 'IN_MOVED_TO', 'IN_CREATE', 'IN_MODIFY', 'IN_DELETE']

stop_in_progress = False
sessen_proc = None
needs_restart = threading.Event()
observers = []

filter = re.compile(os.environ.get('EDIT_WATCHER_FILTER') or '.+\\.(py|txt)$')
paths = os.environ.get('EDIT_WATCHER_PATHS')
if paths:
  paths = paths.split(';' if platform.system() == 'Windows' else ':')
else:
  paths = ['Extensions', 'Permissions']
timeout = float(os.environ.get('EDIT_WATCHER_TIMEOUT') or 5)

try:
  STOP_SIGNAL = signal.CTRL_C_EVENT
except AttributeError:
  STOP_SIGNAL = signal.SIGINT

def start():
  global sessen_proc
  cmd = [sys.executable, os.path.join(os.path.dirname(__file__), 'main.py')] + sys.argv[1:]
  shell = False
  sessen_proc = subprocess.Popen(cmd, shell=shell)

def stop():
  global stop_in_progress
  stop_in_progress = True
  os.kill(sessen_proc.pid, STOP_SIGNAL)
  try:
    sessen_proc.wait()
  except KeyboardInterrupt:
    if platform.system() != 'Windows':
      raise
  stop_in_progress = False

def get_state(path):
  state = None
  try:
    with os.scandir(path) as it:
      for entry in it:
        if filter.match(entry.path):
          state = hash((state, entry.path, entry.stat().st_mtime))
  except FileNotFoundError:
    pass
  return state

def get_change_watcher(path):
  handle = kernel32.FindFirstChangeNotificationW(
    path,
    True,
    FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME | FILE_NOTIFY_CHANGE_ATTRIBUTES | FILE_NOTIFY_CHANGE_LAST_WRITE | FILE_NOTIFY_CHANGE_SIZE)
  if handle == INVALID_HANDLE_VALUE:
    raise ctypes.WinError()
  return handle

def wait_for_change(change_watcher):
  if kernel32.WaitForSingleObject(change_watcher, INFINITE) != WAIT_OBJECT_0:
    raise ctypes.WinError()
  if not kernel32.FindNextChangeNotification(change_watcher):
    raise ctypes.WinError()

if watchdog:
  class WatchdogEventHandler(watchdog.events.FileSystemEventHandler):
    def on_any_event(event):
      if filter.match(event.dest_path if hasattr(event, 'dest_path') else event.src_path):
        needs_restart.set()

def restarter():
  start()
  while True:
    needs_restart.wait()
    while True:
      if not needs_restart.wait(timeout=timeout):
        break
    stop()
    needs_restart.clear()
    start()

def watcher(path):
  if kernel32:
    state = get_state(path)
    change_watcher = get_change_watcher(path)
    while True:
      wait_for_change(change_watcher)
      new_state = get_state(path)
      if new_state != state:
        state = new_state
        needs_restart.set()
  elif inotify:
    notifier = inotify.adapters.InotifyTree(path)
    for _, type_names, dir, file in notifier.event_gen(yield_nones=False):
      if any((i in EVENTS_TO_WATCH for i in type_names)):
        path = dir if not file else os.path.join(dir, file)
        if filter.match(path):
          needs_restart.set()
  else:
    observer = watchdog.observers.Observer()
    observer.schedule(WatchdogEventHandler, path, recursive=True)
    observer.start()
    observers.append(observer)

def main():
  threading.Thread(target=restarter, daemon=True).start()
  for path in paths:
    threading.Thread(target=watcher, args=(path,), daemon=True).start()

  MAX_SLEEP = (2**32)//1000
  while True:
    try:
      time.sleep(MAX_SLEEP)
    except KeyboardInterrupt:
      if platform.system() != 'Windows' or not stop_in_progress:
        for observer in observers:
          observer.stop()
        for observer in observers:
          observer.join()
        if sessen_proc:
          sessen_proc.wait()
        return

if __name__ == '__main__':
  main()
