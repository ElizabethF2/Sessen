import sessen, os, traceback, inspect

PROMPT = '{file}:{line} SDB> '

console = sessen.ExtensionProxy('console')

def breakpoint():
  caller = inspect.currentframe().f_back
  prompt = PROMPT.format(
            path = caller.f_code.co_filename,
            file = os.path.basename(caller.f_code.co_filename),
            line = caller.f_lineno)
  while True:
    inp = console.input(prompt)
    if inp == 'c':
      return
    elif inp == 'w':
      console.print('\n'.join(traceback.format_stack()))
    elif inp == 'q':
      raise SystemExit()
    else:
      try:
        try:
          res = eval(inp, caller.f_globals, caller.f_locals)
        except SyntaxError:
          res = exec(inp, caller.f_globals, caller.f_locals)
        console.print(repr(res))
      except:
        console.print(traceback.format_exc())
