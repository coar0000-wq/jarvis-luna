"""Wait for enough free RAM without touching other processes, then run smoke once."""
import ctypes, pathlib, subprocess, time, json, sys
ROOT=pathlib.Path(__file__).resolve().parent
class Memory(ctypes.Structure):
    _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),('page',ctypes.c_ulonglong),('availpage',ctypes.c_ulonglong),('virtual',ctypes.c_ulonglong),('availvirtual',ctypes.c_ulonglong),('reserved',ctypes.c_ulonglong)]
while True:
    m=Memory(); m.length=ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    (ROOT/'wait-state.json').write_text(json.dumps({'available_bytes':m.available,'required_bytes':2200000000,'state':'ready' if m.available>=2200000000 else 'waiting','unix_time':time.time()},indent=2))
    if m.available>=2200000000:
        with open(ROOT/'smoke.log','w') as log:
            result=subprocess.run([sys.executable,str(ROOT/'smoke.py')],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        sys.exit(result.returncode)
    time.sleep(20)
