import json, pathlib, urllib.request, hashlib, time, os
ROOT=pathlib.Path(__file__).resolve().parent
META=json.loads((ROOT/'model-api.json').read_text())
TREE=json.loads((ROOT/'model-tree.json').read_text())
REV=META['sha']
OUT=ROOT/'model'; OUT.mkdir(exist_ok=True)
checks=[]
for item in TREE:
    if item['type']!='file' or item['path']=='.gitattributes': continue
    rel=item['path']; dest=OUT/rel; dest.parent.mkdir(parents=True,exist_ok=True)
    url=f'https://huggingface.co/google/embeddinggemma-2/resolve/{REV}/{rel}?download=true'
    if not dest.exists() or dest.stat().st_size != item['size']:
        print('Downloading',rel,item['size'],flush=True)
        with urllib.request.urlopen(url,timeout=120) as r, open(str(dest)+'.partial','wb') as f:
            while True:
                b=r.read(4*1024*1024)
                if not b: break
                f.write(b)
        os.replace(str(dest)+'.partial',dest)
    h=hashlib.sha256()
    with open(dest,'rb') as f:
        while b:=f.read(4*1024*1024): h.update(b)
    digest=h.hexdigest(); expected=item.get('lfs',{}).get('oid')
    passed=dest.stat().st_size==item['size'] and (not expected or digest==expected)
    checks.append({'path':rel,'size':dest.stat().st_size,'sha256':digest,'expected_lfs_sha256':expected,'passed':passed})
    print('Checked',rel,passed,flush=True)
    if not passed: raise RuntimeError('Integrity failed: '+rel)
(ROOT/'integrity.json').write_text(json.dumps({'model_id':META['id'],'revision':REV,'files':checks,'all_passed':all(x['passed'] for x in checks)},indent=2))
print('DOWNLOAD_AND_INTEGRITY_OK',flush=True)
