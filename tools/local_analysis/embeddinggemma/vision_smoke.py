"""One bounded offline text/image EmbeddingGemma 2 test on authored PNGs only."""
import os, pathlib, json, time, sys, traceback, ctypes, hashlib, threading
import importlib.metadata as im
ROOT=pathlib.Path(__file__).resolve().parent
START=time.perf_counter()
REVISION='914f7f89142e33e77833254d9c9b90c3cef7303b'
for key in ['PIP_PREFIX','PIP_TARGET','PYTHONPATH','VIRTUAL_ENV']:
    os.environ.pop(key,None)
os.environ.update(HF_HOME=str(ROOT/'hf-cache'),TORCH_HOME=str(ROOT/'torch-cache'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
report={'model_id':'google/embeddinggemma-2','revision':REVISION,'status':'running','device':'cpu','dtype':'float32','dimension':768,'config_kwargs':{'audio_config':None},'vision_enabled':True,'trust_remote_code':False,'local_files_only':True,'modalities_executed':[],'audio_video_tested':False,'fixtures':[],'results':{},'memory_policy':'Single authorized FP32 CPU retry: before model load physical>=2.5GiB and remaining commit>=6GiB; batch1, two threads, below-normal priority; no system changes.'}
running=False
peak=[0]
(ROOT/'vision-evidence.json').write_text(json.dumps(report,indent=2))
try:
    import torch
    import numpy as np
    import psutil
    from PIL import Image, ImageDraw
    from sentence_transformers import SentenceTransformer
    p=psutil.Process()
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    torch.set_num_threads(2)
    report['versions']={k:im.version(k) for k in ['torch','torchvision','transformers','sentence-transformers','numpy','psutil','pillow']}
    report['native_cpu_bf16']=bool(getattr(torch.cpu,'_is_avx512_bf16_supported',lambda:False)())
    report['cpu_capability']=torch.backends.cpu.get_cpu_capability()
    peak[0]=p.memory_info().rss
    running=True
    def monitor():
        while running:
            peak[0]=max(peak[0],p.memory_info().rss)
            time.sleep(.1)
    threading.Thread(target=monitor,daemon=True).start()
    metadata=json.loads((ROOT/'model-api.json').read_text())
    if metadata.get('id')!=report['model_id'] or metadata.get('sha')!=REVISION:
        raise RuntimeError('Unexpected pinned model provenance')
    definitions=[('red-square','a red square on a white background'),('blue-circle','a blue circle on a white background'),('green-triangle','a green triangle on a white background')]
    for name,text in definitions:
        image=Image.new('RGB',(256,256),'white')
        draw=ImageDraw.Draw(image)
        if name=='red-square': draw.rectangle((40,40,216,216),fill=(230,20,20))
        elif name=='blue-circle': draw.ellipse((40,40,216,216),fill=(20,50,230))
        else: draw.polygon([(128,32),(32,224),(224,224)],fill=(20,160,30))
        file=ROOT/f'vision-fixture-{name}.png'
        image.save(file)
        report['fixtures'].append({'id':name,'path':str(file),'description':text,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'size':[256,256],'authored_locally':True})
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(k,ctypes.c_ulonglong) for k in ['total_phys','avail_phys','total_pagefile','avail_pagefile','total_virtual','avail_virtual','avail_extended']]
    m=Memory(); m.length=ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise RuntimeError('Unable to verify Windows memory capacity')
    report['memory_available_before_model_bytes']=m.avail_phys
    report['memory_available_commit_before_model_bytes']=m.avail_pagefile
    if m.avail_phys < int(2.5*1024**3) or m.avail_pagefile < 6*1024**3:
        raise RuntimeError(f'Insufficient safe memory headroom: physical={m.avail_phys}, commit={m.avail_pagefile}')
    print('Loading local text+vision model, audio disabled, RAM',m.avail_phys,'commit',m.avail_pagefile,flush=True)
    model=SentenceTransformer(str(ROOT/'model'),device='cpu',trust_remote_code=False,local_files_only=True,config_kwargs={'audio_config':None},model_kwargs={'torch_dtype':torch.float32,'attn_implementation':'eager'})
    # 280 default image tokens plus structural tokens fit without image truncation.
    model.max_seq_length=1024
    report['max_sequence_tokens']=model.max_seq_length
    report['parameter_count']=sum(v.numel() for v in model.parameters())
    print('Loaded parameter count',report['parameter_count'],flush=True)
    def normalized(arr):
        arr=np.asarray(arr,dtype='float32')
        if not np.isfinite(arr).all(): raise RuntimeError('Non-finite embedding')
        norms=np.linalg.norm(arr,axis=-1,keepdims=True)
        if not (norms>0).all(): raise RuntimeError('Zero embedding')
        return arr/norms
    images=[]
    for fixture in report['fixtures']:
        # Official modality dictionary; do not apply any text task prompt to images.
        emb=model.encode({'image':fixture['path']},batch_size=1,normalize_embeddings=True,truncate_dim=768,show_progress_bar=False,convert_to_numpy=True)
        emb=normalized(emb).reshape(1,-1)
        if emb.shape!=(1,768): raise RuntimeError(f'Wrong image embedding shape: {emb.shape}')
        images.append(emb[0])
        print('Embedded image',fixture['id'],flush=True)
    image_vectors=np.stack(images)
    report['modalities_executed']=['image']
    descriptions=[item['description'] for item in report['fixtures']]
    query_vectors=normalized(model.encode(descriptions,prompt_name='SearchQuery',batch_size=1,normalize_embeddings=True,truncate_dim=768,show_progress_bar=False,convert_to_numpy=True))
    document_vectors=normalized(model.encode(descriptions,prompt_name='Document',batch_size=1,normalize_embeddings=True,truncate_dim=768,show_progress_bar=False,convert_to_numpy=True))
    report['modalities_executed']=['image','text']
    arrays={'image':image_vectors,'query':query_vectors,'document_text':document_vectors}
    report['embedding_checks']={}
    shape_finite_norms_pass=True
    for name,arr in arrays.items():
        norms=np.linalg.norm(arr,axis=1)
        passed=arr.shape==(3,768) and bool(np.isfinite(arr).all()) and bool(np.allclose(norms,1,atol=1e-6))
        shape_finite_norms_pass=shape_finite_norms_pass and passed
        report['embedding_checks'][name]={'shape':list(arr.shape),'all_finite':bool(np.isfinite(arr).all()),'l2_norms':norms.tolist(),'passed':passed,'float32_bytes_sha256':hashlib.sha256(arr.tobytes()).hexdigest()}
    image_scores=query_vectors@image_vectors.T
    text_scores=query_vectors@document_vectors.T
    cross_pass=True
    text_pass=True
    for i,fixture in enumerate(report['fixtures']):
        ranks=np.argsort(-image_scores[i],kind='stable').tolist()
        text_ranks=np.argsort(-text_scores[i],kind='stable').tolist()
        cross_pass=cross_pass and ranks[0]==i
        text_pass=text_pass and text_ranks[0]==i
        item={'query':fixture['description'],'expected_image_id':fixture['id'],'cosine_scores_in_fixture_order':image_scores[i].tolist(),'image_ranked_ids':[report['fixtures'][j]['id'] for j in ranks],'crossmodal_top1_correct':ranks[0]==i,'text_control_cosine_scores':text_scores[i].tolist(),'text_control_ranked_ids':[report['fixtures'][j]['id'] for j in text_ranks],'text_control_top1_correct':text_ranks[0]==i}
        report['results'][fixture['id']]=item
        print(json.dumps(item),flush=True)
    report['crossmodal_top1_all_correct']=cross_pass
    report['text_control_top1_all_correct']=text_pass
    report['status']='passed' if shape_finite_norms_pass and cross_pass and text_pass else 'failed'
    report['normalization']='Official encode(normalize_embeddings=True), then FP32 L2 renormalization; cosine is FP32 dot product.'
except Exception:
    report['status']='error'
    report['error']=traceback.format_exc()
    print(report['error'],flush=True)
finally:
    running=False
    report['peak_process_rss_bytes']=peak[0]
    report['runtime_seconds_including_imports']=time.perf_counter()-START
    (ROOT/'vision-evidence.json').write_text(json.dumps(report,indent=2))
print('FINAL_STATUS',report['status'],flush=True)
if report['status']!='passed': sys.exit(1)
