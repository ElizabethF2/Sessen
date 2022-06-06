import sqlite3, time, threading, queue

class MultithreadedSqliteConnection(object):
  def __init__(self, path, timeout=5*60):
    self.path = path
    self.timeout = timeout
    self.queue = queue.Queue()
    self.thread = threading.Thread(target=self._worker, daemon=True)
    self.thread.start()

  def run(self, function):
    result = queue.Queue()
    self.queue.put((function, result))
    result, exception = result.get()
    if exception:
      raise exception
    return result

  def _worker(self):
    connection = None
    pending_commit = False
    while True:
      try:
        function, result = self.queue.get(timeout=self.timeout)
      except queue.Empty:
        if connection and pending_commit:
          connection.commit()
          connection.execute('PRAGMA optimize')
          pending_commit = False
        continue

      if not connection:
        connection = sqlite3.connect(self.path)
        connection.execute('PRAGMA temp_store = MEMORY')

      pending_commit = True
      res, exception = None, None
      try:
        res = function(connection)
      except Exception as ex:
        exception = ex

      result.put((res, exception))

def connect(path, timeout=5*60):
  return MultithreadedSqliteConnection(path, timeout)
