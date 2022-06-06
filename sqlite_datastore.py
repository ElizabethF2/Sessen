import builtins
import multithreaded_sqlite, config

PAGE_SIZE = 100

db_path = config.get('datastore_path', default='datastore.db')
db_timeout = config.get_int('datastore_timeout', default=5*60)
db_connection = multithreaded_sqlite.connect(db_path, db_timeout)

def _init(connection):
  cur = connection.execute('create table if not exists datastore (key BLOB PRIMARY KEY, value BLOB)')
db_connection.run(_init)


def get(path):
  def f(connection):
    cur = connection.execute('SELECT value FROM datastore WHERE key=(?)', (path,))
    r = cur.fetchone()
    cur.close()
    if r is None:
      raise KeyError(path)
    return r[0]
  return db_connection.run(f)

  
def set(path, value):
  def f(connection):
    with connection:
      cur = connection.execute('INSERT OR REPLACE INTO datastore VALUES (?,?)', (path, value))
      cur.close()
  return db_connection.run(f)


def delete(path):
  def f(connection):
    with connection:
      cur = connection.execute('DELETE FROM datastore WHERE key=(?)', (path,))
      cur.close()
      if cur.rowcount == 0:
        raise KeyError(path)
  return db_connection.run(f)


def keys(path, page):
  def f(connection):
    results = builtins.set()
    limit = PAGE_SIZE
    offset = page*limit
    cur = connection.execute('SELECT key from datastore WHERE key LIKE (?) LIMIT (?), (?)', (path+'%',offset,limit))
    r = [i[0] for i in cur.fetchall()]
    cur.close()
    return r
  return db_connection.run(f)


def test_and_set(path, value):
  def f(connection):
    old_level = connection.isolation_level
    connection.isolation_level = 'EXCLUSIVE'
    try:
      cur = connection.execute('BEGIN EXCLUSIVE')
      cur.execute('SELECT value FROM datastore WHERE key=(?)', (path,))
      r = cur.fetchone()
      cur.execute('INSERT OR REPLACE INTO datastore VALUES (?,?)', (path, value))
      connection.commit()
    except Exception as ex:
      connection.rollback()
      raise ex
    finally:
      connection.isolation_level = old_level
      cur.close()
    if r is None:
      raise KeyError(path)
    return r[0]
  return db_connection.run(f)
