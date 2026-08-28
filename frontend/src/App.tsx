import {useEffect,useMemo,useState} from 'react'
import {ArrowRight,BadgeCheck,Bolt,Building2,CircleDollarSign,Gauge,Landmark,Radar,RotateCcw,ShieldCheck,Sparkles} from 'lucide-react'
import {api,AuditEvent,IntegrationStatus,Metrics,Opportunity,Provider,RankedOffer,RiskLedgerEntry,Settlement} from './api'
import CapitalAgents from './CapitalAgents'
import {money} from './format'

export {money} from './format'
const lifecycle=['Invoice','Verify','Assess risk','Discover','Compete','Match','Finance','Settle','Reallocate']
type Phase='idle'|'loading'|'ready'|'settling'|'settled'|'rerunning'|'completed'|'error'
type View='pulse'|'smart-match'|'opportunities'|'capital-agents'|'risk-ledger'
type AllocationHistory={sequence:number;invoice:string;provider:string;rate:number|null;amount:number|null;liquidityBefore?:number;liquidityAfter?:number;exposureBefore?:number;exposureAfter?:number}
type Receipt={settlement:Settlement;before:Provider;after:Provider}

const provenanceLabel=(status?:IntegrationStatus)=>status?.replace('_',' ')||'UNAVAILABLE'
const provenanceClass=(status?:IntegrationStatus)=>status==='SERVICE'?'service':status==='DEGRADED_FIXTURE'?'degraded':status==='FIXTURE'?'fixture':'unavailable'

export default function App(){
 const [view,setView]=useState<View>('pulse')
 const [ledgerEntries,setLedgerEntries]=useState<RiskLedgerEntry[]>([])
 const [opportunities,setOpportunities]=useState<Opportunity[]>([])
 const [opportunity,setOpportunity]=useState<Opportunity|null>(null)
 const [metrics,setMetrics]=useState<Metrics|null>(null)
 const [providers,setProviders]=useState<Provider[]>([])
 const [audit,setAudit]=useState<AuditEvent[]>([])
 const [history,setHistory]=useState<AllocationHistory[]>([])
 const [receipt,setReceipt]=useState<Receipt|null>(null)
 const [database,setDatabase]=useState<'sqlite'|'supabase-postgres'|null>(null)
 const [phase,setPhase]=useState<Phase>('idle')
 const [error,setError]=useState('')
 const [ledgerError,setLedgerError]=useState('')
 const [agentsError,setAgentsError]=useState('')
 const [opportunitiesError,setOpportunitiesError]=useState('')
 const [failedAction,setFailedAction]=useState<'run'|'settle'|'reallocate'>('run')
 const [reqAmount,setReqAmount]=useState<number>(800000)
 const [reqHours,setReqHours]=useState<number>(48)
 const [reqPriority,setReqPriority]=useState<'BALANCED'|'FASTEST'|'LOWEST_FEE'|'HIGHEST_ADVANCE'>('BALANCED')
 const offers=opportunity?.match?.ranked_offers||[]
 const winner=offers.find(x=>x.offer.id===opportunity?.match?.recommended_offer_id&&x.eligible)
 const offeredRates=offers.filter(x=>x.offer.status==='OFFER'&&x.offer.annual_rate!==null).map(x=>x.offer.annual_rate as number)
 const lowestRate=offeredRates.length?Math.min(...offeredRates):Number.NaN
 const busy=phase==='loading'||phase==='settling'||phase==='rerunning'
 const activeStep={idle:0,loading:3,ready:6,settling:7,settled:8,rerunning:4,completed:9,error:0}[phase]

 const refreshLedger=async()=>{const entries=await api.riskLedger();setLedgerEntries(entries);setLedgerError('')}
 useEffect(()=>{
  if(view==='risk-ledger')void refreshLedger().catch(e=>setLedgerError(e instanceof Error?e.message:'Risk ledger failed'))
  if(view==='opportunities')void api.opportunities().then(items=>{setOpportunities(items);setOpportunitiesError('')}).catch(e=>setOpportunitiesError(e instanceof Error?e.message:'Opportunity history failed'))
  if(view==='capital-agents')void api.providers().then(items=>{setProviders(items);setAgentsError('')}).catch(e=>setAgentsError(e instanceof Error?e.message:'Provider state failed'))
 },[view])
 const refresh=async()=>{
  const [nextMetrics,nextProviders,nextAudit,health]=await Promise.all([api.metrics(),api.providers(),api.audit(),api.health()])
  setMetrics(nextMetrics);setProviders(nextProviders);setAudit(nextAudit);setDatabase(health.database)
  void refreshLedger().catch(e=>setLedgerError(e instanceof Error?e.message:'Risk ledger failed'))
  return nextProviders
 }
 const run=async()=>{
  setError('');setPhase('loading');setOpportunity(null);setMetrics(null);setProviders([]);setAudit([]);setHistory([]);setReceipt(null);setDatabase(null);setLedgerEntries([])
  try{
   await api.reset()
   const scenarios=await api.scenarios()
   const created=await api.create(scenarios.urgent)
   const result=await api.run(created.id)
   setOpportunity(result)
   if(result.requirements){
    setReqAmount(result.requirements.minimum_amount)
    setReqHours(result.requirements.max_settlement_hours)
    setReqPriority(result.requirements.priority||'BALANCED')
   }
   await refresh()
   setPhase('ready')
  }catch(e){setFailedAction('run');setError(e instanceof Error?e.message:'Market failed');setPhase('error')}
 }

 const applySmartMatch=async(p?:'BALANCED'|'FASTEST'|'LOWEST_FEE'|'HIGHEST_ADVANCE',amt?:number,hrs?:number)=>{
  setPhase('loading');setError('')
  try{
   let targetOpp = opportunity
   if(!targetOpp){
    await api.reset()
    const scenarios=await api.scenarios()
    targetOpp=await api.create(scenarios.urgent)
   }
   const updatedReqs={
    minimum_amount:amt??reqAmount,
    max_settlement_hours:hrs??reqHours,
    desired_tenor_days:targetOpp.requirements?.desired_tenor_days||60,
    priority:p??reqPriority,
   }
   const result=await api.run(targetOpp.id,updatedReqs)
   setOpportunity(result);await refresh();setPhase('ready')
  }catch(e){
   setError(e instanceof Error?e.message:'Smart Match failed');setPhase('ready')
  }
 }

 const matchOpportunity=async(oppId:string)=>{
  setView('smart-match');setPhase('loading');setError('')
  try{
   const result=await api.run(oppId)
   setOpportunity(result)
   if(result.requirements){
    setReqAmount(result.requirements.minimum_amount)
    setReqHours(result.requirements.max_settlement_hours)
    setReqPriority(result.requirements.priority||'BALANCED')
   }
   await refresh()
   setPhase('ready')
  }catch(e){
   setError(e instanceof Error?e.message:'Smart Match failed');setPhase('ready')
  }
 }

 const settle=async()=>{
  if(!opportunity||!winner||phase!=='ready')return
  setError('');setPhase('settling')
  try{
   const before=providers.find(p=>p.id===winner.offer.provider_id)||(await api.providers()).find(p=>p.id===winner.offer.provider_id)
   if(!before)throw new Error('Recommended provider state is unavailable')
   const settlement=await api.settle(opportunity.id,winner.offer.id)
   const afterProviders=await refresh()
   const after=afterProviders.find(p=>p.id===winner.offer.provider_id)
   if(!after)throw new Error('Updated provider state is unavailable')
   setReceipt({settlement,before,after})
   setHistory([{sequence:1,invoice:opportunity.invoice.invoice_number,provider:winner.offer.provider_name,rate:winner.offer.annual_rate,amount:winner.offer.financed_amount,liquidityBefore:before.available_liquidity,liquidityAfter:after.available_liquidity,exposureBefore:before.current_exposure,exposureAfter:after.current_exposure}])
   setPhase('settled')
  }catch(e){setFailedAction('settle');setError(e instanceof Error?e.message:'Settlement failed');setPhase('ready')}
 }
 const reallocate=async()=>{
  if(phase!=='settled')return
  setError('');setPhase('rerunning')
  try{
   const scenarios=await api.scenarios()
   const created=await api.create(scenarios.strong)
   const result=await api.run(created.id)
   const nextWinner=result.match?.ranked_offers.find(x=>x.offer.id===result.match?.recommended_offer_id&&x.eligible)
   setOpportunity(result);await refresh()
   if(nextWinner)setHistory(previous=>[...previous,{sequence:2,invoice:result.invoice.invoice_number,provider:nextWinner.offer.provider_name,rate:nextWinner.offer.annual_rate,amount:nextWinner.offer.financed_amount}])
   setPhase('completed')
  }catch(e){setFailedAction('reallocate');setError(e instanceof Error?e.message:'Reallocation failed');setPhase('settled')}
 }
 const primaryAction=phase==='settled'?reallocate:run
 const retryAction=failedAction==='settle'?settle:failedAction==='reallocate'?reallocate:run
 const primaryLabel=phase==='loading'?'Agents are competing':phase==='settling'?'Settlement in progress':phase==='rerunning'?'Reallocating capital':phase==='settled'?'Run next allocation':phase==='completed'?'Restart flagship demo':'Run flagship market'
 const agentLatency=useMemo(()=>busy?'clearing now…':opportunity?'backend decision received':'waiting for first allocation',[busy,opportunity])
 const invoice=opportunity?.invoice
 const req=opportunity?.requirements
 const risk=opportunity?.evaluation?.risk
 const verification=opportunity?.evaluation?.verification

 return <div className="shell"><aside className="rail"><div className="brand"><span>P</span><div>PRATIN<small>CAPITAL NETWORK</small></div></div><nav><button className={view==='pulse'?'active':''} onClick={()=>setView('pulse')}><Gauge/>Market pulse</button><button className={view==='smart-match'?'active':''} onClick={()=>setView('smart-match')}><Sparkles/>Smart funding match</button><button className={view==='opportunities'?'active':''} onClick={()=>setView('opportunities')}><Radar/>Opportunities</button><button className={view==='capital-agents'?'active':''} onClick={()=>setView('capital-agents')}><Landmark/>Capital agents</button><button className={view==='risk-ledger'?'active':''} onClick={()=>setView('risk-ledger')}><ShieldCheck/>Risk ledger</button></nav><div className="rail-foot"><span className="live-dot"/> MARKET READY<small>Synthetic demo • No real funds</small></div></aside>
 {view==='smart-match'?<SmartFundingMatch opportunity={opportunity} onApply={applySmartMatch} busy={busy} lowestRate={lowestRate} error={error} reqAmount={reqAmount} reqHours={reqHours} reqPriority={reqPriority} setReqAmount={setReqAmount} setReqHours={setReqHours} setReqPriority={setReqPriority}/>:view==='opportunities'?<Opportunities items={opportunities} error={opportunitiesError} onMatchOpportunity={matchOpportunity}/>:view==='capital-agents'?<CapitalAgents providers={providers} error={agentsError}/>:view==='risk-ledger'?<RiskLedger entries={ledgerEntries} error={ledgerError} onRefresh={()=>void refreshLedger()} onMatchOpportunity={matchOpportunity}/>:<main><header><div><p className="eyebrow">REQUEST-DRIVEN CLEARING • STATEFUL DEMO MARKET</p><h1>Capital, intelligently <em>allocated.</em></h1><p className="lede">Every verified invoice enters a competitive market where autonomous providers price risk, protect portfolios and race to satisfy the supplier.</p></div><button className="primary" onClick={()=>primaryAction()} disabled={busy}>{busy?<RotateCcw className="spin"/>:<Bolt/>}{primaryLabel}</button></header>
 {error&&<div className="error-banner" role="alert"><strong>Request failed.</strong> {error} <button onClick={retryAction} disabled={busy}>Retry safely</button></div>}
 <section className="provenance" aria-label="Integration provenance"><div><small>INVOICE / RISK AGENT</small><span className={provenanceClass(opportunity?.integration_status.invoice_risk)}>● {provenanceLabel(opportunity?.integration_status.invoice_risk)}</span></div><div><small>CAPITAL MARKET AGENTS</small><span className={provenanceClass(opportunity?.integration_status.capital_market)}>● {provenanceLabel(opportunity?.integration_status.capital_market)}</span></div><div><small>MARKET STATE</small><span className={database==='supabase-postgres'?'service':database?'fixture':'unavailable'}>● {database==='supabase-postgres'?'SUPABASE POSTGRES':database==='sqlite'?'SQLITE OFFLINE':'UNAVAILABLE'}</span></div><p>{!opportunity?'No market response received yet.':Object.values(opportunity.integration_status).includes('DEGRADED_FIXTURE')?'A service was unavailable; deterministic fixtures are clearly shown.':Object.values(opportunity.integration_status).every(x=>x==='SERVICE')?'Both responses came through validated HTTP service contracts.':'Deterministic fixture mode is active; these are not external service responses.'}</p></section>
 <section className="ticker">{lifecycle.map((x,i)=><div key={x} className={i<activeStep?'done':i===activeStep?'now':''}><span>{i<activeStep?'✓':i+1}</span>{x}{i<lifecycle.length-1&&<ArrowRight/>}</div>)}</section>
 <section className="metrics"><article><small>DEPLOYABLE CAPITAL</small><strong>{metrics?money(metrics.available_liquidity):'—'}</strong><p>{metrics?'Backend marketplace state':'Available after first market run'}</p></article><article><small>ACTIVE OPPORTUNITIES</small><strong>{metrics?.active_opportunities??'—'}</strong><p>{metrics?`${metrics.settlements} simulated settlements`:'No backend metrics loaded'}</p></article><article><small>OFFERS GENERATED</small><strong>{metrics?.offers_generated??'—'}</strong><p>{metrics?`${Math.round(metrics.provider_participation_rate*100)}% provider participation`:'No fabricated offer totals'}</p></article><article><small>CAPITAL ALLOCATED</small><strong>{metrics?money(metrics.financing_allocated):'—'}</strong><p>{metrics?'Derived from settlement ledger':'Waiting for settlement'}</p></article></section>

 <section className="smart-match-panel" style={{background:'#f3f7f4',border:'1px solid #c7d8cb',borderRadius:4,padding:'16px 20px',margin:'16px 0'}}>
  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:12}}>
   <div>
    <span className="eyebrow" style={{color:'#204b3e',fontWeight:700}}><Sparkles style={{width:13,verticalAlign:'middle',marginRight:4}}/> SMART FUNDING MATCH & CUSTOMIZED SUGGESTION</span>
    <h3 style={{margin:'4px 0 0',fontSize:15}}>Specify Your Funding Requirements & Priority</h3>
    <p style={{fontSize:11,color:'#526c63',margin:'2px 0 0'}}>Our deterministic matching engine evaluates all eligible providers and tailors the recommendation to your exact needs.</p>
   </div>
   <div style={{display:'flex',gap:10,alignItems:'center',flexWrap:'wrap'}}>
    <div>
     <label style={{fontSize:10,color:'#5a6e67',display:'block',fontWeight:600}}>AMOUNT NEEDED</label>
     <input type="number" step="50000" min="50000" max={invoice?.amount||2000000} value={reqAmount} onChange={e=>setReqAmount(Number(e.target.value))} style={{padding:'4px 8px',fontSize:12,border:'1px solid #b2c5b7',borderRadius:3,width:120}}/>
    </div>
    <div>
     <label style={{fontSize:10,color:'#5a6e67',display:'block',fontWeight:600}}>DEADLINE</label>
     <select value={reqHours} onChange={e=>setReqHours(Number(e.target.value))} style={{padding:'4px 8px',fontSize:12,border:'1px solid #b2c5b7',borderRadius:3}}>
      <option value={2}>2 Hours (Instant)</option>
      <option value={24}>24 Hours (1 Day)</option>
      <option value={48}>48 Hours (2 Days)</option>
      <option value={96}>96 Hours (4 Days)</option>
     </select>
    </div>
    <div>
     <label style={{fontSize:10,color:'#5a6e67',display:'block',fontWeight:600}}>PRIORITY</label>
     <select value={reqPriority} onChange={e=>setReqPriority(e.target.value as any)} style={{padding:'4px 8px',fontSize:12,border:'1px solid #b2c5b7',borderRadius:3,fontWeight:600}}>
      <option value="BALANCED">Balanced</option>
      <option value="FASTEST">Fastest Funding</option>
      <option value="LOWEST_FEE">Lowest Fee</option>
      <option value="HIGHEST_ADVANCE">Highest Advance</option>
     </select>
    </div>
    <button className="primary" onClick={()=>opportunity?void applySmartMatch():void run()} disabled={busy} style={{alignSelf:'flex-end',padding:'6px 14px',fontSize:12}}>
     {busy?<RotateCcw className="spin"/>:<Bolt/>} Find Best Offer
    </button>
   </div>
  </div>
 </section>

 {!opportunity?<section className="empty-market"><Sparkles/><div><p className="eyebrow">MARKETPLACE READY</p><h2>No allocation has run yet.</h2><p>Click <strong>Find Best Offer</strong> above or <strong>Run flagship market</strong> to request real backend verification, provider offers and tailored recommendations.</p></div></section>:<>
 <div className="section-head"><div><p className="eyebrow">{phase==='completed'?'SECOND ALLOCATION':'BACKEND MARKET'} • {opportunity.id}</p><h2>{invoice?.supplier_name} seeks {money(req?.minimum_amount||0)} within {req?.max_settlement_hours} hours</h2></div><div className="risk"><span>{risk?.band} RISK</span><b>{risk?.score}</b><small>/100</small></div></div>

 <section className="market-grid"><article className="invoice-card"><div className="card-label"><BadgeCheck/> {verification?.status} OPPORTUNITY</div><h3>{invoice?.invoice_number}</h3><p>{invoice?.buyer_name} → {invoice?.supplier_name}</p><div className="invoice-total"><small>INVOICE VALUE</small><strong>{money(invoice?.amount||0)}</strong></div><dl><div><dt>Minimum capital</dt><dd>{money(req?.minimum_amount||0)}</dd></div><div><dt>Settlement ceiling</dt><dd>{req?.max_settlement_hours} hours</dd></div><div><dt>Desired tenor</dt><dd>{req?.desired_tenor_days} days</dd></div><div><dt>Verification confidence</dt><dd>{Math.round((verification?.confidence||0)*100)}%</dd></div></dl><footer><ShieldCheck/> Synthetic verification clearly labelled</footer></article>
 <div className="arena"><div className="arena-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i/> {agentLatency}</span></div><div className="provider-list">{offers.map(r=><ProviderOffer key={r.offer.id} ranked={r} winnerId={winner?.offer.id} lowestRate={lowestRate}/>)}</div></div></section>
 <section className="decision">
  <div>
   <p className="eyebrow">{phase==='completed'?'ADAPTIVE REALLOCATION COMPLETE':receipt?'MARKET STATE UPDATED':'EXPLAINABLE BACKEND DECISION'}</p>
   <h2>{winner?`${phase==='completed'?`${winner.offer.provider_name} wins allocation two after provider state changed.`:`BEST MATCH: ${winner.offer.provider_name}`}`:'No provider currently satisfies every mandate.'}</h2>
   {winner&&(
    <div style={{display:'flex',gap:16,margin:'10px 0',fontSize:12,color:'#204b3e',fontWeight:600}}>
     <span>⚡ Settlement: {winner.offer.settlement_hours}h</span>
     <span>💰 Advance: {((winner.offer.advance_rate||0)*100).toFixed(0)}% ({money(winner.offer.financed_amount||0)})</span>
     <span>🏷️ Est. Fee: {money(winner.offer.fees||0)}</span>
     <span>📈 Rate: {winner.offer.annual_rate}%</span>
    </div>
   )}
   <div style={{marginTop:12}}>
    <strong style={{fontSize:11,textTransform:'uppercase',letterSpacing:'0.04em',color:'#5a6e67',display:'block',marginBottom:4}}>Why this is the best match:</strong>
    <ul style={{margin:'0 0 10px 0',paddingLeft:18,fontSize:12,lineHeight:1.6}}>
     {opportunity.match?.recommendation_reasons.map((r,i)=><li key={i}>✓ {r}</li>)}
    </ul>
   </div>
   {opportunity.match?.tradeoffs&&opportunity.match.tradeoffs.length>0&&(
    <div style={{marginTop:8,padding:'8px 12px',background:'#fafafa',border:'1px solid #e5e5e5',borderRadius:4}}>
     <strong style={{fontSize:10,textTransform:'uppercase',letterSpacing:'0.04em',color:'#737373',display:'block',marginBottom:2}}>Trade-off & Alternatives:</strong>
     <ul style={{margin:0,paddingLeft:16,fontSize:11,color:'#525252',lineHeight:1.5}}>
      {opportunity.match.tradeoffs.map((t,i)=><li key={i}>{t}</li>)}
     </ul>
    </div>
   )}
   <div style={{marginTop:12,display:'flex',gap:12,fontSize:11,color:'#4b6358',flexWrap:'wrap'}}>
    <span>✓ Amount: {money(req?.minimum_amount||0)}</span>
    <span>✓ Deadline: {req?.max_settlement_hours}h</span>
    <span>✓ Priority: {req?.priority||'BALANCED'}</span>
    <span>✓ Risk Band: {risk?.band} ({risk?.score}/100)</span>
   </div>
  </div>
  {winner&&<div className="score-ring"><strong>{winner.suitability_score}</strong><small>SUITABILITY</small></div>}
  {phase==='ready'&&winner&&<button className="settle" onClick={settle} disabled={busy}>Accept & simulate settlement <ArrowRight/></button>}
 </section>
 </>}

 {receipt&&<section className="settlement-proof"><div><p className="eyebrow">SIMULATED SETTLEMENT • {receipt.settlement.id}</p><h2>One atomic write changed the next market.</h2><p>{receipt.settlement.notice}</p></div><dl><div><dt>Provider liquidity</dt><dd>{money(receipt.before.available_liquidity)} <ArrowRight/> <strong>{money(receipt.after.available_liquidity)}</strong></dd></div><div><dt>Provider exposure</dt><dd>{money(receipt.before.current_exposure)} <ArrowRight/> <strong>{money(receipt.after.current_exposure)}</strong></dd></div></dl></section>}
 {history.length>0&&<section className="allocation-history"><p className="eyebrow">CAUSAL ALLOCATION HISTORY</p><div className="history-flow">{history.map((item,index)=><div key={item.sequence} className="history-item"><small>ALLOCATION {item.sequence}</small><strong>{item.provider}</strong><span>{item.invoice} • {item.amount?money(item.amount):'—'} • {item.rate??'—'}%</span>{item.liquidityBefore!==undefined&&<em>Liquidity {money(item.liquidityBefore)} → {money(item.liquidityAfter||0)}</em>}{index<history.length-1&&<ArrowRight/>}</div>)}</div>{history.length===1&&phase==='settled'&&<p className="history-hint">Provider liquidity and exposure changed. Run the next allocation to see the market adapt.</p>}{history.length===2&&<p className="history-hint success">VegaFlow → state mutation → Meridian. The second winner changed because settlement changed provider capacity.</p>}</section>}
 {audit.length>0&&<section className="audit-timeline"><p className="eyebrow">RECENT BACKEND AUDIT EVENTS</p>{audit.slice(0,4).map(event=><div key={event.id}><span>{event.event_type.replaceAll('_',' ')}</span><p>{event.detail}</p><small>{event.id}</small></div>)}</section>}
 </main>}
 </div>
}

function Opportunities({items,error,onMatchOpportunity}:{items:Opportunity[];error:string;onMatchOpportunity?:(id:string)=>void}){
 return <main><header><div><p className="eyebrow">DURABLE BACKEND HISTORY • SYNTHETIC DEMO</p><h1>Financing <em>opportunities.</em></h1><p className="lede">Invoices admitted to the market remain visible with their current lifecycle state and backend recommendation.</p></div></header>
 {error&&<div className="error-banner" role="alert">Opportunities unavailable: {error}</div>}
 <section className="opportunity-grid">{items.length===0?<div className="empty-ledger">No opportunities exist yet. Run the flagship market from Market pulse.</div>:items.map(item=>{const winner=item.match?.ranked_offers.find(r=>r.offer.id===item.match?.recommended_offer_id);return <article className="opportunity-card" key={item.id}><div><small>{item.status.replaceAll('_',' ')} • {item.id}</small><h3>{item.invoice.invoice_number}</h3><p>{item.invoice.supplier_name} → {item.invoice.buyer_name}</p></div><dl><div><dt>Invoice value</dt><dd>{money(item.invoice.amount)}</dd></div><div><dt>Minimum capital</dt><dd>{money(item.requirements.minimum_amount)}</dd></div><div><dt>Recommendation</dt><dd>{winner?.offer.provider_name||'Not cleared'}</dd></div><div><dt>Created</dt><dd>{new Date(item.created_at).toLocaleString()}</dd></div></dl>{onMatchOpportunity&&<button className="primary" onClick={()=>onMatchOpportunity(item.id)} style={{marginTop:12,fontSize:11,padding:'4px 10px'}}><Sparkles style={{width:13,verticalAlign:'middle',marginRight:4}}/> Smart Match This Opportunity</button>}</article>})}</section>
 </main>
}

function RiskLedger({entries,error,onRefresh,onMatchOpportunity}:{entries:RiskLedgerEntry[];error:string;onRefresh?:()=>void;onMatchOpportunity?:(id:string)=>void}){
 const [file,setFile]=useState<File|null>(null)
 const [uploading,setUploading]=useState(false)
 const [uploadError,setUploadError]=useState('')
 const [uploadResult,setUploadResult]=useState<any>(null)

 const handleUpload=async()=>{
  if(!file)return
  setUploading(true);setUploadError('');setUploadResult(null)
  try{
   const result=await api.parseInvoicePdf(file)
   setUploadResult(result)
   if(onRefresh)onRefresh()
  }catch(e){
   setUploadError(e instanceof Error?e.message:'PDF upload failed')
  }finally{
   setUploading(false)
  }
 }

 return <main><header><div><p className="eyebrow">DURABLE AUDIT • EXPLAINABLE EVALUATIONS</p><h1>Invoice Risk <em>Ledger.</em></h1><p className="lede">Upload and parse PDF invoices with deterministic field extraction, or review durably logged evaluations with factor-level explainability and explicit provenance.</p></div>{onRefresh&&<button className="primary" onClick={onRefresh}><RotateCcw/> Refresh ledger</button>}</header>
 {error&&<div className="error-banner" role="alert">Risk ledger unavailable: {error}</div>}

 <section className="pdf-upload-card" style={{background:'#f8faf6',border:'1px solid #d2ddd4',padding:20,margin:'20px 0',borderRadius:4}}>
  <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:12}}>
   <div>
    <div className="card-label"><ShieldCheck/> PDF INVOICE EXTRACTION & UNDERWRITING</div>
    <h3 style={{fontSize:16,margin:'6px 0 2px'}}>Upload Invoice PDF</h3>
    <p style={{fontSize:11,color:'#61736d',margin:0}}>Extracts invoice fields deterministically and runs the existing risk engine.</p>
   </div>
   <div style={{display:'flex',gap:8,alignItems:'center'}}>
    <input type="file" accept=".pdf,application/pdf" onChange={e=>setFile(e.target.files?.[0]||null)} style={{fontSize:11}}/>
    <button className="primary" onClick={handleUpload} disabled={!file||uploading}>
     {uploading?<RotateCcw className="spin"/>:<Bolt/>} {uploading?'Parsing PDF…':'Extract & Evaluate'}
    </button>
   </div>
  </div>

  {uploadError&&<div className="error-banner" style={{marginTop:12}} role="alert">{uploadError}</div>}

  {uploadResult&&(
   <div style={{marginTop:16,paddingTop:14,borderTop:'1px solid #e2e8e1'}}>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:10}}>
     <div>
      <span className="eyebrow">EXTRACTION STATUS: {uploadResult.status}</span>
      {uploadResult.extracted_fields?.extraction_confidence&&(
       <span className="verified-tag" style={{marginLeft:8,background:uploadResult.extracted_fields.extraction_confidence==='HIGH'?'#edf8ee':uploadResult.extracted_fields.extraction_confidence==='MEDIUM'?'#fffbeb':'#fef2f2',color:uploadResult.extracted_fields.extraction_confidence==='HIGH'?'#2e6935':uploadResult.extracted_fields.extraction_confidence==='MEDIUM'?'#92400e':'#991b1b',borderColor:'currentColor'}}>
        {uploadResult.extracted_fields.extraction_confidence} CONFIDENCE
       </span>
      )}
     </div>
     {uploadResult.evaluation&&<div className="risk"><span>{uploadResult.evaluation.risk.band} RISK</span><b>{uploadResult.evaluation.risk.score}</b><small>/100</small></div>}
    </div>

    {uploadResult.extracted_fields&&(
     <dl style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(200px,1fr))',gap:10,margin:'10px 0',fontSize:11}}>
      <div><dt style={{color:'#7b8d86'}}>Invoice #</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.invoice_number||'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>Supplier</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.supplier_name||'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>Buyer</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.buyer_name||'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>Amount</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.amount?money(uploadResult.extracted_fields.amount):'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>Issue Date</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.issue_date||'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>Due Date</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.due_date||'—'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>GSTIN</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.gstin||'Missing'}</dd></div>
      <div><dt style={{color:'#7b8d86'}}>PO Reference</dt><dd style={{fontWeight:700}}>{uploadResult.extracted_fields.purchase_order_reference||'Missing'}</dd></div>
     </dl>
    )}

    {uploadResult.extracted_fields?.missing_fields?.length>0&&(
     <div className="tag-list" style={{marginTop:8}}>
      <span className="eyebrow" style={{marginRight:8}}>MISSING FROM PDF:</span>
      {uploadResult.extracted_fields.missing_fields.map((f:string)=><span key={f} className="uncertainty-tag">{f}</span>)}
     </div>
    )}

    {uploadResult.ledger_entry?.opportunity_id&&onMatchOpportunity&&(
     <div style={{marginTop:14,paddingTop:12,borderTop:'1px dashed #c7d8cb'}}>
      <button className="primary" onClick={()=>onMatchOpportunity(uploadResult.ledger_entry.opportunity_id)} style={{fontSize:11,padding:'6px 14px'}}>
       <Sparkles style={{width:13,verticalAlign:'middle',marginRight:4}}/> Match with Capital Providers (Smart Funding Match) →
      </button>
     </div>
    )}
   </div>
  )}
 </section>

 <section className="ledger-grid">
  {entries.length===0?<div className="empty-ledger">No risk evaluations in the ledger yet. Run the market from Market pulse or upload a PDF invoice above to generate evaluation history.</div>:entries.map(entry=><RiskEntryCard key={entry.id} entry={entry} onMatchOpportunity={onMatchOpportunity}/>)}
 </section>
</main>
}

function RiskEntryCard({entry,onMatchOpportunity}:{entry:RiskLedgerEntry;onMatchOpportunity?:(id:string)=>void}){
 const [simulation,setSimulation]=useState<any>(null)
 const [simBusy,setSimBusy]=useState(false)
 const [simError,setSimError]=useState('')

 const summary=entry.risk.summary
 const reducers=summary?.top_risk_reducers?.length?summary.top_risk_reducers:entry.risk.factors.filter(f=>f.points<0).sort((a,b)=>a.points-b.points)
 const contributors=summary?.top_risk_contributors?.length?summary.top_risk_contributors:entry.risk.factors.filter(f=>f.points>0).sort((a,b)=>b.points-a.points)

 const runSimulation=async(req:any)=>{
  setSimBusy(true);setSimError('')
  try{
   const res=await api.simulateRisk(entry.id,req)
   setSimulation(res)
  }catch(e){
   setSimError(e instanceof Error?e.message:'Simulation failed')
  }finally{
   setSimBusy(false)
  }
 }

 return (
  <article className="ledger-entry" key={entry.id}>
   <div className="ledger-header">
    <div>
     <div className="card-label">
      <BadgeCheck/> {entry.verification.status} • {Math.round(entry.verification.confidence*100)}% CONFIDENCE • {entry.id}{' '}
      {entry.source==='PDF_UPLOAD'&&<span className="verified-tag" style={{marginLeft:6}}>PDF UPLOAD {entry.source_filename?`(${entry.source_filename})`:''}</span>}
     </div>
     <h3>{entry.invoice_number} — {money(entry.amount)}</h3>
     <p>{entry.supplier_name} → {entry.buyer_name} • Evaluated {new Date(entry.evaluated_at).toLocaleString()}</p>
    </div>
    <div className="risk">
     <span>{entry.risk.band} RISK</span>
     <b>{entry.risk.score}</b>
     <small>/100</small>
    </div>
   </div>

   {entry.verification.duplicate_check?.duplicate_detected&&(
    <div style={{background:'#fef2f2',border:'1px solid #f87171',color:'#991b1b',padding:'8px 12px',borderRadius:4,marginBottom:12,fontSize:11}}>
     <strong style={{display:'block',marginBottom:2}}>⚠️ DUPLICATE DETECTED — Matched: {entry.verification.duplicate_check.matched_invoice_number}</strong>
     <span>Reasons: {entry.verification.duplicate_check.reasons.join(' • ')}</span>
    </div>
   )}

   {entry.verification.consistency_warnings&&entry.verification.consistency_warnings.length>0&&(
    <div style={{background:'#fffbeb',border:'1px solid #fbbf24',color:'#92400e',padding:'8px 12px',borderRadius:4,marginBottom:12,fontSize:11}}>
     <strong style={{display:'block',marginBottom:2}}>⚠️ CONSISTENCY WARNING</strong>
     {entry.verification.consistency_warnings.map(w=><div key={w}>{w}</div>)}
    </div>
   )}

   {/* 1. RISK DECISION SUMMARY */}
   <div style={{background:'#f3f7f4',border:'1px solid #c8d8cc',borderRadius:4,padding:'14px 16px',marginBottom:14}}>
    <div className="eyebrow" style={{color:'#204b3e',marginBottom:4}}>RISK DECISION & EXPLANATION</div>
    <p style={{margin:'0 0 10px 0',fontSize:12,fontWeight:600,color:'#1b3d32',lineHeight:1.5}}>
     {summary?.human_readable_explanation||`This invoice is evaluated as ${entry.risk.band} risk (${entry.risk.score}/100) based on evaluated factors.`}
    </p>

    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(240px,1fr))',gap:14,paddingTop:10,borderTop:'1px solid #d8e5dc'}}>
     <div>
      <strong style={{fontSize:10,textTransform:'uppercase',letterSpacing:'0.04em',color:'#8c3f35',display:'block',marginBottom:4}}>
       TOP RISK CONTRIBUTORS (+ POINTS)
      </strong>
      {contributors.length===0?(
       <span style={{fontSize:11,color:'#688077'}}>No elevated positive risk contributors.</span>
      ):(
       <ul style={{margin:0,paddingLeft:16,fontSize:11,color:'#8c3f35',lineHeight:1.5}}>
        {contributors.map((c,i)=>(
         <li key={i}>
          <strong>+{c.points}</strong> {c.label} <span style={{color:'#666',fontSize:10}}>({c.explanation})</span>
         </li>
        ))}
       </ul>
      )}
     </div>

     <div>
      <strong style={{fontSize:10,textTransform:'uppercase',letterSpacing:'0.04em',color:'#2e6935',display:'block',marginBottom:4}}>
       RISK REDUCERS (- POINTS)
      </strong>
      {reducers.length===0?(
       <span style={{fontSize:11,color:'#688077'}}>No risk-reducing factors identified.</span>
      ):(
       <ul style={{margin:0,paddingLeft:16,fontSize:11,color:'#2e6935',lineHeight:1.5}}>
        {reducers.map((r,i)=>(
         <li key={i}>
          <strong>{r.points}</strong> {r.label} <span style={{color:'#666',fontSize:10}}>({r.explanation})</span>
         </li>
        ))}
       </ul>
      )}
     </div>
    </div>
   </div>

   {/* 2. FACTOR-LEVEL EXPLAINABILITY */}
   <div className="eyebrow">ALL FACTOR-LEVEL EXPLAINABILITY ({entry.risk.factors.length} FACTORS)</div>
   <div className="ledger-factors">
    {entry.risk.factors.map(factor=>(
     <div key={factor.label} className={`factor-card ${factor.impact}`}>
      <div className="factor-title">
       <span>{factor.label}</span>
       <b>{factor.points>0?`+${factor.points}`:factor.points}</b>
      </div>
      {factor.reason_code&&(
       <div style={{fontSize:9,fontWeight:700,letterSpacing:'0.04em',color:factor.impact==='positive'?'#2e6935':factor.impact==='negative'?'#8c3f35':'#526c63',marginBottom:4}}>
        {factor.reason_code}
       </div>
      )}
      <p className="factor-desc">{factor.explanation}</p>
     </div>
    ))}
   </div>

   {/* 3. WHAT-IF ANALYSIS */}
   <div style={{marginTop:16,padding:'14px 16px',background:'#fafbfc',border:'1px solid #d8e2dc',borderRadius:4}}>
    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:8,marginBottom:8}}>
     <div>
      <span className="eyebrow" style={{color:'#1c4d3e'}}><Bolt style={{width:12,verticalAlign:'middle',marginRight:4}}/> WHAT-IF RISK ANALYSIS (SIMULATION)</span>
      <p style={{margin:'2px 0 0',fontSize:11,color:'#556b63'}}>See how changing invoice/buyer conditions would deterministically affect the risk score and band.</p>
     </div>
     {simulation&&(
      <button className="primary" onClick={()=>setSimulation(null)} style={{fontSize:10,padding:'3px 8px',background:'#5a6e67'}}>
       Reset simulation
      </button>
     )}
    </div>

    <div style={{display:'flex',gap:8,flexWrap:'wrap',margin:'10px 0'}}>
     <button
      type="button"
      className="primary"
      onClick={()=>void runSimulation({scenario_name:'Duplicate Invoice Scenario',simulate_duplicate:true})}
      disabled={simBusy}
      style={{fontSize:11,padding:'5px 10px',background:'#8c3f35'}}
     >
      ⚠️ Simulate Duplicate (+35)
     </button>
     <button
      type="button"
      className="primary"
      onClick={()=>void runSimulation({scenario_name:'Lower Payment History (60%)',simulated_on_time_payment_ratio:0.60})}
      disabled={simBusy}
      style={{fontSize:11,padding:'5px 10px',background:'#a05e20'}}
     >
      📉 Simulate Lower Payment History (60%)
     </button>
     <button
      type="button"
      className="primary"
      onClick={()=>void runSimulation({scenario_name:'Large Invoice Amount (₹5M)',simulated_amount:5000000.0})}
      disabled={simBusy}
      style={{fontSize:11,padding:'5px 10px',background:'#2c5e50'}}
     >
      📈 Simulate Higher Amount (₹5M)
     </button>
     <button
      type="button"
      className="primary"
      onClick={()=>void runSimulation({scenario_name:'Urgent Maturity Tenor (10d)',simulated_days_until_due:10})}
      disabled={simBusy}
      style={{fontSize:11,padding:'5px 10px',background:'#2c5e50'}}
     >
      ⏳ Simulate Urgent Maturity (10d)
     </button>
     <button
      type="button"
      className="primary"
      onClick={()=>void runSimulation({scenario_name:'Verification Uncertainty',simulated_verification_status:'PARTIALLY_VERIFIED'})}
      disabled={simBusy}
      style={{fontSize:11,padding:'5px 10px',background:'#526c63'}}
     >
      ❓ Simulate Uncertainty (+12)
     </button>
    </div>

    {simError&&<div className="error-banner" style={{fontSize:11,margin:'8px 0'}}>{simError}</div>}

    {simulation&&(
     <div style={{marginTop:10,padding:'12px 14px',background:'#fff',border:'1px solid #bad2c2',borderRadius:4}}>
      <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',flexWrap:'wrap',gap:8,marginBottom:6}}>
       <span className="eyebrow" style={{color:'#204b3e'}}>SIMULATION RESULT: {simulation.scenario_name}</span>
       <span style={{fontSize:12,fontWeight:700,color:simulation.score_delta>0?'#8c3f35':simulation.score_delta<0?'#2e6935':'#526c63'}}>
        Score: {simulation.original_score} ({simulation.original_band}) → {simulation.simulated_score} ({simulation.simulated_band}) [{simulation.score_delta>0?'+':''}{simulation.score_delta} pts]
       </span>
      </div>
      <p style={{margin:'4px 0 8px 0',fontSize:12,color:'#334d43',fontWeight:500}}>
       {simulation.explanation}
      </p>
      {simulation.modified_factors&&simulation.modified_factors.length>0&&(
       <div style={{fontSize:11,color:'#556e64'}}>
        <strong>Modified Factors:</strong> {simulation.modified_factors.map((f:any)=>`${f.label} (${f.points>0?'+':''}${f.points} pts - ${f.explanation})`).join(' • ')}
       </div>
      )}
     </div>
    )}
   </div>

   <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginTop:12,flexWrap:'wrap',gap:8}}>
    {entry.opportunity_id&&onMatchOpportunity&&(
     <button className="primary" onClick={()=>onMatchOpportunity(entry.opportunity_id!)} style={{fontSize:11,padding:'5px 12px',background:'#2e6935'}}>
      <Sparkles style={{width:12,verticalAlign:'middle',marginRight:4}}/> Smart Match This Invoice
     </button>
    )}
    <footer style={{fontSize:10,color:'#719087',margin:0}}>
     <ShieldCheck style={{width:14,verticalAlign:'middle',marginRight:4}}/> Policy: {entry.risk.policy_version} • Provenance: {entry.provenance} • Deterministic what-if simulation enabled
    </footer>
   </div>
  </article>
 )
}

function ProviderOffer({ranked,winnerId,lowestRate}:{ranked:RankedOffer;winnerId?:string;lowestRate:number}){
 const o=ranked.offer,isWinner=o.id===winnerId,isLowest=o.annual_rate===lowestRate
 return <article className={`provider ${isWinner?'winner':''} ${!ranked.eligible?'ineligible':''}`}><div className="provider-title"><div className="provider-icon">{o.provider_type==='BANK'?<Building2/>:o.provider_type==='FINTECH'?<CircleDollarSign/>:<Landmark/>}</div><div><h3>{o.provider_name}</h3><small>{o.provider_type} AGENT • {o.status}</small></div><div className="offer-badges">{isLowest&&<b className="lowest">LOWEST RATE</b>}{isWinner&&<b>RECOMMENDED</b>}{!ranked.eligible&&<b className="bad">INELIGIBLE</b>}</div></div><div className="offer-stats"><div><small>RATE</small><strong>{o.annual_rate!==null?`${o.annual_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>{ranked.hard_constraint_failures.length?<p className="fail">× {ranked.hard_constraint_failures.join(' • ')}</p>:<p className={isWinner?'pass':'neutral'}>{isWinner?'✓ Satisfies every supplier hard constraint':`Rank #${ranked.rank}`} • {ranked.suitability_score}/100 suitability</p>}<details><summary>Why this offer?</summary>{o.reasons.length>0&&<ul>{o.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}{ranked.hard_constraint_failures.map(failure=><p className="factor-failure" key={failure}>Hard gate: {failure}</p>)}{ranked.factors.map(factor=><div className="factor" key={factor.name}><div><strong>{factor.name}</strong><span>{factor.score.toFixed(1)} × {Math.round(factor.weight*100)}% = {(factor.score*factor.weight).toFixed(1)}</span></div><p>{factor.explanation}</p></div>)}</details></article>
}

function SmartFundingMatch({
 opportunity,
 onApply,
 busy,
 lowestRate,
 error,
 reqAmount,
 reqHours,
 reqPriority,
 setReqAmount,
 setReqHours,
 setReqPriority,
}:{
 opportunity:Opportunity|null;
 onApply:(p?:'BALANCED'|'FASTEST'|'LOWEST_FEE'|'HIGHEST_ADVANCE',amt?:number,hrs?:number)=>Promise<void>;
 busy:boolean;
 lowestRate:number;
 error:string;
 reqAmount:number;
 reqHours:number;
 reqPriority:'BALANCED'|'FASTEST'|'LOWEST_FEE'|'HIGHEST_ADVANCE';
 setReqAmount:(v:number)=>void;
 setReqHours:(v:number)=>void;
 setReqPriority:(v:'BALANCED'|'FASTEST'|'LOWEST_FEE'|'HIGHEST_ADVANCE')=>void;
}){
 const offers=opportunity?.match?.ranked_offers||[]
 const winner=offers.find(x=>x.offer.id===opportunity?.match?.recommended_offer_id&&x.eligible)
 const invoice=opportunity?.invoice
 const risk=opportunity?.evaluation?.risk
 const verification=opportunity?.evaluation?.verification

 return (
  <main>
   <header>
    <div>
     <p className="eyebrow">USER-REQUIREMENT-BASED OFFER RECOMMENDATION</p>
     <h1>Smart Funding <em>Match.</em></h1>
     <p className="lede">Customize your required financing amount, funding deadline, and priority to receive deterministic, explainable provider recommendations.</p>
    </div>
   </header>

   {error&&<div className="error-banner" role="alert">Match failed: {error}</div>}

   <section className="smart-match-panel" style={{background:'#f8faf6',border:'1px solid #d2ddd4',borderRadius:6,padding:24,marginBottom:24}}>
    <div className="card-label"><Sparkles/> CONFIGURE YOUR FUNDING REQUIREMENTS</div>
    <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:16,marginTop:12,marginBottom:16}}>
     <div>
      <label style={{fontSize:11,fontWeight:700,color:'#40534c',display:'block',marginBottom:4}}>AMOUNT NEEDED (₹)</label>
      <input
       type="number"
       step="50000"
       min="50000"
       max={invoice?.amount||5000000}
       value={reqAmount}
       onChange={e=>setReqAmount(Number(e.target.value))}
       style={{width:'100%',padding:'8px 12px',fontSize:13,border:'1px solid #b8c9bd',borderRadius:4}}
      />
      <small style={{color:'#71837c',fontSize:10}}>e.g. ₹8,00,000 against invoice value</small>
     </div>

     <div>
      <label style={{fontSize:11,fontWeight:700,color:'#40534c',display:'block',marginBottom:4}}>FUNDING DEADLINE</label>
      <select
       value={reqHours}
       onChange={e=>setReqHours(Number(e.target.value))}
       style={{width:'100%',padding:'8px 12px',fontSize:13,border:'1px solid #b8c9bd',borderRadius:4,background:'#fff'}}
      >
       <option value={2}>2 Hours (Instant settlement)</option>
       <option value={24}>24 Hours (Within 1 day)</option>
       <option value={48}>48 Hours (Within 2 days)</option>
       <option value={96}>96 Hours (Within 4 days)</option>
       <option value={168}>168 Hours (Within 1 week)</option>
      </select>
      <small style={{color:'#71837c',fontSize:10}}>Maximum acceptable settlement time</small>
     </div>

     <div>
      <label style={{fontSize:11,fontWeight:700,color:'#40534c',display:'block',marginBottom:4}}>YOUR PRIORITY</label>
      <select
       value={reqPriority}
       onChange={e=>setReqPriority(e.target.value as any)}
       style={{width:'100%',padding:'8px 12px',fontSize:13,border:'1px solid #b8c9bd',borderRadius:4,fontWeight:700,background:'#fff',color:'#1c4236'}}
      >
       <option value="BALANCED">Balanced (Speed, cost, advance & risk)</option>
       <option value="FASTEST">Fastest Funding (Prioritize settlement speed)</option>
       <option value="LOWEST_FEE">Lowest Fee (Prioritize lowest cost/rate)</option>
       <option value="HIGHEST_ADVANCE">Highest Advance (Prioritize advance rate %)</option>
      </select>
      <small style={{color:'#71837c',fontSize:10}}>Changes the weighted recommendation policy</small>
     </div>
    </div>

    <div style={{display:'flex',justifyContent:'flex-end'}}>
     <button className="primary" onClick={()=>void onApply(reqPriority,reqAmount,reqHours)} disabled={busy} style={{padding:'8px 20px',fontSize:13}}>
      {busy?<RotateCcw className="spin"/>:<Bolt/>} Find Best Financing Offer
     </button>
    </div>
   </section>

   {!opportunity?(
    <section className="empty-market"><Sparkles/><div><p className="eyebrow">NO ACTIVE INVOICE</p><h2>Configure requirements and click "Find Best Financing Offer".</h2><p>The matching engine will evaluate all capital providers (Astra Bank, VegaFlow NBFC, PulseTrade Capital, Meridian Yield Fund) and select the optimal offer.</p></div></section>
   ):(
    <>
     <section className="decision" style={{marginBottom:24}}>
      <div>
       <p className="eyebrow">RECOMMENDED FINANCING OFFER • {reqPriority.replace('_',' ')} PRIORITY</p>
       <h2>{winner?`BEST MATCH: ${winner.offer.provider_name}`:'No provider currently satisfies all hard requirements.'}</h2>
       {winner&&(
        <div style={{display:'flex',gap:16,margin:'12px 0',fontSize:13,color:'#204b3e',fontWeight:700,flexWrap:'wrap'}}>
         <span>⚡ Settlement: {winner.offer.settlement_hours}h</span>
         <span>💰 Advance: {((winner.offer.advance_rate||0)*100).toFixed(0)}% ({money(winner.offer.financed_amount||0)})</span>
         <span>🏷️ Est. Fee: {money(winner.offer.fees||0)}</span>
         <span>📈 Annual Rate: {winner.offer.annual_rate}%</span>
        </div>
       )}

       <div style={{marginTop:14}}>
        <strong style={{fontSize:11,textTransform:'uppercase',letterSpacing:'0.04em',color:'#5a6e67',display:'block',marginBottom:6}}>Why this is the best match:</strong>
        <ul style={{margin:'0 0 10px 0',paddingLeft:18,fontSize:12,lineHeight:1.6}}>
         {opportunity.match?.recommendation_reasons.map((r,i)=><li key={i}>✓ {r}</li>)}
        </ul>
       </div>

       {opportunity.match?.tradeoffs&&opportunity.match.tradeoffs.length>0&&(
        <div style={{marginTop:12,padding:'10px 14px',background:'#fafafa',border:'1px solid #e5e5e5',borderRadius:4}}>
         <strong style={{fontSize:10,textTransform:'uppercase',letterSpacing:'0.04em',color:'#737373',display:'block',marginBottom:4}}>Trade-off & Alternatives:</strong>
         <ul style={{margin:0,paddingLeft:16,fontSize:11,color:'#525252',lineHeight:1.5}}>
          {opportunity.match.tradeoffs.map((t,i)=><li key={i}>{t}</li>)}
         </ul>
        </div>
       )}

       <div style={{marginTop:14,display:'flex',gap:14,fontSize:11,color:'#4b6358',flexWrap:'wrap'}}>
        <span>✓ Requested Amount: {money(reqAmount)}</span>
        <span>✓ Target Deadline: {reqHours}h</span>
        <span>✓ Active Priority: {reqPriority}</span>
        <span>✓ Invoice Risk: {risk?.band} ({risk?.score}/100)</span>
       </div>
      </div>
      {winner&&<div className="score-ring"><strong>{winner.suitability_score}</strong><small>SUITABILITY</small></div>}
     </section>

     <div className="section-head">
      <div>
       <p className="eyebrow">ALL EVALUATED PROVIDERS</p>
       <h2>Provider Competition & Eligibility Breakdown</h2>
      </div>
      <div className="risk">
       <span>{risk?.band} RISK</span><b>{risk?.score}</b><small>/100</small>
      </div>
     </div>

     <div className="arena">
      <div className="provider-list">
       {offers.map(r=><ProviderOffer key={r.offer.id} ranked={r} winnerId={winner?.offer.id} lowestRate={lowestRate}/>)}
      </div>
     </div>
    </>
   )}
  </main>
 )
}
