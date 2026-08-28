import {useEffect,useMemo,useState} from 'react'
import {ArrowRight,BadgeCheck,Bolt,Building2,CircleDollarSign,Gauge,Landmark,Radar,RotateCcw,ShieldCheck,Sparkles} from 'lucide-react'
import {api,AuditEvent,IntegrationStatus,Metrics,Opportunity,Provider,RankedOffer,RiskLedgerEntry,Settlement} from './api'
import CapitalAgents from './CapitalAgents'
import AdvancedLab from './AdvancedLab'
import {money} from './format'

export {money} from './format'
const lifecycle=['Invoice','Verify','Assess risk','Discover','Compete','Match','Finance','Settle','Reallocate']
type Phase='idle'|'loading'|'ready'|'settling'|'settled'|'rerunning'|'completed'|'error'
type View='pulse'|'opportunities'|'capital-agents'|'risk-ledger'|'advanced'
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
   setOpportunity(result);await refresh();setPhase('ready')
  }catch(e){setFailedAction('run');setError(e instanceof Error?e.message:'Market failed');setPhase('error')}
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

 return <div className="shell"><aside className="rail"><div className="brand"><span>P</span><div>PRATIN<small>CAPITAL NETWORK</small></div></div><nav><button className={view==='pulse'?'active':''} onClick={()=>setView('pulse')}><Gauge/>Market pulse</button><button className={view==='opportunities'?'active':''} onClick={()=>setView('opportunities')}><Radar/>Opportunities</button><button className={view==='capital-agents'?'active':''} onClick={()=>setView('capital-agents')}><Landmark/>Capital agents</button><button className={view==='risk-ledger'?'active':''} onClick={()=>setView('risk-ledger')}><ShieldCheck/>Risk ledger</button><button className={view==='advanced'?'active':''} onClick={()=>setView('advanced')}><Sparkles/>Simulation lab</button></nav><div className="rail-foot"><span className="live-dot"/> MARKET READY<small>Synthetic demo • No real funds</small></div></aside>
 {view==='advanced'?<AdvancedLab/>:view==='opportunities'?<Opportunities items={opportunities} error={opportunitiesError}/>:view==='capital-agents'?<CapitalAgents providers={providers} error={agentsError}/>:view==='risk-ledger'?<RiskLedger entries={ledgerEntries} error={ledgerError} onRefresh={()=>void refreshLedger()}/>:<main><header><div><p className="eyebrow">REQUEST-DRIVEN CLEARING • STATEFUL DEMO MARKET</p><h1>Capital, intelligently <em>allocated.</em></h1><p className="lede">Every verified invoice enters a competitive market where autonomous providers price risk, protect portfolios and race to satisfy the supplier.</p></div><button className="primary" onClick={primaryAction} disabled={busy}>{busy?<RotateCcw className="spin"/>:<Bolt/>}{primaryLabel}</button></header>
 {error&&<div className="error-banner" role="alert"><strong>Request failed.</strong> {error} <button onClick={retryAction} disabled={busy}>Retry safely</button></div>}
 <section className="provenance" aria-label="Integration provenance"><div><small>INVOICE / RISK AGENT</small><span className={provenanceClass(opportunity?.integration_status.invoice_risk)}>● {provenanceLabel(opportunity?.integration_status.invoice_risk)}</span></div><div><small>CAPITAL MARKET AGENTS</small><span className={provenanceClass(opportunity?.integration_status.capital_market)}>● {provenanceLabel(opportunity?.integration_status.capital_market)}</span></div><div><small>MARKET STATE</small><span className={database==='supabase-postgres'?'service':database?'fixture':'unavailable'}>● {database==='supabase-postgres'?'SUPABASE POSTGRES':database==='sqlite'?'SQLITE OFFLINE':'UNAVAILABLE'}</span></div><p>{!opportunity?'No market response received yet.':Object.values(opportunity.integration_status).includes('DEGRADED_FIXTURE')?'A service was unavailable; deterministic fixtures are clearly shown.':Object.values(opportunity.integration_status).every(x=>x==='SERVICE')?'Both responses came through validated HTTP service contracts.':'Deterministic fixture mode is active; these are not external service responses.'}</p></section>
 <section className="ticker">{lifecycle.map((x,i)=><div key={x} className={i<activeStep?'done':i===activeStep?'now':''}><span>{i<activeStep?'✓':i+1}</span>{x}{i<lifecycle.length-1&&<ArrowRight/>}</div>)}</section>
 <section className="metrics"><article><small>DEPLOYABLE CAPITAL</small><strong>{metrics?money(metrics.available_liquidity):'—'}</strong><p>{metrics?'Backend marketplace state':'Available after first market run'}</p></article><article><small>ACTIVE OPPORTUNITIES</small><strong>{metrics?.active_opportunities??'—'}</strong><p>{metrics?`${metrics.settlements} simulated settlements`:'No backend metrics loaded'}</p></article><article><small>OFFERS GENERATED</small><strong>{metrics?.offers_generated??'—'}</strong><p>{metrics?`${Math.round(metrics.provider_participation_rate*100)}% provider participation`:'No fabricated offer totals'}</p></article><article><small>CAPITAL ALLOCATED</small><strong>{metrics?money(metrics.financing_allocated):'—'}</strong><p>{metrics?'Derived from settlement ledger':'Waiting for settlement'}</p></article></section>

 {!opportunity?<section className="empty-market"><Sparkles/><div><p className="eyebrow">MARKETPLACE READY</p><h2>No allocation has run yet.</h2><p>Select <strong>Run flagship market</strong> to request real backend verification, provider offers and a recommendation. No preview decision is being presented as live data.</p></div></section>:<>
 <div className="section-head"><div><p className="eyebrow">{phase==='completed'?'SECOND ALLOCATION':'BACKEND MARKET'} • {opportunity.id}</p><h2>{invoice?.supplier_name} seeks {money(req?.minimum_amount||0)} within {req?.max_settlement_hours} hours</h2></div><div className="risk"><span>{risk?.band} RISK</span><b>{risk?.score}</b><small>/100</small></div></div>
 <section className="market-grid"><article className="invoice-card"><div className="card-label"><BadgeCheck/> {verification?.status} OPPORTUNITY</div><h3>{invoice?.invoice_number}</h3><p>{invoice?.buyer_name} → {invoice?.supplier_name}</p><div className="invoice-total"><small>INVOICE VALUE</small><strong>{money(invoice?.amount||0)}</strong></div><dl><div><dt>Minimum capital</dt><dd>{money(req?.minimum_amount||0)}</dd></div><div><dt>Settlement ceiling</dt><dd>{req?.max_settlement_hours} hours</dd></div><div><dt>Desired tenor</dt><dd>{req?.desired_tenor_days} days</dd></div><div><dt>Verification confidence</dt><dd>{Math.round((verification?.confidence||0)*100)}%</dd></div></dl><footer><ShieldCheck/> Synthetic verification clearly labelled</footer></article>
 <div className="arena"><div className="arena-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i/> {agentLatency}</span></div><div className="provider-list">{offers.map(r=><ProviderOffer key={r.offer.id} opportunityId={opportunity.id} ranked={r} winnerId={winner?.offer.id} lowestRate={lowestRate}/>)}</div></div></section>
 <section className="decision"><div><p className="eyebrow">{phase==='completed'?'ADAPTIVE REALLOCATION COMPLETE':receipt?'MARKET STATE UPDATED':'EXPLAINABLE BACKEND DECISION'}</p><h2>{winner?`${winner.offer.provider_name} ${phase==='completed'?'wins allocation two after provider state changed.':'wins on complete suitability.'}`:'No provider currently satisfies every mandate.'}</h2><p>{opportunity.match?.recommendation_reasons.join(' ')}</p></div>{winner&&<div className="score-ring"><strong>{winner.suitability_score}</strong><small>SUITABILITY</small></div>}{phase==='ready'&&winner&&<button className="settle" onClick={settle} disabled={busy}>Accept & simulate settlement <ArrowRight/></button>}</section>
 </>}

 {receipt&&<section className="settlement-proof"><div><p className="eyebrow">SIMULATED SETTLEMENT • {receipt.settlement.id}</p><h2>One atomic write changed the next market.</h2><p>{receipt.settlement.notice}</p></div><dl><div><dt>Provider liquidity</dt><dd>{money(receipt.before.available_liquidity)} <ArrowRight/> <strong>{money(receipt.after.available_liquidity)}</strong></dd></div><div><dt>Provider exposure</dt><dd>{money(receipt.before.current_exposure)} <ArrowRight/> <strong>{money(receipt.after.current_exposure)}</strong></dd></div></dl></section>}
 {history.length>0&&<section className="allocation-history"><p className="eyebrow">CAUSAL ALLOCATION HISTORY</p><div className="history-flow">{history.map((item,index)=><div key={item.sequence} className="history-item"><small>ALLOCATION {item.sequence}</small><strong>{item.provider}</strong><span>{item.invoice} • {item.amount?money(item.amount):'—'} • {item.rate??'—'}%</span>{item.liquidityBefore!==undefined&&<em>Liquidity {money(item.liquidityBefore)} → {money(item.liquidityAfter||0)}</em>}{index<history.length-1&&<ArrowRight/>}</div>)}</div>{history.length===1&&phase==='settled'&&<p className="history-hint">Provider liquidity and exposure changed. Run the next allocation to see the market adapt.</p>}{history.length===2&&<p className="history-hint success">VegaFlow → state mutation → Meridian. The second winner changed because settlement changed provider capacity.</p>}</section>}
 {audit.length>0&&<section className="audit-timeline"><p className="eyebrow">RECENT BACKEND AUDIT EVENTS</p>{audit.slice(0,4).map(event=><div key={event.id}><span>{event.event_type.replaceAll('_',' ')}</span><p>{event.detail}</p><small>{event.id}</small></div>)}</section>}
 </main>}
 </div>
}

function Opportunities({items,error}:{items:Opportunity[];error:string}){
 return <main><header><div><p className="eyebrow">DURABLE BACKEND HISTORY • SYNTHETIC DEMO</p><h1>Financing <em>opportunities.</em></h1><p className="lede">Invoices admitted to the market remain visible with their current lifecycle state and backend recommendation.</p></div></header>
 {error&&<div className="error-banner" role="alert">Opportunities unavailable: {error}</div>}
 <section className="opportunity-grid">{items.length===0?<div className="empty-ledger">No opportunities exist yet. Run the flagship market from Market pulse.</div>:items.map(item=>{const winner=item.match?.ranked_offers.find(r=>r.offer.id===item.match?.recommended_offer_id);return <article className="opportunity-card" key={item.id}><div><small>{item.status.replaceAll('_',' ')} • {item.id}</small><h3>{item.invoice.invoice_number}</h3><p>{item.invoice.supplier_name} → {item.invoice.buyer_name}</p></div><dl><div><dt>Invoice value</dt><dd>{money(item.invoice.amount)}</dd></div><div><dt>Minimum capital</dt><dd>{money(item.requirements.minimum_amount)}</dd></div><div><dt>Recommendation</dt><dd>{winner?.offer.provider_name||'Not cleared'}</dd></div><div><dt>Created</dt><dd>{new Date(item.created_at).toLocaleString()}</dd></div></dl></article>})}</section>
 </main>
}

function RiskLedger({entries,error,onRefresh}:{entries:RiskLedgerEntry[];error:string;onRefresh?:()=>void}){
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
   </div>
  )}
 </section>

 <section className="ledger-grid">{entries.length===0?<div className="empty-ledger">No risk evaluations in the ledger yet. Run the market from Market pulse or upload a PDF invoice above to generate evaluation history.</div>:entries.map(entry=><article className="ledger-entry" key={entry.id}><div className="ledger-header"><div><div className="card-label"><BadgeCheck/> {entry.verification.status} • {Math.round(entry.verification.confidence*100)}% CONFIDENCE • {entry.id} {entry.source==='PDF_UPLOAD'&&<span className="verified-tag" style={{marginLeft:6}}>PDF UPLOAD {entry.source_filename?`(${entry.source_filename})`:''}</span>}</div><h3>{entry.invoice_number} — {money(entry.amount)}</h3><p>{entry.supplier_name} → {entry.buyer_name} • Evaluated {new Date(entry.evaluated_at).toLocaleString()}</p></div><div className="risk"><span>{entry.risk.band} RISK</span><b>{entry.risk.score}</b><small>/100</small></div></div>{entry.verification.reason_codes&&entry.verification.reason_codes.length>0&&<div className="tag-list" style={{marginBottom:12}}><span className="eyebrow" style={{marginRight:8}}>VERIFICATION CODES:</span>{entry.verification.reason_codes.map(code=><span key={code} className="uncertainty-tag" style={{borderColor:'#37725f',color:'#204b3e',background:'#eaf4ef'}}>{code}</span>)}</div>}<div className="eyebrow">FACTOR-LEVEL EXPLAINABILITY ({entry.risk.factors.length} FACTORS)</div><div className="ledger-factors">{entry.risk.factors.map(factor=><div key={factor.label} className={`factor-card ${factor.impact}`}><div className="factor-title"><span>{factor.label}</span><b>{factor.points>0?`+${factor.points}`:factor.points}</b></div>{factor.reason_code&&<div style={{fontSize:9,fontWeight:700,letterSpacing:'0.04em',color:factor.impact==='positive'?'#2e6935':factor.impact==='negative'?'#8c3f35':'#526c63',marginBottom:4}}>{factor.reason_code}</div>}<p className="factor-desc">{factor.explanation}</p></div>)}</div>{entry.verification.uncertain_fields.length>0&&<div className="tag-list"><span className="eyebrow" style={{marginRight:8}}>UNCERTAINTY:</span>{entry.verification.uncertain_fields.map(field=><span key={field} className="uncertainty-tag">{field}</span>)}</div>}<footer style={{marginTop:12,fontSize:10,color:'#719087'}}><ShieldCheck style={{width:14,verticalAlign:'middle',marginRight:4}}/> Policy: {entry.risk.policy_version} • Provenance: {entry.provenance} • Synthetic assessment</footer></article>)}</section></main>
}

function ProviderOffer({ranked,winnerId,lowestRate,opportunityId}:{ranked:RankedOffer;winnerId?:string;lowestRate:number;opportunityId:string}){
 const o=ranked.offer,isWinner=o.id===winnerId,isLowest=o.annual_rate===lowestRate,[why,setWhy]=useState<any>(null)
 return <article className={`provider ${isWinner?'winner':''} ${!ranked.eligible?'ineligible':''}`}><div className="provider-title"><div className="provider-icon">{o.provider_type==='BANK'?<Building2/>:o.provider_type==='FINTECH'?<CircleDollarSign/>:<Landmark/>}</div><div><h3>{o.provider_name}</h3><small>{o.provider_type} AGENT • {o.status}</small></div><div className="offer-badges">{isLowest&&<b className="lowest">LOWEST RATE</b>}{isWinner&&<b>RECOMMENDED</b>}{!ranked.eligible&&<b className="bad">INELIGIBLE</b>}</div></div><div className="offer-stats"><div><small>RATE</small><strong>{o.annual_rate!==null?`${o.annual_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>{ranked.hard_constraint_failures.length?<p className="fail">× {ranked.hard_constraint_failures.join(' • ')}</p>:<p className={isWinner?'pass':'neutral'}>{isWinner?'✓ Satisfies every supplier hard constraint':`Rank #${ranked.rank}`} • {ranked.suitability_score}/100 suitability</p>}<details><summary>Decision influence & explanation</summary><button onClick={()=>void api.counterfactual(opportunityId,o.provider_id).then(setWhy)}>Why didn't this provider win?</button>{why&&<div className="counterfactual"><b>{why.currently_eligible?'APPROXIMATE RANKING SENSITIVITY':'EXACT ELIGIBILITY CHANGES'}</b>{why.hard_constraint_changes.map((x:any)=><p key={x.field}>{x.field.replaceAll('_',' ')}: {x.current} → {x.required}</p>)}{why.ranking_disadvantages.slice(0,2).map((x:any)=><p key={x.factor}>{x.factor}: {x.weighted_gap} weighted points behind</p>)}</div>}{o.reasons.length>0&&<ul>{o.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}{ranked.hard_constraint_failures.map(failure=><p className="factor-failure" key={failure}>Hard gate: {failure}</p>)}{ranked.factors.map(factor=><div className="factor" key={factor.name}><div><strong>{factor.name}</strong><span>+{(factor.score*factor.weight).toFixed(1)} influence</span></div><p>{factor.score.toFixed(1)} × {Math.round(factor.weight*100)}%. {factor.explanation}</p></div>)}</details></article>
}
