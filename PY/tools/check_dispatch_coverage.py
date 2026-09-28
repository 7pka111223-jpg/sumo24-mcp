import ast, re, sys
src = open('PY/server.py', encoding='utf-8').read()
tree = ast.parse(src)
# registered = the `name=` kwarg of types.Tool(...) calls ONLY - a regex over `name="..."`
# also matches inputSchema property names (e.g. "variable") and gives false positives.
reg = {k.value.value for x in ast.walk(tree)
       if isinstance(x, ast.Call) and getattr(x.func, 'attr', '') == 'Tool'
       for k in x.keywords
       if k.arg == 'name' and isinstance(k.value, ast.Constant)}
disp = set(re.findall(r'if name == "([a-z0-9_]+)"', src))
print('registered:', len(reg), '| dispatched:', len(disp))
print('registered, never dispatched:', sorted(reg - disp) or 'none')
print('dispatched, never registered:', sorted(disp - reg) or 'none')
