(()=>{
const API='/api/v1';
const $=selector=>document.querySelector(selector);
let organizationId='';
let loading=false;
let reloadTimer=null;
let commandObserver=null;

async function request(path){
  const token=sessionStorage.seldruneToken||'';
  if(!token)throw new Error('Owner session required');
  const response=await fetch(`${API}${path}`,{
    headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
  });
  if(!response.ok){
    const body=await response.json().catch(()=>({}));
    throw new Error(body.detail||`Request failed (${response.status})`);
  }
  return response.json();
}

async function resolveOrganization(){
  const me=await request('/auth/me');
  const membership=(me.memberships||[]).find(item=>item.role==='owner');
  if(!membership)throw new Error('Owner organization not available');
  organizationId=membership.organization.id;
  return organizationId;
}

function approvalStatus(command){
  return command.context?.owner_command?.approval_status||'awaiting_approval';
}

function commandBudget(command){
  const delivery=command.context?.project_delivery||{};
  const forecast=delivery.cost_forecast||{};
  const governor=command.context?.portfolio_governor||{};
  const reservation=governor.budget_reservation||null;
  const execution=command.summary?.autonomous_execution||{};
  return{
    forecast:Number(forecast.estimated_execution_cost_usd||0),
    reservation,
    recorded:Number(execution.recorded_cost_usd||0),
    halted:execution.halted_reason==='budget_reservation_exceeded',
  };
}

function appendBudget(container,data){
  if(!data.forecast&&!data.reservation&&!data.recorded)return;
  const strip=document.createElement('div');
  strip.className='budget-strip';
  const reservation=Number(data.reservation?.amount_usd||0);
  const status=data.halted
    ?'Circuit breaker stopped execution'
    :`Reservation: ${data.reservation?.status||'not reserved'}`;
  [
    `Forecast ${data.forecast.toFixed(4)}`,
    `Reserved ${reservation.toFixed(4)}`,
    `Recorded ${data.recorded.toFixed(4)}`,
    status,
  ].forEach((value,index)=>{
    const span=document.createElement('span');
    span.textContent=value;
    if(index===3&&data.halted)span.className='budget-alert';
    strip.append(span);
  });
  container.append(strip);
}

function actionButton(label,action,id){
  const button=document.createElement('button');
  button.type='button';
  button.dataset.action=action;
  button.dataset.id=id;
  if(action==='brief')button.className='ghost';
  button.textContent=label;
  return button;
}

function renderAllCommands(commands){
  const root=$('#command-list');
  if(!root)return;
  if(commandObserver)commandObserver.disconnect();
  root.replaceChildren();
  if(!commands.length){
    const empty=document.createElement('div');
    empty.className='empty';
    empty.textContent='No commands yet. Create your first objective.';
    root.append(empty);
  }else{
    commands.forEach(command=>{
      const card=document.createElement('article');
      card.className='command-card';
      card.id=`command-${command.id}`;

      const content=document.createElement('div');
      const title=document.createElement('h3');
      title.textContent=command.objective;
      const meta=document.createElement('div');
      meta.className='meta';
      const status=document.createElement('span');
      status.className='pill';
      status.textContent=command.status;
      const approval=document.createElement('span');
      const approvalValue=approvalStatus(command);
      approval.className=`pill ${approvalValue==='awaiting_approval'?'pending':''}`;
      approval.textContent=approvalValue.replaceAll('_',' ');
      meta.append(status,approval);
      content.append(title,meta);
      appendBudget(content,commandBudget(command));

      const actions=document.createElement('div');
      actions.className='actions';
      actions.append(actionButton('Decision brief','brief',command.id));
      if(approvalValue==='approved'){
        actions.append(
          actionButton('Execute','execute',command.id),
          actionButton('Revoke approval','revoke',command.id),
        );
      }else{
        actions.append(actionButton('Approve','approve',command.id));
      }
      card.append(content,actions);
      root.append(card);
    });
  }
  observeCommandList();
}

function setCount(id,value){
  const element=$(id);
  if(element)element.textContent=String(value);
}

function inboxItem(kind,badge,title,detail,meta){
  const item=document.createElement('article');
  item.className=`action-inbox-item action-inbox-${kind}`;
  const marker=document.createElement('span');
  marker.className='action-inbox-badge';
  marker.textContent=badge;
  const content=document.createElement('div');
  const heading=document.createElement('strong');
  heading.textContent=title;
  const description=document.createElement('p');
  description.textContent=detail;
  content.append(heading,description);
  if(meta){
    const small=document.createElement('small');
    small.textContent=meta;
    content.append(small);
  }
  item.append(marker,content);
  return item;
}

function navigationLink(label,href){
  const link=document.createElement('a');
  link.href=href;
  link.textContent=label;
  return link;
}

function reviewCommandButton(commandId){
  const button=document.createElement('button');
  button.type='button';
  button.dataset.inboxCommand=commandId;
  button.textContent='Review command';
  return button;
}

function renderInbox(dashboard,commands,brief){
  const root=$('#owner-action-list');
  if(!root)return;
  const approvals=commands.filter(command=>approvalStatus(command)==='awaiting_approval');
  const reviews=(brief.priorities||[]).filter(item=>{
    const review=item.strategy_review||{};
    return review.required&&!review.current;
  });
  const incidents=dashboard.operational_incidents?.recent||[];
  const critical=incidents.filter(item=>item.severity==='critical');
  const warnings=incidents.filter(item=>item.severity==='warning');

  setCount('#action-approvals',approvals.length);
  setCount('#action-reviews',reviews.length);
  setCount('#action-critical',critical.length);
  setCount('#action-warnings',warnings.length);
  root.replaceChildren();

  const appendIncident=(incident,kind,label)=>{
    const item=inboxItem(
      kind,
      label,
      incident.title,
      incident.detail||incident.type,
      incident.occurred_at?new Date(incident.occurred_at).toLocaleString():'',
    );
    item.append(navigationLink('Open incidents','#incident-title'));
    root.append(item);
  };
  critical.forEach(item=>appendIncident(item,'critical','Critical'));

  reviews.forEach(priority=>{
    const review=priority.strategy_review||{};
    const stale=review.status==='stale';
    const item=inboxItem(
      'review',
      stale?'Re-review':'Review',
      priority.title||'Strategy review required',
      stale
        ?'Previously reviewed strategy evidence changed. A current owner review is required before a new governed command can be created.'
        :'A comparative strategy recommendation requires owner review before command creation.',
      priority.detail||'',
    );
    item.append(navigationLink('Open Review Drift','/console-assets/executive-brief.html'));
    root.append(item);
  });

  approvals.forEach(command=>{
    const item=inboxItem(
      'approval',
      'Approval',
      command.objective,
      'Governed plan is waiting for the owner to inspect its decision brief and explicitly approve or reject execution.',
      command.created_at?new Date(command.created_at).toLocaleString():'',
    );
    item.append(reviewCommandButton(command.id));
    root.append(item);
  });

  warnings.forEach(item=>appendIncident(item,'warning','Warning'));

  if(!root.childElementCount){
    const clear=document.createElement('div');
    clear.className='action-inbox-clear';
    clear.textContent='No owner decisions or operational alerts currently require attention.';
    root.append(clear);
  }
}

function showInboxError(message){
  const root=$('#owner-action-list');
  if(!root)return;
  root.replaceChildren();
  const error=document.createElement('div');
  error.className='action-inbox-clear';
  error.textContent=`Action inbox unavailable: ${message}`;
  root.append(error);
}

async function loadActionSurface(){
  const view=$('#console-view');
  if(loading||!view||view.classList.contains('hidden'))return;
  if(!sessionStorage.seldruneToken)return;
  loading=true;
  try{
    if(!organizationId)await resolveOrganization();
    const [dashboard,commands,brief]=await Promise.all([
      request(`/organizations/${organizationId}/owner-dashboard`),
      request(`/organizations/${organizationId}/owner-commands`),
      request(`/organizations/${organizationId}/executive-brief`),
    ]);
    renderAllCommands(commands);
    renderInbox(dashboard,commands,brief);
  }catch(error){
    showInboxError(error.message);
  }finally{
    loading=false;
  }
}

function scheduleReload(){
  clearTimeout(reloadTimer);
  reloadTimer=setTimeout(loadActionSurface,120);
}

function observeCommandList(){
  const root=$('#command-list');
  if(!root)return;
  if(!commandObserver){
    commandObserver=new MutationObserver(()=>{
      if(!loading)scheduleReload();
    });
  }
  commandObserver.observe(root,{childList:true});
}

$('#owner-action-list')?.addEventListener('click',event=>{
  const control=event.target.closest('[data-inbox-command]');
  if(!control)return;
  const card=document.getElementById(`command-${control.dataset.inboxCommand}`);
  if(!card)return;
  document.querySelectorAll('.command-card.inbox-focus').forEach(item=>item.classList.remove('inbox-focus'));
  card.classList.add('inbox-focus');
  card.scrollIntoView({behavior:'smooth',block:'center'});
  setTimeout(()=>card.querySelector('button[data-action="brief"]')?.click(),180);
});

$('#refresh')?.addEventListener('click',scheduleReload);

const consoleView=$('#console-view');
if(consoleView){
  new MutationObserver(()=>{
    if(consoleView.classList.contains('hidden')){
      organizationId='';
    }else{
      scheduleReload();
    }
  }).observe(consoleView,{attributes:true,attributeFilter:['class']});
}
observeCommandList();
if(consoleView&&!consoleView.classList.contains('hidden'))scheduleReload();
})();
