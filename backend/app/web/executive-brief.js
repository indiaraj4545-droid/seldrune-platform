(()=>{
const API='/api/v1';const $=s=>document.querySelector(s);
async function request(path){const token=sessionStorage.seldruneToken||'';if(!token)throw new Error('NO_SESSION');const r=await fetch(`${API}${path}`,{headers:{Authorization:`Bearer ${token}`}});if(r.status===401)throw new Error('SESSION_EXPIRED');if(!r.ok){const b=await r.json().catch(()=>({}));throw new Error(b.detail||`Request failed (${r.status})`)}return r.json()}
function money(v){return`$${Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2})}`}
function pct(v){return`${Math.round(Number(v||0)*100)}%`}
function clear(id){const e=$(id);e.replaceChildren();return e}
function text(tag,value,className=''){const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;return e}
function pair(label,value){const d=document.createElement('div');d.append(text('span',label),text('strong',value));return d}
function metric(label,value){const d=document.createElement('div');d.className='metric';d.append(text('small',label),text('strong',String(value)));return d}
function renderPriority(item){const d=document.createElement('div');d.className='priority';const h=document.createElement('h3');h.append(text('span',item.severity,`severity ${item.severity}`),document.createTextNode(item.title));d.append(h,text('p',item.detail));return d}
function renderIncident(item){const d=document.createElement('div');d.className='incident';d.append(text('h3',item.title),text('p',item.detail||item.type));return d}
function renderAgent(item){const d=document.createElement('div');d.className='agent';const rate=item.success_rate===null||item.success_rate===undefined?'No completed evidence':`${Math.round(item.success_rate*100)}% success`;d.append(text('h3',item.name),text('p',`${item.succeeded_tasks} succeeded · ${rate} · ${money(item.estimated_cost_usd)} recorded cost`));return d}
function render(data){$('#health-score').textContent=data.health.score;$('#health-posture').textContent=data.health.posture;
const s=data.operating_snapshot;const metrics=clear('#metrics');[['Open goals',s.open_goals],['Active projects',s.active_projects],['Awaiting approval',s.commands_awaiting_approval],['Open delegations',s.open_delegations],['Succeeded steps',s.succeeded_steps],['Failed steps',s.failed_steps],['Active agents',`${s.active_agents}/${s.total_agents}`],['Critical incidents',data.health.critical_incidents]].forEach(x=>metrics.append(metric(x[0],x[1])));
const priorities=clear('#priorities');if(data.priorities.length)data.priorities.forEach(x=>priorities.append(renderPriority(x)));else priorities.append(text('p','No immediate owner intervention is indicated by current evidence.','empty'));
const incidents=clear('#incidents');if(data.recent_incidents.length)data.recent_incidents.forEach(x=>incidents.append(renderIncident(x)));else incidents.append(text('p','No current operational incidents.','empty'));
const t=data.treasury;const treasury=clear('#treasury');treasury.append(pair('Allocated',money(t.allocated_budget_usd)),pair('Spent',money(t.spent_budget_usd)),pair('Reserved',money(t.reserved_budget_usd)),pair('Available',money(t.available_budget_usd)),pair('Utilization',pct(t.utilization)),pair('Overcommitted',t.overcommitted?'Yes':'No'));
const g=data.governance;const governance=clear('#governance');governance.append(pair('Max command steps',g.max_steps_per_command),pair('Max project budget',money(g.max_project_budget_usd)),pair('Autonomous execution',g.allow_autonomous_execution?'Allowed':'Disabled'));
const agents=clear('#agents');if(data.top_agents.length)data.top_agents.forEach(x=>agents.append(renderAgent(x)));else agents.append(text('p','No verified agent delivery evidence yet.','empty'));
}
function showError(message){const root=clear('#message');root.append(text('div',message,'message'))}
async function load(){clear('#message');try{const me=await request('/auth/me');const membership=me.memberships.find(x=>x.role==='owner');if(!membership)throw new Error('OWNER_REQUIRED');const data=await request(`/organizations/${membership.organization.id}/executive-brief`);render(data)}catch(e){if(['NO_SESSION','SESSION_EXPIRED'].includes(e.message))showError('Sign in to the Owner Console first, then open Executive Brief in the same browser tab.');else if(e.message==='OWNER_REQUIRED')showError('Executive Brief requires an organization owner account.');else showError(e.message)}}
$('#refresh').onclick=load;load();
})();
