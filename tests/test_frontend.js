/* Development checks only. The application itself still has no Node dependency. */
const fs=require('fs'), path=require('path'), vm=require('vm'), assert=require('assert');
const root=path.resolve(__dirname,'..');
const document={addEventListener(){},getElementById(){return null},querySelector(){return null}};
const context=vm.createContext({document,console,URLSearchParams,Set,Date,location:{search:'',hash:''}});
vm.runInContext(fs.readFileSync(path.join(root,'static/core.js'),'utf8'),context);
vm.runInContext(fs.readFileSync(path.join(root,'static/charts.js'),'utf8'),context);
const views=fs.readFileSync(path.join(root,'static/views.js'),'utf8');
vm.runInContext(views.slice(0,views.indexOf('document.getElementById("tabs").addEventListener')),context);
const run=code=>vm.runInContext(code,context);
assert.equal(run(`SRC.codex.icon`),'openai');
assert.equal(run(`SRC.opencode.label`),'OpenCode');
assert.match(run(`toolLabel('opencode')`),/>OpenCode</);
assert.match(run(`srcBadge('opencode')`),/OpenCode/);
assert.match(run(`quotaWindowHTML({label:'5-hour limit',remaining_percent:89,resets_at:2000},{observed_at:1000},1000)`),/89% left/);
assert.match(run(`quotaWindowHTML({label:'5-hour limit',remaining_percent:0,resets_at:2000},{observed_at:1000},1000)`),/value="0"/);
assert.doesNotMatch(run(`quotaWindowHTML({label:'5-hour limit',remaining_percent:null,resets_at:null},{observed_at:1000},1000)`),/<progress|100% left/);
assert.match(run(`quotaWindowHTML({label:'5-hour limit',remaining_percent:89,resets_at:1100},{observed_at:1000},1301)`),/Stale|Reset passed/);
assert.match(run(`quotaWindowHTML({label:'5-hour limit',remaining_percent:89,resets_at:1100},{observed_at:1000},1301)`),/89% left/);
assert.doesNotMatch(run(`quotaWindowHTML({label:'<img src=x onerror=alert(1)>',remaining_percent:89,resets_at:2000},{observed_at:1000},1000)`),/<img src=x/);
assert.match(run(`sessionAccountDetails({source:'codex',account_metadata:{creator_account_id:'creator-A'}})`),/Thread creator account/);
assert.match(run(`sessionAccountDetails({source:'claude'})`),/Not recorded/);
assert.doesNotMatch(run(`sessionAccountDetails({source:'claude',account_metadata:{recorded_account_ids:['<img src=x onerror=alert(1)>']}})`),/<img src=x/);
assert.doesNotMatch(run(`accountEntryHTML({source:'codex',profile:'<img src=x onerror=alert(1)>',identity:{auth:'apiKey',email:'<img src=x>',plan:null},snapshots:[]})`),/<img src=x/);
assert.equal(run(`SRC.claude.icon`),run(`SRC['claude-desktop'].icon`));
for(const source of run(`ORDER`)){
  const name=run(`SRC[${JSON.stringify(source)}].icon`);
  assert.ok(fs.existsSync(path.join(root,'static/tool-icons',name+'.svg')),source+' lacks its bundled mark');
  assert.ok(run(`toolIcon(${JSON.stringify(source)})`).includes('role="img"'));
  assert.ok(!run(`toolIcon(${JSON.stringify(source)})`).includes('https://'),'Logo fetch would leak a local dashboard visit');
}
assert.ok(run(`toolDot('codex')`).includes('/static/tool-icons/openai.svg'));
assert.ok(run(`srcBadge('copilot')`).includes('/static/tool-icons/copilot.svg'));
assert.ok(run(`toolLabel('codex')`).includes('aria-hidden="true"'));
assert.ok(run(`legendHTML('test',[{source:'codex',label:'Codex',color:'#fff'}])`).includes('data-k="Codex"'));
assert.ok(!run(`toolIcon('<img src=x onerror=alert(1)>')`).includes('<img src=x'));
assert.ok(!run(`renameButton({device:'Mac',source:'codex',id:'fixture',title:'<img src=x onerror=alert(1)>'})`).includes('<img src=x'));
assert.notEqual(run(`sessionIdentity({device:'Mac',source:'codex',id:'same'})`),
                run(`sessionIdentity({device:'PC',source:'codex',id:'same'})`));
assert.notEqual(run(`sessionIdentity({device:'Mac',source:'claude',id:'same',rename_id:'same-uuid-one'})`),
                run(`sessionIdentity({device:'Mac',source:'claude',id:'same',rename_id:'same-uuid-two'})`));
run(`let haikuPreviousRaw=RAW;
 RAW={pricing:{'Claude Haiku 5.5':[.1,.5,.125,.2,.01]},
      prices:{'Claude Haiku 5.5':[.1,.5,.125,.2,.01]},
      pricing_long_context:{'Claude Haiku 5.5':[.5,2.5,.625,1,.05]}};
 let haikuRow={model:'Claude Haiku 5.5',date:'2026-10-12',in:2,out:3,cc5:4,cc1:5,cr:100001,
     asst:2,lc_in:1,lc_out:2,lc_cc5:3,lc_cc1:4,lc_cr:100000,lc_asst:1};`);
const near=(value,expected)=>assert.ok(Math.abs(value-expected)<1e-10,`${value} != ${expected}`);
near(run(`Object.values(tokenCostParts(haikuRow)).reduce((a,b)=>a+b,0)/1e6`),.00501231);
near(run(`cacheSavings(haikuRow)`),.04500009);
near(run(`cachedRequestRate(haikuRow)`),.03);
near(run(`cacheWriteRate([haikuRow])`),6.2/9/1e6);
near(run(`rateOf('Claude Haiku 5.5')[0]`),.5);
run(`RAW.pricing['Legacy']=[1,5,0,0,.1];`);
near(run(`tokenCostParts({model:'Legacy',in:1,out:2,cc:3,cr:4}).cw`),3);
run(`RAW.prices['Legacy']=[1,5,0,0,.1]; RAW.pricing_history={'Legacy':[['2026-01-01',[2,10,0,0,.2]]]};`);
near(run(`tokenCostParts({model:'Legacy',date:'2025-12-31',cc:3}).cw`),6);
near(run(`cacheWriteRate([{model:'Legacy',date:'2025-12-31',cc:3}])`),1e-6);
near(run(`cachedRequestRate({model:'Legacy',date:'2025-12-31',asst:1})`),.1);
run(`RAW=haikuPreviousRaw;`);
run(`RAW={device:{id:'Mac'},devices:[{id:'Mac',name:'Mac'},{id:'PC',name:'PC'}],
 records:[],sessions:[],hourly:[],tools:[],pricing:{'Claude Opus 5.5 (US)':[4.4,22,5.5,8.8,.22]},
 prices:{'Claude Opus 5.5 (fast)':[8,40,10,16,.4]}};
 S.tools=new Set(['copilot','codex','claude']);`);
assert.equal(run(`priceOf('Claude Opus 5.5 (US)','2026-10-02')[0]`),4.4);
assert.equal(run(`priceOf('Claude Opus 5.5 (fast)')[0]`),8);
run(`RAW.pricing_history={'Claude Opus 5.5 (US)':[['2026-09-01',[5.5,27.5,6.875,11,.55]]]};`);
assert.equal(run(`priceOf('Claude Opus 5.5 (US)','2026-08-01')[0]`),5.5);
run(`RAW.records=[{date:'2026-10-02',source:'copilot',device:'Mac',model:'M',project:'P',ide:'VS Code',in:500,out:50,cost:1,
 exact:{in:100,out:10,asst:1,user:1,req:1,cost:.2}}]; S.exactOnly=true;`);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).recs[0].in`),100);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).recs[0].cost`),.2);
run(`RAW.records.push({date:'2026-10-02',source:'copilot',device:'Mac',model:'M',in:5});`);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).recs.length`),1);
run(`S.exactOnly=false; S.ides=new Set(['Missing']); RAW.hourly=[{date:'2026-10-02',source:'copilot',device:'Mac',hour:10,tokens:110,msgs:1}];`);
assert.equal(run(`!!dimFiltered()`),true);
run(`S.ides.clear(); S.models=new Set(['Secondary']); RAW.sessions=[{source:'claude',project:'P',model:'Primary',
 model_days:{'Primary':{'2026-10-02':[9,900,90,0,0,9,0,0,0,0,9,0,0,0,0]},
 'Secondary':{'2026-10-02':[1,100,10,0,0,1,0,0,0,0,1,0,0,0,0]}},
 days:{'2026-10-02':[10,1000,100,0,0,10,0,0,0,0,10,0,0,0,0]}}];`);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).sessions[0].cost`),1);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).sessions[0].req`),1);
run(`S.models.clear(); RAW.sessions=[{source:'copilot',model:'M',exact_days:{'2026-10-02':[.2,100,10,0,0,1,1,0,0,0,1]},
 exact_model_days:{'M':{'2026-10-02':[.2,100,10,0,0,1,1,0,0,0,1]}},days:{'2026-10-02':[1,500,50,0,0,5,5,0,0,0,5]}}]; S.exactOnly=true;`);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).sessions[0].in`),100);
run(`S.exactOnly=false; RAW.sessions=[{source:'claude',model:'(user)',model_days:{'(user)':{'2026-10-02':[0,0,0,0,0,0,1]}},days:{'2026-10-02':[0,0,0,0,0,0,1]}}];`);
assert.equal(run(`slice({from:'2026-10-02',to:'2026-10-02'}).sessions[0].user`),1);
run(`S.exactOnly=false; RAW.mcp_servers=[{name:'fixture',tool:'codex'}];
 RAW.tools=[{date:'2026-09-01',source:'codex',device:'Mac',name:'mcp__fixture__call',count:1},
 {date:'2026-10-02',source:'claude',device:'Mac',name:'mcp__fixture__call',count:1}];`);
assert.equal(run(`findIdleMCP({r:{from:'2026-10-02',to:'2026-10-02'}},'codex').rows.length`),1);
run(`RAW.tools.push({date:'2026-10-02',source:'codex',device:'Mac',name:'mcp__fixture__call',count:1});`);
assert.equal(run(`findIdleMCP({r:{from:'2026-10-02',to:'2026-10-02'}},'codex')`),null);
run(`S.devs=new Set(['PC']);`);
assert.equal(run(`onThisDevice(()=>({id:'fixture'}))({recs:[],sessions:[]})`),null);
run(`S.devs.clear();`);
run(`RAW.tools=[];RAW.mcp_inventory={servers:{},calls:[{date:'2026-10-02',source:'codex',server:'fixture',calls:1,tools:['mcp__fixture__call']}]};`);
assert.equal(run(`findIdleMCP({r:{from:'2026-10-02',to:'2026-10-02'}},'codex')`),null);
assert.equal(run(`findCacheWaste({sessions:[{source:'claude',model:'Haiku',cc:1000000,cr:0,cost:1.25}]}).impact`),0);
run(`var deviceData={recs:[{device:'Mac',in:100,out:10,asst:2,cost:1},{device:'PC',in:200,out:20,asst:1,cost:4}]}; S.metric='tokens';`);
assert.equal(run(`deviceDistribution(deviceData).reduce((n,x)=>n+x.value,0)`),330);
assert.equal(run(`deviceDistribution(deviceData)[0].id`),'PC');
run(`S.metric='messages';`);assert.equal(run(`deviceDistribution(deviceData)[0].id`),'Mac');
run(`S.metric='cost';`);assert.equal(run(`deviceDistribution(deviceData)[0].value`),4);
run(`S.devs=new Set(['Mac']);`);assert.equal(run(`deviceDistribution(deviceData).length`),1);
assert.equal(run(`deviceDistribution(deviceData)[0].value`),1);
// Sidebar selection uses the existing device filter rather than a separate scope.
run(`S.devs.clear();`);
assert.equal(run(`sidebarDeviceState().value`),'all');
assert.equal(run(`selectSidebarDevice('device:PC')`),true);
assert.equal(run(`deviceDistribution(deviceData).length`),1);
assert.equal(run(`deviceDistribution(deviceData)[0].value`),4);
assert.equal(run(`sidebarDeviceState().name`),'PC');
assert.equal(run(`selectSidebarDevice('device:missing')`),false);
assert.equal(run(`sidebarDeviceState().value`),'device:PC');
assert.equal(run(`selectSidebarDevice('all')`),true);
assert.equal(run(`deviceDistribution(deviceData).length`),2);
run(`RAW.devices.push({id:'Third',name:'Third'});S.devs=new Set(['Mac','PC']);`);
assert.equal(run(`sidebarDeviceState().value`),'selected');
assert.ok(run(`sidebarDeviceState().options`).includes('value="selected" disabled'));
run(`RAW.devices=[{id:'Mac',name:'Mac'}];S.devs.clear();`);
assert.equal(run(`sidebarDeviceState().multiple`),false);
run(`RAW.devices=[{id:'Mac',name:'Mac'},{id:'PC',name:'PC'}];`);
const syncCode=views.slice(views.indexOf('const POLL_KEY='),views.indexOf('let nativeSettingsTimer;'));
for(const search of ['', '?nativeApp=1&nativePollSeconds=300']){
  const fixture=vm.createContext({URLSearchParams,location:{search}, document, console});
  vm.runInContext(syncCode,fixture);
  assert.equal(vm.runInContext('pollMs()',fixture),15000);
  assert.equal(vm.runInContext('acceptRefreshSync({seconds:60,revision:"tick"})',fixture),true);
  assert.equal(vm.runInContext('pollMs()',fixture),60000);
  assert.equal(vm.runInContext('acceptRefreshSync({seconds:60,revision:"tick"})',fixture),false);
  assert.equal(vm.runInContext('acceptRefreshSync({seconds:0,revision:"manual"})',fixture),true);
  assert.equal(vm.runInContext('pollMs()',fixture),0);
  for(const seconds of [true,1,-1,Infinity,'60']){
    assert.throws(()=>vm.runInContext(`acceptRefreshSync({seconds:${JSON.stringify(seconds)},revision:'bad'})`,fixture));
    assert.equal(vm.runInContext('pollMs()',fixture),0);
  }
}
run(`S.tools=new Set(['claude']);S.devs.clear();S.projs.clear();S.ides.clear();S.models.clear();S.provs.clear();S.exactOnly=false;
 var compactSession={source:'claude',model:'M',title:'Fixture',device:'Mac',
   days:{'2026-10-09':[1,100,10,0,0,1,1,0,0,0,1]},model_days:{M:{'2026-10-09':[1,100,10,0,0,1,1,0,0,0,1]}},
   compactions:[{id:'one',date:'2026-10-10',timestamp:'2026-10-10T13:09:08+06:00',trigger:'manual',before:558980,after:16124,duration_ms:93029},
   {id:'two',date:'2026-10-11',timestamp:'2026-10-11T13:09:08+06:00',trigger:'auto',before:100,after:200,duration_ms:null}]};
 RAW.sessions=[compactSession];RAW.records=[];RAW.hourly=[];`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),1);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].compaction_count`),1);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].in`),0);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].user`),0);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].cost`),0);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].span`),3);
assert.equal(run(`sessionWhen(slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0])`),'2026-10-10T13:09:08+06:00');
assert.equal(run(`sessionWhen({in:100,end:'2026-10-09',compactions:compactSession.compactions})`),'2026-10-09');
assert.equal(run(`slice({from:'2026-10-12',to:'2026-10-12'}).sessions.length`),0);
run(`S.models=new Set(['M']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0,'Unknown event model must not satisfy a billed model filter');
assert.equal(run(`slice({from:'2026-10-09',to:'2026-10-09'}).sessions[0].in`),100);
run(`S.models.clear();S.devs=new Set(['PC']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
run(`S.devs.clear();S.tools=new Set(['codex']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
run(`S.tools=new Set(['claude']);`);
assert.equal(run(`clipSession({source:'claude',days:{}},{from:'2026-10-10',to:'2026-10-10'}).compaction_count`),null);
assert.match(run(`compactionDetails({source:'claude'})`),/Not recorded in this ledger entry/);
assert.match(run(`compactionDetails({source:'claude',compactions:[]})`),/Compactions · 0/);
const compactHTML=run(`compactionDetails(clipSession(compactSession,{from:'2026-10-10',to:'2026-10-11'}))`);
assert.match(compactHTML,/1 manual · 1 auto/);
assert.match(compactHTML,/100 → 200/,'A context increase must remain visible');
assert.match(compactHTML,/Before: 558,980; after: 16,124/);
assert.match(compactHTML,/93s/);
assert.match(compactHTML,/tokens and cost are not recorded/);
assert.match(run(`compactionDetails({source:'claude',compactions:[{timestamp:'<script>',trigger:'unexpected',before:null,after:null,duration_ms:null}]})`),/&lt;script&gt;/);
assert.match(run(`compactionDetails({source:'codex'})`),/Not recorded in this ledger entry/);
assert.equal(run(`compactionDetails({source:'copilot'})`),'');
run(`S.tools=new Set(['codex']);var codexCompactSession={...compactSession,source:'codex',compactions:[
  {id:'response:fixture',date:'2026-10-10',timestamp:'2026-10-10T13:09:08+06:00',trigger:'unknown',before:null,after:null,duration_ms:null}]};
 RAW.sessions=[codexCompactSession];`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].compaction_count`),1);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0].cost`),0);
const codexHTML=run(`compactionDetails(slice({from:'2026-10-10',to:'2026-10-10'}).sessions[0])`);
assert.match(codexHTML,/1 unknown/);
assert.match(codexHTML,/Unknown/);
assert.match(codexHTML,/already included in session totals/);
assert.doesNotMatch(codexHTML,/tokens and cost are not recorded/);
assert.match(codexHTML,/— → —/);
run(`S.models=new Set(['M']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
assert.equal(run(`slice({from:'2026-10-09',to:'2026-10-09'}).sessions[0].in`),100);
run(`S.models.clear();S.tools=new Set(['claude']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
run(`S.tools=new Set(['codex']);S.devs=new Set(['PC']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
run(`S.devs.clear();S.projs=new Set(['Missing']);`);
assert.equal(run(`slice({from:'2026-10-10',to:'2026-10-10'}).sessions.length`),0);
run(`S.projs.clear();S.tools=new Set(['claude']);`);
console.log('Frontend regression checks passed: pricing, precision, scope, model contributions, Optimize, device distribution, shared refresh and compaction metadata.');
(async()=>{
  const accountNode={innerHTML:''}; let accountCalls=[], resolveAccountOld;
  const accountFixture=vm.createContext({Date,Number,Set,console,RAW:{device:{id:'local'}},S:{devs:new Set()},
    esc:value=>String(value??'').replaceAll('<','&lt;'),toolLabel:value=>value,
    document:{getElementById:()=>accountNode},askConfirm:async()=>false,
    fetch:async(url,options)=>{accountCalls.push({url,options});return {ok:true,json:async()=>({entries:[]})}}});
  vm.runInContext(views.slice(views.indexOf('let ACCOUNTS='),views.indexOf('function viewOverview(')),accountFixture);
  await vm.runInContext('loadAccounts()',accountFixture);
  await vm.runInContext('refreshAccount("codex")',accountFixture);
  assert.equal(accountCalls.length,1,'Declined consent ran a live lookup');
  assert.equal(accountCalls[0].options,undefined,'Local read unexpectedly posted a live lookup');
  accountFixture.askConfirm=async()=>true;
  accountFixture.fetch=async(url,options)=>{
    accountCalls.push({url,options});
    if(!options) return await new Promise(resolve=>{resolveAccountOld=resolve});
    return {ok:true,json:async()=>({entries:[{source:'codex',profile:'new-account',snapshots:[],identity:{auth:'apiKey'}}]})};
  };
  const oldAccountLoad=vm.runInContext('loadAccounts()',accountFixture);
  await vm.runInContext('refreshAccount("codex")',accountFixture);
  resolveAccountOld({ok:true,json:async()=>({entries:[{source:'codex',profile:'old-account',snapshots:[]}]})});
  await oldAccountLoad;
  assert.equal(vm.runInContext('ACCOUNTS.entries[0].profile',accountFixture),'new-account','Late GET undid a newer account lookup');
  assert.equal(JSON.parse(accountCalls.at(-1).options.body).confirmed,true);
  assert.equal(accountCalls.at(-1).options.headers['Content-Type'],'application/json');
  accountFixture.fetch=async()=>({ok:false});
  await vm.runInContext('loadAccounts()',accountFixture);
  assert.equal(vm.runInContext('ACCOUNTS.entries[0].profile',accountFixture),'new-account','Failed read dropped last successful account');
  assert.match(accountNode.innerHTML,/stale/i);
  // A failed opt-in lookup may have discarded a switched account on the server.
  // Re-read only local observations instead of indefinitely displaying its identity.
  accountCalls=[];
  accountFixture.fetch=async(url,options)=>{
    accountCalls.push({url,options});
    return options?{ok:false,json:async()=>({error:'Account changed during lookup'})}
      :{ok:true,json:async()=>({entries:[{source:'codex',profile:'current-profile',identity:null,snapshots:[]}]})};
  };
  await vm.runInContext('refreshAccount("codex")',accountFixture);
  assert.equal(accountCalls.length,2,'Failed lookup did not reconcile local account state');
  assert.equal(accountCalls[1].options,undefined,'Failure triggered another provider lookup');
  assert.doesNotMatch(accountNode.innerHTML,/new-account/,'Switched account remained visible after failure');
  assert.match(accountNode.innerHTML,/Account changed during lookup/);
  accountFixture.fetch=async(url,options)=>options
    ?{ok:false,json:async()=>({error:'Provider unavailable'})}
    :{ok:true,json:async()=>({entries:[{source:'codex',profile:'same-account',identity:{auth:'chatgpt'},snapshots:[]}]})};
  await vm.runInContext('refreshAccount("codex")',accountFixture);
  assert.match(accountNode.innerHTML,/same-account/,'Verified same-account failure discarded local state');
  assert.match(accountNode.innerHTML,/stale/i);
  accountFixture.fetch=async()=>{throw new Error('Dashboard unreachable')};
  await vm.runInContext('refreshAccount("codex")',accountFixture);
  assert.doesNotMatch(accountNode.innerHTML,/same-account/,'Unverified identity remained visible after failed reconciliation');
  assert.equal(vm.runInContext('accountBusy',accountFixture),false,'Failure left refresh disabled');
  assert.match(accountNode.innerHTML,/data-account-refresh="codex"/,'Failed reconciliation removed the retry control');
  vm.runInContext('S.devs.add("remote");renderAccountLimits()',accountFixture);
  assert.match(accountNode.innerHTML,/source device/);assert.doesNotMatch(accountNode.innerHTML,/new-account/);
  console.log('Account quota consent, privacy, stale values and superseded requests passed.');
  // A completed check must leave a way to check again without reloading.
  const versionNode={innerHTML:''}, updateRequests=[];
  let updateResult={behind:0,changes:[]};
  const updating=vm.createContext({RAW:{version:{git:true,commit:'fixture'}},esc:value=>String(value),
    document:{getElementById:()=>versionNode,addEventListener(){}},
    fetch:async(url,options)=>{updateRequests.push({url,options});return {ok:true,json:async()=>updateResult}}});
  vm.runInContext(views.slice(views.indexOf('let UPD ='),views.indexOf('/* ---------------- STORAGE')),updating);
  await vm.runInContext("updateAction('check')",updating);
  assert.match(versionNode.innerHTML,/Up to date/);
  assert.match(versionNode.innerHTML,/data-upd="check">Check for updates/);
  await vm.runInContext("updateAction('check')",updating);
  assert.equal(updateRequests.length,2,'Second update check did not issue a new request');
  for(const request of updateRequests){
    assert.equal(request.url,'/api/update');
    assert.equal(request.options.headers['Content-Type'],'application/json');
    assert.equal(JSON.parse(request.options.body).action,'check');
  }
  updateResult={behind:1,changes:['fixture update']};
  await vm.runInContext("updateAction('check')",updating);
  assert.match(versionNode.innerHTML,/data-upd="apply"/);
  assert.doesNotMatch(versionNode.innerHTML,/Up to date/);
  vm.runInContext("UPD={busy:'Checking…'};renderVersion()",updating);
  assert.doesNotMatch(versionNode.innerHTML,/data-upd=/,'Busy check allows duplicate clicks');
  vm.runInContext("UPD={error:'Offline'};renderVersion()",updating);
  assert.match(versionNode.innerHTML,/data-upd="check">Retry/);
  vm.runInContext("RAW.version.git=false;renderVersion()",updating);
  assert.doesNotMatch(versionNode.innerHTML,/data-upd=/,'Packaged build offers unsupported git update');
  console.log('Update checks remain repeatable after an up-to-date result.');
  let tick={seconds:15,revision:'first'}, loads=0, requested;
  const clock=vm.createContext({URLSearchParams,location:{search:''},document,console,S:{live:true},
    load:async()=>{loads++;return true},fetch:async(url,options)=>{requested=options; if(options){tick={seconds:JSON.parse(options.body).seconds,revision:'native-setting'};}return {ok:true,json:async()=>tick}}});
  vm.runInContext(syncCode,clock);
  await vm.runInContext('pollRefreshSync()',clock);
  await vm.runInContext('pollRefreshSync()',clock);
  assert.equal(loads,1,'Unchanged sync tick refetched the entire payload');
  tick={seconds:0,revision:'manual'};
  await vm.runInContext('pollRefreshSync()',clock);
  await vm.runInContext('pollRefreshSync()',clock);
  assert.equal(loads,2,'Manual mode updated without a new shared tick');
  tick={seconds:0,revision:'tray-refreshed'};
  await vm.runInContext('pollRefreshSync()',clock);
  assert.equal(loads,3,'Native manual refresh did not update the browser');
  await vm.runInContext('setPollMs(60000)',clock);
  assert.equal(JSON.parse(requested.body).seconds,60);
  assert.equal(vm.runInContext('pollMs()',clock),60000);
  vm.runInContext('S.live=false',clock); tick={seconds:15,revision:'paused'};
  await vm.runInContext('pollRefreshSync()',clock);
  assert.equal(loads,4,'Paused dashboard updated its figures');
  vm.runInContext('S.live=true',clock);
  let failed=true;
  clock.load=async()=>{loads++;if(failed){failed=false;return false;}return true};
  await vm.runInContext('pollRefreshSync()',clock);
  await vm.runInContext('pollRefreshSync()',clock);
  await vm.runInContext('pollRefreshSync()',clock);
  assert.equal(loads,6,'Failed payload did not retry on the same shared tick');
  console.log('Browser follows shared ticks, tray refreshes, Manual and Pause; setting writes use the guarded API.');
  // Execute the actual load function with delayed HTTP responses. A failed
  // payload remains retryable; an older response must not replace newer data.
  let resolveOld, pending=0, rendered=0;
  const payload=token=>({records:[{date:'2026-10-10',in:token}],meta:{last_refresh:1,files:1},device:{},pricing_note:''});
  const loadNodes={statusText:{},livedot:{classList:{add(){}}},coverage:{},devName:{},devOs:{},device:{},pricingNote:{}};
  const loading=vm.createContext({console,Date,Set,S:{live:true,devs:new Set()},RAW:null,
    document:{getElementById:id=>loadNodes[id],documentElement:{dataset:{}}},
    fetch:async()=>{pending++;if(pending===1)return await new Promise(resolve=>{resolveOld=resolve});return {ok:true,json:async()=>payload(200)}},
    devices:()=>[],renderVersion(){},loadAccounts(){},fmtNum:value=>value,renderAll(){rendered++}});
  vm.runInContext(views.slice(views.indexOf('let loadSequence='),views.indexOf('async function loadStorage()')),loading);
  const oldLoad=vm.runInContext('load()',loading);
  await vm.runInContext('load()',loading);
  resolveOld({ok:true,json:async()=>payload(100)});
  await oldLoad;
  assert.equal(vm.runInContext('RAW.records[0].in',loading),200);
  assert.equal(rendered,1,'Superseded payload rendered after a newer one');
  loading.console={error(){}};
  loading.fetch=async()=>({ok:false});
  assert.equal(await vm.runInContext('load()',loading),false);
  assert.equal(vm.runInContext('RAW.records[0].in',loading),200);
  console.log('Actual dashboard load discards superseded results and retains data on HTTP failure.');
  let state={supported:true,installed:true,running:false,requested:false,label:'Menu bar app',error:null};
  const nodes={nativeAppToggle:{dataset:{}},nativeAppMsg:{}};
  const box={dataset:{},isConnected:true,set innerHTML(value){nodes.nativeAppToggle={dataset:{}};nodes.nativeAppMsg={};}};
  const fixture=vm.createContext({esc:value=>String(value),
    document:{getElementById:id=>id==='nativeAppBox'?box:nodes[id]},
    fetch:async()=>({ok:true,json:async()=>state})});
  vm.runInContext(views.slice(views.indexOf('async function loadNativeSettings()'),views.indexOf('function renderSettings(')),fixture);
  await vm.runInContext('loadNativeSettings()',fixture);
  const toggle=nodes.nativeAppToggle;
  await vm.runInContext('loadNativeSettings()',fixture);
  assert.strictEqual(nodes.nativeAppToggle,toggle,'Idle status polling replaced the focused native toggle');
  state={...state,running:true,requested:true};
  await vm.runInContext('loadNativeSettings()',fixture);
  assert.notStrictEqual(nodes.nativeAppToggle,toggle,'Changed status was not rendered');
  console.log('Native Settings retains the toggle across unchanged status polls.');
})().catch(error=>{console.error(error);process.exitCode=1;});
