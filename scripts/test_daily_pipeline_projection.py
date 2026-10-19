import json
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
from build_public_site import ROOT, SCHEMAS, build, project, registry_for_public_display

class DailyProjectionTests(unittest.TestCase):
    def test_bounded_selection_does_not_disclose_provenance_or_accept_spoof(self):
        rows=[{'status':'DRAFT','grade':'RANK','source':'private', 'shopify_id':'private'},
              {'status':'DRAFT','source':'owner_body_shower_category_fallback'},
              {'status':'DRAFT','source':'manual_owner_image_localization_example'},
              {'status':'DRAFT','selection_recorded':True},
              {'status':'deleted_by_owner','grade':'S'}]
        p=project(registry_for_public_display({'items':rows}),SCHEMAS['data/shopify_daily_registry.json'])
        self.assertEqual([r['selection_recorded'] for r in p['items']],[True,True,True,False,False])
        for r in p['items']:
            self.assertFalse({'grade','source','shopify_id'} & r.keys())

    def test_real_build_to_ui_and_error_refresh(self):
        self.check_build_to_ui(False)

    def test_observed_assets_do_not_approve_legal_or_imply_publication(self):
        self.check_build_to_ui(True)

    def check_build_to_ui(self, observed):
        with tempfile.TemporaryDirectory(dir=ROOT.parent) as td:
            # Build accepts only a separate sibling dist; isolate under a fixture root.
            import shutil
            from build_public_site import STATIC_FILES
            root=Path(td)/'source';root.mkdir()
            for f in (*STATIC_FILES,*SCHEMAS):
                p=root/f;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/f,p)
            # Fixed historical rows reproduce the deployed bug without depending on future daily picks.
            snapshots=[
                {'pd_no':'1084687','category':'skincare','date':'2026-10-16','status':'DRAFT',
                 'grade':'-','source':'manual_owner_image_localization_example',
                 'single_usd':None,'images':11,'title':'Historical manual cream draft',
                 'draft_reasons':['quantity_conflict_60g_vs_60mL','selling_price_evidence_pending']},
                {'pd_no':'1072801','category':'makeup','date':'2026-10-18','status':'DRAFT',
                 'grade':'RANK','source':'daiso_realtime_ranking','title':'Historical ranking draft',
                 'size':None,
                 'single_usd':24.99,'single_margin_pct':52.5,'images':0,
                 'draft_reasons':['ingredients_missing','no_usable_product_images']},
                {'pd_no':'1042251','category':'body','date':'2026-10-18','status':'DRAFT',
                 'grade':'-','source':'owner_body_shower_category_fallback','title':'Historical body draft',
                 'single_usd':18.99,'single_margin_pct':47.2,'images':0,
                 'draft_reasons':['inci_unresolved:1','no_usable_product_images']},
            ]
            observations={'items':[]}
            if observed:
                for i, row in enumerate(snapshots):
                    observations['items'].append({'pd_no':row['pd_no'],'source':'manual_connector_readback', 'observed_at':'2026-10-19T02:28:00Z', 'status':'ACTIVE', 'media_count':11 if i==0 else 6, 'online_store_visible':i==0, 'private_id':'secret'})
            (root/'data/shopify_public_observations.json').write_text(json.dumps(observations))
            (root/'data/shopify_daily_registry.json').write_text(json.dumps({'items':snapshots}))
            out=Path(td)/'dist';build(root,out,'a'*40)
            html=(out/'index.html').read_text()
            script=html.split('/* 오늘의 상품 등록 파이프라인:')[1].split('</script>')[0]
            script='/* 오늘의 상품 등록 파이프라인:'+script
            # This renderer shares its capacity formatter with the history list.
            formatter=re.search(r'function formatProductSize\([\s\S]*?\n}',html)
            self.assertIsNotNone(formatter)
            script=formatter.group(0)+'\n'+script
            script=script.replace('renderDailyPipeline();\nsetInterval(renderDailyPipeline,300000);','')
            data=json.loads((out/'data/shopify_daily_registry.json').read_text())
            observed_data=json.loads((out/'data/shopify_public_observations.json').read_text())
            self.assertTrue(all('private_id' not in r for r in observed_data['items']))
            self.assertTrue(all('shopify_observation' not in r for r in data['items']))
            self.assertTrue(all(r['status']=='DRAFT' for r in data['items']))
            self.assertEqual(data['items'][1]['size'], {})
            js=r'''
const assert=require('assert');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.className='';this.style={};this.attributes={};this._text='';this.classList={toggle(){}};}
 setAttribute(name,value){this.attributes[name]=String(value);}
 set textContent(v){this._text=v;this.children=[];} get textContent(){return this._text;}
 appendChild(c){c.parentNode=this;this.children.push(c);return c;}
 insertBefore(c,other){c.parentNode=this;this.children.splice(this.children.indexOf(other),0,c);}
 querySelector(s){return this.children.find(c=>c.className===s.slice(1))||null;}
 remove(){this.parentNode.children=this.parentNode.children.filter(c=>c!==this);}
 addEventListener(){}
}
const host=new Element('section'), ids={};
for(const id of ['dp-grid','dp-kpis','dp-when']){ids[id]=new Element('div');host.appendChild(ids[id]);}
const document={getElementById:id=>ids[id],createElement:t=>new Element(t),createTextNode:t=>({textContent:t})};
let fail=false, failObservation=false;
async function getJSON(p){if(p.includes('recommendations'))return {recommendations:[]};if(fail)throw Error('network');if(p.includes('shopify_public_observations')){if(failObservation)throw Error('observation unavailable');return OBSERVATIONDATA;}return DATA;}
SCRIPT
(async()=>{
 await renderDailyPipeline();
 assert.equal(ids['dp-grid'].children.length,3);
 const details=ids['dp-grid'].children[1].children.find(e=>e.className==='dp-detail');
 const capacity=details.children.find(e=>e.children[0].textContent==='용량');
 assert.equal(capacity.children[1].textContent,'표기 없음');
 let states=ids['dp-grid'].children.map(c=>c.children.find(e=>e.className==='dp-steps').children.map(e=>e.className));
 if(OBSERVED){
  assert.deepEqual(states[0],['dp-step done','dp-step wait','dp-step queued','dp-step done','dp-step done']);
  for(const state of states.slice(1))assert.deepEqual(state,['dp-step done','dp-step done','dp-step bad','dp-step done','dp-step wait']);
  assert(ids['dp-when'].textContent.includes('2026-10-19T02:28:00Z'));
 }else{
  assert.deepEqual(states[0],['dp-step done','dp-step wait','dp-step queued','dp-step queued','dp-step queued']);
  for(const state of states.slice(1))assert.deepEqual(state,['dp-step done','dp-step done','dp-step bad','dp-step queued','dp-step queued']);
 }
 failObservation=true; await renderDailyPipeline();
 let fallback=ids['dp-grid'].children.map(c=>c.children.find(e=>e.className==='dp-steps').children.map(e=>e.className));
 assert.equal(fallback[1][3],'dp-step queued'); assert.equal(fallback[1][4],'dp-step queued');
 assert(ids['dp-when'].textContent.includes('현재 상태 미조회'));
 failObservation=false; await renderDailyPipeline();
 assert.equal(ids['dp-grid'].children.length,3);assert.equal(ids['dp-kpis'].children.length,4);
 assert.equal(host.children.filter(c=>c.className==='dp-legend').length,1);
 fail=true;await renderDailyPipeline();
 assert.equal(ids['dp-grid'].children.length,0);assert(ids['dp-grid'].textContent.includes('확인할 수 없습니다'));
 assert.equal(ids['dp-kpis'].children.length,0);assert.equal(host.children.filter(c=>c.className==='dp-legend').length,0);
 fail=false;await renderDailyPipeline();assert.equal(ids['dp-grid'].children.length,3);
})().catch(e=>{console.error(e);process.exit(1)});
'''
            result=subprocess.run(['node','-e',js.replace('OBSERVATIONDATA',json.dumps(observed_data)).replace('DATA',json.dumps(data)).replace('SCRIPT',script).replace('OBSERVED',str(observed).lower())],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
