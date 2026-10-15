"""LAN-only discovery with fresh challenges and authenticated host responses."""
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import threading

PORT = 7789


def signature(token: str, nonce: str, port: int, host: str) -> str:
  return hmac.new(token.encode(),f'external-lanes-v1:{nonce}:{host}:{port}'.encode(),hashlib.sha256).hexdigest()


def reply(data: bytes, token: str, port: int, host: str = '127.0.0.1') -> bytes:
  value=json.loads(data)
  nonce=value['nonce']
  if value.get('version') != 1 or not isinstance(nonce,str) or len(nonce)!=32 or any(c not in '0123456789abcdef' for c in nonce):
    raise ValueError('invalid challenge')
  return json.dumps({'version':1,'nonce':nonce,'port':port,'host':host,'signature':signature(token,nonce,port,host)}).encode()


def verify_reply(data: bytes, nonce: str, token: str, address: str) -> str:
  value=json.loads(data)
  port=value.get('port')
  ip=ipaddress.ip_address(address)
  if (value.get('version')!=1 or value.get('nonce')!=nonce or value.get('host')!=address or type(port) is not int or not 1<=port<=65535 or
      not (ip.is_private or ip.is_loopback) or ip.is_multicast or ip.is_unspecified or
      not isinstance(value.get('signature'),str) or not hmac.compare_digest(value['signature'],signature(token,nonce,port,address))):
    raise ValueError('untrusted host response')
  return f'http://{address}:{port}'


def discover(token: str, *, target: str = '255.255.255.255', port: int = PORT) -> str | None:
  nonce=secrets.token_hex(16)
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_BROADCAST,1)
    sock.settimeout(0.25)
    sock.sendto(json.dumps({'version':1,'nonce':nonce}).encode(),(target,port))
    for _ in range(4):
      try:
        data,addr=sock.recvfrom(512)
        return verify_reply(data,nonce,token,addr[0])
      except (ValueError,KeyError,TypeError):
        continue
      except socket.timeout:
        break
  return None


class DiscoveryResponder:
  def __init__(self,token: str,http_port: int,*,bind: str='0.0.0.0',port: int=PORT):
    self.token,self.http_port=token,http_port
    self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    self.sock.bind((bind,port));self.sock.settimeout(0.5)
    self.stop=threading.Event()
    self.thread=threading.Thread(target=self.run,daemon=True)

  def run(self):
    while not self.stop.is_set():
      try:
        data,address=self.sock.recvfrom(256)
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as route:
          route.connect(address)
          host=route.getsockname()[0]
        self.sock.sendto(reply(data,self.token,self.http_port,host),address)
      except (ValueError,KeyError,TypeError,socket.timeout):
        continue
      except OSError:
        break

  def __enter__(self):
    self.thread.start();return self

  def __exit__(self,*_args):
    self.stop.set();self.sock.close();self.thread.join(1)
