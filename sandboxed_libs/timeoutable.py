import os, time, threading, logging

DEFAULT_TIMEOUT = 5*60

class TimeoutableResource(object):  
  def __init__(self, timeout=DEFAULT_TIMEOUT):
    self._timeout_offset = timeout
    self._usage_count = 0
    self._lock = threading.Lock()
    self.instance = None

  def __enter__(self):
    with self._lock:
      self._timeout = time.time() + self._timeout_offset
      self._usage_count += 1
      if self.instance:
        return self.instance
      else:
        self.instance = self.create()
        threading.Thread(target=self._timeout_worker, args=()).start()
        return self.instance

  def __exit__(self, etype, evalue, traceback):
    with self._lock:
      self._timeout = time.time() + self._timeout_offset
      self._usage_count -= 1

  def _timeout_worker(self):
    while True:
      try:
        tdiff = self._timeout - time.time()
        if tdiff > 0:
          time.sleep(tdiff)
        with self._lock:
          if time.time() >= self._timeout:
            if self._usage_count == 0:
              self.flush_and_destroy()
              self.instance = None
              self._timeout = None
            else:
              self._timeout = time.time() + self._timeout_offset
      except TypeError:
        return

  def create(self):
    raise NotImplementedError()
  
  def flush_and_destroy(self):
    raise NotImplementedError()

class TimeoutableFile(TimeoutableResource):
  def __init__(self, path, mode):
     self.path = path
     self.mode = mode
     super().__init__()

  def create(self):
    return open(self.path, self.mode)
  
  def flush_and_destroy(self):
    self.instance.flush()
    self.instance.close()

class TimeoutableFileHandler(logging.StreamHandler):
  def __init__(self, filename, mode='a'):
    path = os.path.abspath(filename)
    self.file = TimeoutableFile(path, mode)
    self.lock = threading.Lock()
    self.stream = None
    logging.Handler.__init__(self)

  def close(self):
    pass

  def emit(self, record):
    with self.file as file:
      with self.lock:
        self.stream = file
        logging.StreamHandler.emit(self, record)
        self.stream = None
