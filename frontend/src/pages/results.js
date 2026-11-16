import {jobs} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {submit} from '../hooks/forms.js';
import {heading} from '../components/common/shell.js';
import {chart} from '../components/common/chart.js';
import {table} from '../components/common/table.js';
import {status} from '../components/common/status.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
function progressPanel(j){
 const p=j.progress||{};const completed=p.completed||0,target=p.target||j.params?.resamples||0;
 const bands=p.bands||[];
 const canRun=session.user.role!=='viewer';
 const appendButton=canRun&&['completed','paused','failed'].includes(j.status)&&!j.superseded_by&&!p.legacy&&target<5000?'<button class="button small" id="append-job" aria-expanded="false">追加采样次数</button>':'';
 const appendForm=appendButton?'<form id="append-form" class="append-form" hidden><label>追加次数<input type="number" name="additional" min="1" max="'+Math.max(1,5000-target)+'" step="1" value="'+Math.min(500,Math.max(1,5000-target))+'" required></label><button type="submit" class="small primary">确认追加</button><small>仅补算未完成部分；当前目标 '+target+' 次。</small></form>':'';
 const stateButton=canRun&&['queued','running'].includes(j.status)?'<button class="button small" id="pause-job">暂停采样</button>':(canRun&&['paused','failed'].includes(j.status)?'<button class="button small" id="resume-job">继续采样</button>':'');
 const version=j.parent_id?'<p class="hint">本版为追加采样产生的待审版本，沿用原版已存采样，只补算未完成部分。</p>':(p.legacy?'<p class="hint">这是升级前的结果，未保存逐次采样明细；如需追加次数请新建分析任务。</p>':'');
 return '<section class="panel progress-panel"><div class="section-title"><h2>采样进度</h2><span>已完成 '+completed+' / 目标 '+target+' 次 · '+fmt(p.percent||0)+'%</span></div><div class="progress-track" role="progressbar" aria-valuemin="0" aria-valuemax="'+target+'" aria-valuenow="'+completed+'"><span style="width:'+Math.min(100,p.percent||0)+'%"></span></div><div class="progress-bands">'+bands.map(b=>'<div><strong>'+esc(b.band)+'</strong><span>'+b.completed+' / '+target+' 次 · '+b.n+' 对</span></div>').join('')+'</div><div class="progress-actions">'+stateButton+appendButton+'<small>分段 '+(p.segment_size||'—')+' 次/段 · 段大小与暂停位置不改变同参数同总次数的最终区间。</small></div>'+appendForm+version+'</section>';
}
export async function results(id){
 workspace.jobs=await jobs.list();const j=id?await jobs.get(id):(workspace.jobs.find(j=>j.id===workspace.selectedJob)||workspace.jobs[0]);
 if(j&&!workspace.jobs.some(x=>x.id===j.id))workspace.jobs.push(j);
 if(!j)return heading('04 / REVIEW','结果复核','尚无分析结果。')+'<div class="empty">先到分析工作台，选择批次并提交一次计算。<a href="#/workbench">前往工作台 ↗</a></div>';
 workspace.selectedJob=j.id;const r=j.result||{};
 const complete=j.status==='completed'&&r.summary;
 const body=complete?'<section class="result-lead"><p class="eyebrow">COMPUTED FINDING</p><h2>'+esc(r.summary)+'</h2><div class="metrics">'+(r.metrics||[]).map(m=>'<div><span>'+esc(m.label)+'</span><strong>'+esc(fmt(m.value))+'<small>'+esc(m.unit||'')+'</small></strong></div>').join('')+'</div></section><section class="panel">'+chart(r.chart)+'</section><div class="two-columns"><section class="panel"><div class="section-title"><h2>业务解释</h2><span>由计算结果生成</span></div><ol class="questions">'+(r.findings||[]).map(v=>'<li>'+esc(v)+'</li>').join('')+'</ol>'+(r.warnings||[]).map(v=>'<p class="warning">'+esc(v)+'</p>').join('')+'</section><section class="method-sheet compact"><p class="eyebrow">REPRODUCIBILITY</p><h3>计算口径与参数</h3><p>'+esc(r.method)+'</p><pre>'+esc(JSON.stringify(j.params,null,2))+'</pre>'+(session.user.role==='admin'&&!j.approved&&!j.superseded_by?'<button class="primary" id="approve-job">批准此业务结论</button>':'')+(j.approved?'<p class="approval">已获业务批准。追加采样会保留此版本并另建待审版本。</p>':'')+'<p class="hint">仅已完成且获批准的结果可进入定时分发档案。</p></section></div><section class="panel"><div class="section-title"><h2>结果明细</h2><span>'+(r.table?.rows?.length||0)+' 行</span></div>'+table(r.table?.columns||[],r.table?.rows||[])+'</section>':'<section class="panel empty">'+(j.status==='failed'?'计算失败：'+esc(j.error)+'。请恢复采样或返回工作台调整参数或数据。':j.status==='paused'?'采样已暂停，进度已保存。继续后只计算未完成部分。':'后台正在执行分段计算，已完成部分会随时保存。')+'<a href="#/workbench">返回工作台 ↗</a></section>';
 return heading('04 / REVIEW','结果复核与业务解释',j.name,'<button class="button" id="refresh-results">刷新结果 ↻</button>')+'<div class="result-selector"><label>分析记录<select id="select-job">'+workspace.jobs.map(x=>'<option value="'+x.id+'" '+(x.id===j.id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.status)+(x.parent_id?' · 待审版本':'')+'</option>').join('')+'</select></label>'+status(j.status)+'<span>'+date(j.created_at)+'</span><span class="approval">'+(j.approved?'已获业务批准':j.superseded_by?'已被待审版本替代':'待负责人复核')+'</span></div>'+(j.superseded_by?'<p class="hint">已批准原版被保留，追加采样已另建待审版本 #'+j.superseded_by+'；原版仍可按原快照分发。</p>':'')+progressPanel(j)+body;
}
export function bindResults(refresh){
 clearTimeout(window.__resultPoll);
 document.querySelector('#refresh-results')?.addEventListener('click',refresh);
 document.querySelector('#select-job')?.addEventListener('change',e=>{workspace.selectedJob=Number(e.target.value);location.hash='#/results/'+e.target.value;});
 document.querySelector('#approve-job')?.addEventListener('click',async()=>{try{await jobs.approve(workspace.selectedJob);notify('已批准，可创建分发计划');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#pause-job')?.addEventListener('click',async()=>{try{await jobs.pause(workspace.selectedJob);notify('已暂停；已存采样保留，继续时只算未完成部分');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#resume-job')?.addEventListener('click',async()=>{try{await jobs.resume(workspace.selectedJob);notify('已恢复采样，从已存进度继续');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelector('#append-job')?.addEventListener('click',()=>{const f=document.querySelector('#append-form');if(f){f.hidden=!f.hidden;f.querySelector('input')?.focus();}});
 submit(document.querySelector('#append-form'),async f=>{
   const additional=Number(f.get('additional'));
   const current=workspace.jobs.find(x=>x.id===workspace.selectedJob);
   const left=5000-(current?.progress?.target||current?.params?.resamples||2000);
   if(!Number.isInteger(additional)||additional<1||additional>left)throw new Error('追加次数需为 1 到 '+Math.max(1,left)+' 之间的整数');
   const j=await jobs.append(workspace.selectedJob,{additional});
   workspace.selectedJob=j.id;
   notify(j.parent_id?'已另建待审版本，只补算未完成部分':j.status==='paused'?'已记录追加次数；继续采样后只补算未完成部分':'已追加采样，只补算未完成部分');
   location.hash='#/results/'+j.id;await refresh();
 });
 const live=document.querySelector('.progress-panel')&&['queued','running'].includes((workspace.jobs.find(x=>x.id===workspace.selectedJob)||{}).status);
 if(live)window.__resultPoll=setTimeout(refresh,4000);
}
