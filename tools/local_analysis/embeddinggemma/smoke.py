"""Real pinned EmbeddingGemma 2 smoke test; local only, no remote code."""
import os, pathlib, json, time, sys, traceback
import importlib.metadata as im
ROOT=pathlib.Path(__file__).resolve().parent
START_TIME=time.perf_counter()
os.environ['HF_HOME']=str(ROOT/'hf-cache')
os.environ['HF_HUB_OFFLINE']='1'
os.environ['TRANSFORMERS_OFFLINE']='1'
os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
os.environ['TOKENIZERS_PARALLELISM']='false'
os.environ['TORCH_HOME']=str(ROOT/'torch-cache')
os.environ['OMP_NUM_THREADS']='2'
os.environ['MKL_NUM_THREADS']='2'
import torch
import numpy as np
import psutil
from sentence_transformers import SentenceTransformer
import threading
p=psutil.Process()
running=True
peak=[p.memory_info().rss]
def monitor():
    while running:
        peak[0]=max(peak[0],p.memory_info().rss)
        time.sleep(.1)
threading.Thread(target=monitor,daemon=True).start()
torch.set_num_threads(2)
native_bf16=bool(getattr(torch.cpu,'_is_avx512_bf16_supported',lambda:False)())
# BF16 is model-supported even without hardware acceleration. Software BF16
# avoids FP16 (forbidden by the model card) and halves resident weight storage.
dtype=torch.bfloat16
if os.name == 'nt':
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
report={'model_id':'google/embeddinggemma-2','revision':json.loads((ROOT/'model-api.json').read_text())['sha'],'python':sys.version,'versions':{k:im.version(k) for k in ['torch','torchvision','transformers','sentence-transformers','numpy','safetensors','psutil','pillow']},'device':'cpu','dtype':str(dtype),'cpu_capability':torch.backends.cpu.get_cpu_capability(),'native_cpu_bf16':native_bf16,'trust_remote_code':False,'local_files_only':True,'memory_available_before_bytes':psutil.virtual_memory().available,'fixtures':{},'results':{},'status':'running'}
(ROOT/'evidence.json').write_text(json.dumps(report,indent=2))
try:
    print('Loading text-only model',dtype,'available RAM',report['memory_available_before_bytes'],flush=True)
    # Windows can page inactive memory. Require both real physical headroom and
    # substantial remaining commit capacity; never change system paging settings.
    import ctypes
    class MemoryStatus(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(name,ctypes.c_ulonglong) for name in ['total_phys','avail_phys','total_pagefile','avail_pagefile','total_virtual','avail_virtual','avail_extended']]
    memory=MemoryStatus(); memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise RuntimeError('Unable to verify Windows memory capacity')
    report['memory_available_commit_bytes']=memory.avail_pagefile
    report['memory_policy']='BF16/software allowed; physical >=512MiB, remaining commit >=3GiB; batch1, max256 tokens, 2 threads, below-normal priority; no system changes'
    if memory.avail_phys < 512*1024**2 or memory.avail_pagefile < 3*1024**3:
        raise RuntimeError(f'Insufficient safe memory headroom: physical={memory.avail_phys}, commit={memory.avail_pagefile}')
    model=SentenceTransformer(str(ROOT/'model'),device='cpu',trust_remote_code=False,local_files_only=True,config_kwargs={'vision_config':None,'audio_config':None},model_kwargs={'torch_dtype':dtype,'attn_implementation':'eager'})
    model.max_seq_length=256
    report['parameter_count']=sum(v.numel() for v in model.parameters())
    print('Loaded parameter count',report['parameter_count'],flush=True)
    suites={
      'text':{'query':'How can I stop water leaking from a kitchen faucet?','prompt':'SearchQuery','expected_top1':0,'documents':['Replace the worn rubber washer inside the leaking kitchen tap, then tighten the faucet and test for drips.','To bake bread, knead flour and yeast, let the dough rise, and bake it in a hot oven.','A lunar eclipse occurs when Earth blocks sunlight from reaching the Moon.']},
      'code':{'query':'Find a Python function that removes duplicates from a list while keeping the original order.','prompt':'CodeRetrieval','expected_top1':0,'documents':['def unique_in_order(items):\n    seen = set()\n    result = []\n    for item in items:\n        if item not in seen:\n            seen.add(item)\n            result.append(item)\n    return result','def factorial(n):\n    return 1 if n < 2 else n * factorial(n - 1)','def celsius_to_fahrenheit(c):\n    return c * 9 / 5 + 32']}}
    for name,fixture in suites.items():
        report['fixtures'][name]=fixture
        report['results'][name]={}
        for dim in [768,256]:
            q=model.encode([fixture['query']],prompt_name=fixture['prompt'],batch_size=1,normalize_embeddings=True,truncate_dim=dim,show_progress_bar=False,convert_to_numpy=True)
            d=model.encode(fixture['documents'],prompt_name='Document',batch_size=1,normalize_embeddings=True,truncate_dim=dim,show_progress_bar=False,convert_to_numpy=True)
            q=q.astype('float32')
            d=d.astype('float32')
            # BF16 normalization introduces rounding; renormalize exported FP32
            # vectors so dot products are true cosine scores at both dimensions.
            q=q/np.linalg.norm(q,axis=1,keepdims=True)
            d=d/np.linalg.norm(d,axis=1,keepdims=True)
            scores=(q@d.T)[0]
            rank=np.argsort(-scores).tolist()
            finite=bool(np.isfinite(q).all() and np.isfinite(d).all())
            norms=np.linalg.norm(np.concatenate([q,d]),axis=1)
            passed=finite and q.shape==(1,dim) and d.shape==(3,dim) and np.allclose(norms,1,atol=1e-6) and rank[0]==fixture['expected_top1']
            item={'query_shape':list(q.shape),'document_shape':list(d.shape),'all_finite':finite,'l2_norms':norms.tolist(),'cosine_scores':scores.tolist(),'ranking':rank,'top1_correct':rank[0]==fixture['expected_top1'],'passed':bool(passed)}
            report['results'][name][str(dim)]=item
            np.savez(ROOT/f'embeddings_{name}_{dim}.npz',query=q,documents=d)
            print(name,dim,json.dumps(item),flush=True)
    report['status']='passed' if all(x['passed'] for r in report['results'].values() for x in r.values()) else 'failed'
    report['optional_vision']='Scope of this script: text/code only. See vision_smoke.py for the separate image/text suite.'
    report['normalization']='encode(normalize_embeddings=True), then FP32 L2 renormalization after BF16-to-FP32 export'
except Exception:
    report['status']='error'
    report['error']=traceback.format_exc()
    print(report['error'],flush=True)
finally:
    running=False
    report['runtime_seconds_including_imports']=time.perf_counter()-START_TIME
    report['peak_process_rss_bytes']=peak[0]
    report['memory_available_after_bytes']=psutil.virtual_memory().available
    (ROOT/'evidence.json').write_text(json.dumps(report,indent=2))
print('FINAL_STATUS',report['status'],flush=True)
if report['status']!='passed': sys.exit(1)
