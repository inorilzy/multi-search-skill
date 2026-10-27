# HISTORICAL EVIDENCE — DO NOT RUN.
#
# This script was used to check the proxy trust boundary (t18, 2026-10-22)
# against the code of that time. It only applies to code before ticket 01 of
# the fake-IP/DNS cleanup: it imports `_is_trusted_proxy_hop`, which has since
# been removed, so it fails with ImportError on the current code. The original
# logic is kept unchanged for the record; do not treat it as a current test.
import sys, socket, threading, http.server, json, urllib.request
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from multi_search_mcp.src.support.http import urlopen_retry, _is_trusted_proxy_hop
from multi_search_mcp.src.support.url_security import UrlSecurityError
class Handler(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  self.server.seen.append(self.path)
  if self.path.endswith('/redirect'):
   self.send_response(302); self.send_header('Location','http://127.0.0.1/private'); self.end_headers()
  else:
   self.send_response(200); self.send_header('Content-Length','2'); self.end_headers(); self.wfile.write(b'ok')
 def log_message(self,*a): pass
rows=[]
for host in ['localhost','127.0.0.1','::1']:
 class Server(http.server.ThreadingHTTPServer): address_family=socket.AF_INET6 if host=='::1' else socket.AF_INET
 try: server=Server(('::1' if host=='::1' else '127.0.0.1',0),Handler)
 except OSError as e: rows.append({'host':host,'unavailable':str(e)}); continue
 server.seen=[]; thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
 port=server.server_port; endpoint=f'http://[{host}]:{port}' if ':' in host else f'http://{host}:{port}'
 try:
  with patch('urllib.request.getproxies',return_value={}),patch('urllib.request.proxy_bypass',return_value=False):
   # .invalid origin never resolved: only the explicitly selected local proxy is dialled.
   with urlopen_retry('http://synthetic.invalid/page',2,extra_handlers=(urllib.request.ProxyHandler({'http':endpoint}),)) as r: assert r.read()==b'ok'
   for target in [f'http://127.0.0.1:{port}/','http://10.0.0.8/']:
    try: urlopen_retry(target,1,extra_handlers=(urllib.request.ProxyHandler({}),)); raise AssertionError('direct target allowed')
    except UrlSecurityError: pass
   try: urlopen_retry('http://synthetic.invalid/redirect',2,extra_handlers=(urllib.request.ProxyHandler({'http':endpoint}),)); raise AssertionError('redirect allowed')
   except UrlSecurityError: pass
   request=urllib.request.Request('http://synthetic.invalid/'); request.set_proxy(endpoint.split('://')[1],'http')
   assert not _is_trusted_proxy_hop(request,host,port+1)
   for u in [f'http://127.0.0.1:{port}/http://evil/',f'http://localhost:{port}/?selector=http://x','http://10.0.0.8/']:
    q=urllib.request.Request(u); assert not q.has_proxy() and not _is_trusted_proxy_hop(q,q.host,port)
  rows.append({'host':host,'proxy_ok':True,'direct_private_denied':True,'redirect_denied':True,'wrong_port_denied':True,'seen':server.seen})
 finally: server.shutdown();server.server_close();thread.join()
print(json.dumps(rows,indent=2))
