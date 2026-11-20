import {store} from '../stores/entities.js';
import {session} from '../stores/session.js';
import {purgesAPI} from '../api/entities.js';
import {table} from '../components/common/table.js';
import {purgeBadge} from '../components/common/status.js';
import {esc,formObject} from '../utils/html.js';
import {action,message} from '../hooks/action.js';
import {PURGE_STEPS} from '../constants/enums.js';

const STATUS_TEXT={active:'保留中',purging:'已受理，清理中',purged:'已清理'};

export function retentionPage(){
 const expired=store.points.filter(p=>p.expired&&p.status==='active');
 const pointRows=store.points.map(p=>[esc(pointLogSet(p.log_set_id)),esc(p.key),esc(p.retain_until),p.expired?'已过期':'保留期内',esc(STATUS_TEXT[p.status]||p.status),p.status==='active'&&p.expired&&session.role!=='viewer'?`<button class="secondary purge-one" data-log-set="${p.log_set_id}" data-key="${esc(p.key)}">受理清理</button>`:'—']);
 const ledgerRows=store.logs.map(l=>[esc(l.name),esc(JSON.stringify(l.initial)),(l.redacted_points||[]).length?esc('已清理：'+(l.redacted_points||[]).join(', ')):'全部保留']);
 const purgeRows=store.purges.map(j=>[j.id,esc(pointLogSet(j.log_set_id)+' / '+j.point_key),purgeBadge(j.status),esc(j.progress+' · 下一步 '+(PURGE_STEPS[j.remaining_step]||'—')),esc(j.message||''),esc(JSON.stringify(j.remaining_ledger||{}))]);
 const selectable=store.logs.filter(l=>store.points.some(p=>p.log_set_id===l.id&&p.status==='active'&&(p.key in (l.initial||{}))));
 return `<div class="section-title"><h2>采样点保留期限</h2><span>过期读数不得继续保留</span></div><div class="boundary">受理后该点立即从旧报告与下载中隐去；日志前缀、排队快照、已存报告由后台分步擦除，中断后可续跑。其他采样点照常演练与导出。</div>
 ${table(['日志集','采样点','保留至','期限','状态','操作'],pointRows)}
 <section class="split"><div><h2>剩余读数</h2><p>清理完成后，日志集账本只保留未过期采样点的读数；清理步骤按 日志 → 排队快照 → 已存报告 推进。</p>${table(['日志集','当前账本','已清理点'],ledgerRows)}<h2 style="margin-top:28px">可受理的过期点</h2><p>${expired.length?esc('共 '+expired.length+' 个点已过保留期限，等待受理。'):'暂无已过期且仍保留的采样点。'}</p></div>
 ${session.role!=='viewer'?`<form id="purge-form"><h2>受理一次清理</h2><label>日志集<select name="log_set_id">${selectable.map(l=>`<option value="${l.id}">${esc(l.name)}</option>`).join('')}</select></label><label>采样点<select name="key">${selectable.flatMap(l=>store.points.filter(p=>p.log_set_id===l.id&&p.status==='active').map(p=>`<option value="${esc(p.key)}" data-log-set="${l.id}">${esc(l.name)} / ${esc(p.key)}${p.expired?'（已过期）':''}</option>`)).join('')}</select></label><button type="submit">受理并清理 →</button></form>`:'<p class="readonly">观察员可核对清理进度，受理需要操作员或管理员。</p>'}</section>
 <div class="section-title"><h2>清理进度</h2><button class="secondary" id="refresh">刷新进度</button></div>
 ${table(['编号','日志集 / 采样点','状态','进度','说明','其余读数'],purgeRows)}`;}
export function bindRetention(render){
 document.querySelector('#refresh').onclick=render;
 document.querySelector('#purge-form')?.addEventListener('change',e=>{
  if(e.target.name!=='log_set_id')return;const logSetId=e.target.value;const keySelect=document.querySelector('#purge-form select[name=key]');
  const points=store.points.filter(p=>String(p.log_set_id)===String(logSetId)&&p.status==='active');
  keySelect.innerHTML=points.map(p=>`<option value="${esc(p.key)}">${esc(p.key)}${p.expired?'（已过期）':''}</option>`).join('')||'<option value="">无可受理采样点</option>';
 });
 document.querySelectorAll('.purge-one').forEach(b=>b.onclick=async()=>{try{await purgesAPI.create({log_set_id:Number(b.dataset.logSet),key:b.dataset.key});message('已受理，该点已从报告与下载中隐去');await render();}catch(err){message(err.message,true);}});
 action(document.querySelector('#purge-form'),async f=>{const d=formObject(f);if(!d.key)throw new Error('请选择可受理的采样点');await purgesAPI.create({log_set_id:Number(d.log_set_id),key:d.key});await render();});
}
function pointLogSet(id){return store.logs.find(l=>l.id===id)?.name||('日志集 #'+id);}
