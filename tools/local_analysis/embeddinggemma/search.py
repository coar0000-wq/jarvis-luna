"""Offline explicit-input EmbeddingGemma 2 retrieval. No file discovery or approval decisions."""
import argparse, os, pathlib, json, sys, hashlib, time, ctypes
ROOT=pathlib.Path(__file__).resolve().parent
REVISION='914f7f89142e33e77833254d9c9b90c3cef7303b'

def main():
    started=time.perf_counter()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',required=True)
    parser.add_argument('--documents-json',type=pathlib.Path,required=True)
    parser.add_argument('--dimension',type=int,choices=[768,256],default=256)
    parser.add_argument('--code',action='store_true')
    parser.add_argument('--top-k',type=int,default=3)
    args=parser.parse_args()
    if not 1 <= len(args.query.strip()) <= 1000:
        parser.error('query must contain 1..1000 characters')
    if not 1 <= args.top_k <= 10:
        parser.error('top-k must be 1..10')
    source=args.documents_json.resolve(strict=True)
    if source.stat().st_size > 4_000_000:
        parser.error('documents JSON must be at most 4MB')
    raw=source.read_bytes()
    docs=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(docs,list) or not 1 <= len(docs) <= 64:
        parser.error('documents must be a list of 1..64 {id,text} objects')
    ids=[]
    for doc in docs:
        if not isinstance(doc,dict) or not isinstance(doc.get('id'),str) or not 1 <= len(doc['id']) <= 128 or not isinstance(doc.get('text'),str) or not 1 <= len(doc['text']) <= 5000:
            parser.error('each document needs id string (1..128) and text string (1..5000)')
        ids.append(doc['id'])
    if len(set(ids))!=len(ids):
        parser.error('document ids must be unique')
    metadata=json.loads((ROOT/'model-api.json').read_text())
    if metadata.get('id')!='google/embeddinggemma-2' or metadata.get('sha')!=REVISION:
        raise RuntimeError('Unexpected model provenance')
    for key in ['PIP_PREFIX','PIP_TARGET','PYTHONPATH','VIRTUAL_ENV']:
        os.environ.pop(key,None)
    os.environ.update(HF_HOME=str(ROOT/'hf-cache'),TORCH_HOME=str(ROOT/'torch-cache'),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    import torch
    import numpy as np
    import psutil
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(2)
    proc=psutil.Process()
    if os.name=='nt':
        proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    class Memory(ctypes.Structure):
        _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ['total_phys','avail_phys','total_pagefile','avail_pagefile','total_virtual','avail_virtual','avail_extended']]
    memory=Memory(); memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise RuntimeError('Cannot verify available Windows memory')
    if memory.avail_phys < 512*1024**2 or memory.avail_pagefile < 3*1024**3:
        raise RuntimeError(f'Insufficient safe memory headroom: physical={memory.avail_phys}, commit={memory.avail_pagefile}')
    print('Loading offline text-only EmbeddingGemma 2...',file=sys.stderr,flush=True)
    model=SentenceTransformer(str(ROOT/'model'),device='cpu',trust_remote_code=False,local_files_only=True,config_kwargs={'vision_config':None,'audio_config':None},model_kwargs={'torch_dtype':torch.bfloat16,'attn_implementation':'eager'})
    model.max_seq_length=256
    q=model.encode([args.query],prompt_name='CodeRetrieval' if args.code else 'SearchQuery',batch_size=1,truncate_dim=args.dimension,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True).astype('float32')
    d=model.encode([x['text'] for x in docs],prompt_name='Document',batch_size=1,truncate_dim=args.dimension,normalize_embeddings=True,show_progress_bar=False,convert_to_numpy=True).astype('float32')
    q=q/np.linalg.norm(q,axis=1,keepdims=True)
    d=d/np.linalg.norm(d,axis=1,keepdims=True)
    scores=(q@d.T)[0]
    if q.shape!=(1,args.dimension) or d.shape!=(len(docs),args.dimension) or not np.isfinite(q).all() or not np.isfinite(d).all() or not np.isfinite(scores).all():
        raise RuntimeError('Invalid/non-finite embedding output')
    if not np.allclose(np.linalg.norm(np.concatenate([q,d]),axis=1),1,atol=1e-6):
        raise RuntimeError('Output normalization failed')
    order=np.argsort(-scores,kind='stable')[:args.top_k]
    result={'kind':'derived_retrieval_ranking','not_an_approval':'Not a safety, legal, product, or publication approval. Similarity only.','model_id':'google/embeddinggemma-2','revision':REVISION,'device':'cpu','dtype':'bfloat16','dimension':args.dimension,'normalized_export_dtype':'float32','max_sequence_tokens':256,'truncation_notice':'Inputs beyond 256 model tokens are truncated, including prompt tokens.','query_sha256':hashlib.sha256(args.query.encode()).hexdigest(),'source_file':str(source),'source_file_sha256':hashlib.sha256(raw).hexdigest(),'document_count':len(docs),'prompt':'CodeRetrieval' if args.code else 'SearchQuery','rankings':[{'rank':rank+1,'id':ids[int(i)],'cosine_score':float(scores[i])} for rank,i in enumerate(order)],'runtime_seconds_including_imports':time.perf_counter()-started,'modalities_executed':['text'],'remote_code':False,'offline':True}
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status':'error','error':str(exc)}),file=sys.stderr)
        sys.exit(1)
