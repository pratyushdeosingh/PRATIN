import {useEffect,useMemo,useState} from 'react'
import {ArrowRight,BadgeCheck,Bolt,Building2,CircleDollarSign,Gauge,Landmark,Radar,RotateCcw,ShieldCheck,Sparkles} from 'lucide-react'
import {api,AuditEvent,IntegrationStatus,Metrics,Opportunity,Provider,RankedOffer,RiskLedgerEntry,Settlement} from './api'
import CapitalAgents from './CapitalAgents'

export const money=(n:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n)
const lifecycle=['Invoice','Verify','Assess risk','Discover','Compete','Match','Finance','Settle','Reallocate']
type Phase='idle'|'loading'|'ready'|'settling'|'settled'|'rerunning'|'completed'|'error'
type View='pulse'|'capital-agents'|'risk-ledger'
type AllocationHistory={sequence:number;invoice:string;provider:string;rate:number|null;amount:number|null;liquidityBefore?:number;liquidityAfter?:number;exposureBefore?:number;exposureAfter?:number}
type Receipt={settlement:Settlement;before:Provider;after:Provider}

const provenanceLabel=(status?:IntegrationStatus)=>status?.replace('_',' ')||'UNAVAILABLE'
const provenanceClass=(status?:IntegrationStatus)=>status==='SERVICE'?'service':status==='DEGRADED_FIXTURE'?'degraded':status==='FIXTURE'?'fixture':'unavailable'

export default function App(){
 const [view,setView]=useState<View>('pulse')
 const [ledgerEntries,setLedgerEntries]=useState<RiskLedgerEntry[]>([])
 const [opportunity,setOpportunity]=useState<Opportunity|null>(null)
 const [metrics,setMetrics]=useState<Metrics|null>(null)
 const [providers,setProviders]=useState<Provider[]>([])
 const [audit,setAudit]=useState<AuditEvent[]>([])
 const [history,setHistory]=useState<AllocationHistory[]>([])
 const [receipt,setReceipt]=useState<Receipt|null>(null)
 const [database,setDatabase]=useState<'sqlite'|'supabase-postgres'|null>(null)
 const [phase,setPhase]=useState<Phase>('idle')
 const [error,setError]=useState('')
 const [failedAction,setFailedAction]=useState<'run'|'settle'|'reallocate'>('run')
 const offers=opportunity?.match?.ranked_offers||[]
 const winner=offers.find(x=>x.offer.id===opportunity?.match?.recommended_offer_id&&x.eligible)
 const offeredRates=offers.filter(x=>x.offer.status==='OFFER'&&x.offer.annual_rate!==null).map(x=>x.offer.annual_rate as number)
 const lowestRate=offeredRates.length?Math.min(...offeredRates):Number.NaN
 const busy=phase==='loading'||phase==='settling'||phase==='rerunning'
 const activeStep={idle:0,loading:3,ready:6,settling:7,settled:8,rerunning:4,completed:9,error:0}[phase]

 const refreshLedger=async()=>{const entries=await api.riskLedger();setLedgerEntries(entries)}
 useEffect(()=>{if(view==='risk-ledger')void refreshLedger().catch(e=>setError(e instanceof Error?e.message:'Risk ledger failed'))},[view])
 const refresh=async()=>{
  const [nextMetrics,nextProviders,nextAudit,health]=await Promise.all([api.metrics(),api.providers(),api.audit(),api.health()])
  setMetrics(nextMetrics);setProviders(nextProviders);setAudit(nextAudit);setDatabase(health.database)
  void refreshLedger().catch(()=>undefined)
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

 return <div className="shell"><aside className="rail"><div className="brand"><span>P</span><div>PRATIN<small>CAPITAL NETWORK</small></div></div><nav><button className={view==='pulse'?'active':''} onClick={()=>setView('pulse')}><Gauge/>Market pulse</button><button><Radar/>Opportunities</button><button className={view==='capital-agents'?'active':''} onClick={()=>setView('capital-agents')}><Landmark/>Capital agents</button><button className={view==='risk-ledger'?'active':''} onClick={()=>setView('risk-ledger')}><ShieldCheck/>Risk ledger</button></nav><div className="rail-foot"><span className="live-dot"/> MARKET READY<small>Synthetic demo • No real funds</small></div></aside>
 {view==='capital-agents'?<CapitalAgents/>:view==='risk-ledger'?<RiskLedger entries={ledgerEntries} error={error}/>:<main><header><div><p className="eyebrow">CONTINUOUS CLEARING • STATEFUL DEMO MARKET</p><h1>Capital, intelligently <em>allocated.</em></h1><p className="lede">Every verified invoice enters a competitive market where autonomous providers price risk, protect portfolios and race to satisfy the supplier.</p></div><button className="primary" onClick={primaryAction} disabled={busy}>{busy?<RotateCcw className="spin"/>:<Bolt/>}{primaryLabel}</button></header>
 {error&&<div className="error-banner" role="alert"><strong>Request failed.</strong> {error} <button onClick={retryAction} disabled={busy}>Retry safely</button></div>}
 <section className="provenance" aria-label="Integration provenance"><div><small>INVOICE / RISK AGENT</small><span className={provenanceClass(opportunity?.integration_status.invoice_risk)}>● {provenanceLabel(opportunity?.integration_status.invoice_risk)}</span></div><div><small>CAPITAL MARKET AGENTS</small><span className={provenanceClass(opportunity?.integration_status.capital_market)}>● {provenanceLabel(opportunity?.integration_status.capital_market)}</span></div><div><small>MARKET STATE</small><span className={database==='supabase-postgres'?'service':database?'fixture':'unavailable'}>● {database==='supabase-postgres'?'SUPABASE POSTGRES':database==='sqlite'?'SQLITE OFFLINE':'UNAVAILABLE'}</span></div><p>{!opportunity?'No market response received yet.':Object.values(opportunity.integration_status).includes('DEGRADED_FIXTURE')?'A service was unavailable; deterministic fixtures are clearly shown.':Object.values(opportunity.integration_status).every(x=>x==='SERVICE')?'Both responses came through validated HTTP service contracts.':'Deterministic fixture mode is active; these are not external service responses.'}</p></section>
 <section className="ticker">{lifecycle.map((x,i)=><div key={x} className={i<activeStep?'done':i===activeStep?'now':''}><span>{i<activeStep?'✓':i+1}</span>{x}{i<lifecycle.length-1&&<ArrowRight/>}</div>)}</section>
 <section className="metrics"><article><small>DEPLOYABLE CAPITAL</small><strong>{metrics?money(metrics.available_liquidity):'—'}</strong><p>{metrics?'Backend marketplace state':'Available after first market run'}</p></article><article><small>ACTIVE OPPORTUNITIES</small><strong>{metrics?.active_opportunities??'—'}</strong><p>{metrics?`${metrics.settlements} simulated settlements`:'No backend metrics loaded'}</p></article><article><small>OFFERS GENERATED</small><strong>{metrics?.offers_generated??'—'}</strong><p>{metrics?`${Math.round(metrics.provider_participation_rate*100)}% provider participation`:'No fabricated offer totals'}</p></article><article><small>CAPITAL ALLOCATED</small><strong>{metrics?money(metrics.financing_allocated):'—'}</strong><p>{metrics?'Derived from settlement ledger':'Waiting for settlement'}</p></article></section>

 {!opportunity?<section className="empty-market"><Sparkles/><div><p className="eyebrow">MARKETPLACE READY</p><h2>No allocation has run yet.</h2><p>Select <strong>Run flagship market</strong> to request real backend verification, provider offers and a recommendation. No preview decision is being presented as live data.</p></div></section>:<>
 <div className="section-head"><div><p className="eyebrow">{phase==='completed'?'SECOND ALLOCATION':'BACKEND MARKET'} • {opportunity.id}</p><h2>{invoice?.supplier_name} seeks {money(req?.minimum_amount||0)} within {req?.max_settlement_hours} hours</h2></div><div className="risk"><span>{risk?.band} RISK</span><b>{risk?.score}</b><small>/100</small></div></div>
 <section className="market-grid"><article className="invoice-card"><div className="card-label"><BadgeCheck/> {verification?.status} OPPORTUNITY</div><h3>{invoice?.invoice_number}</h3><p>{invoice?.buyer_name} → {invoice?.supplier_name}</p><div className="invoice-total"><small>INVOICE VALUE</small><strong>{money(invoice?.amount||0)}</strong></div><dl><div><dt>Minimum capital</dt><dd>{money(req?.minimum_amount||0)}</dd></div><div><dt>Settlement ceiling</dt><dd>{req?.max_settlement_hours} hours</dd></div><div><dt>Desired tenor</dt><dd>{req?.desired_tenor_days} days</dd></div><div><dt>Verification confidence</dt><dd>{Math.round((verification?.confidence||0)*100)}%</dd></div></dl><footer><ShieldCheck/> Synthetic verification clearly labelled</footer></article>
 <div className="arena"><div className="arena-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i/> {agentLatency}</span></div><div className="provider-list">{offers.map(r=><ProviderOffer key={r.offer.id} ranked={r} winnerId={winner?.offer.id} lowestRate={lowestRate}/>)}</div></div></section>
 <section className="decision"><div><p className="eyebrow">{phase==='completed'?'ADAPTIVE REALLOCATION COMPLETE':receipt?'MARKET STATE UPDATED':'EXPLAINABLE BACKEND DECISION'}</p><h2>{winner?`${winner.offer.provider_name} ${phase==='completed'?'wins allocation two after provider state changed.':'wins on complete suitability.'}`:'No provider currently satisfies every mandate.'}</h2><p>{opportunity.match?.recommendation_reasons.join(' ')}</p></div>{winner&&<div className="score-ring"><strong>{winner.suitability_score}</strong><small>SUITABILITY</small></div>}{phase==='ready'&&winner&&<button className="settle" onClick={settle} disabled={busy}>Accept & simulate settlement <ArrowRight/></button>}</section>
 </>}

 {receipt&&<section className="settlement-proof"><div><p className="eyebrow">SIMULATED SETTLEMENT • {receipt.settlement.id}</p><h2>One atomic write changed the next market.</h2><p>{receipt.settlement.notice}</p></div><dl><div><dt>Provider liquidity</dt><dd>{money(receipt.before.available_liquidity)} <ArrowRight/> <strong>{money(receipt.after.available_liquidity)}</strong></dd></div><div><dt>Provider exposure</dt><dd>{money(receipt.before.current_exposure)} <ArrowRight/> <strong>{money(receipt.after.current_exposure)}</strong></dd></div></dl></section>}
 {history.length>0&&<section className="allocation-history"><p className="eyebrow">CAUSAL ALLOCATION HISTORY</p><div className="history-flow">{history.map((item,index)=><div key={item.sequence} className="history-item"><small>ALLOCATION {item.sequence}</small><strong>{item.provider}</strong><span>{item.invoice} • {item.amount?money(item.amount):'—'} • {item.rate??'—'}%</span>{item.liquidityBefore!==undefined&&<em>Liquidity {money(item.liquidityBefore)} → {money(item.liquidityAfter||0)}</em>}{index<history.length-1&&<ArrowRight/>}</div>)}</div>{history.length===1&&phase==='settled'&&<p className="history-hint">Provider liquidity and exposure changed. Run the next allocation to see the market adapt.</p>}{history.length===2&&<p className="history-hint success">VegaFlow → state mutation → Meridian. The second winner changed because settlement changed provider capacity.</p>}</section>}
 {audit.length>0&&<section className="audit-timeline"><p className="eyebrow">RECENT BACKEND AUDIT EVENTS</p>{audit.slice(0,4).map(event=><div key={event.id}><span>{event.event_type.replaceAll('_',' ')}</span><p>{event.detail}</p><small>{event.id}</small></div>)}</section>}
 </main>}
 </div>
}

function RiskLedger({entries,error}:{entries:RiskLedgerEntry[];error:string}){
 return <main><header><div><p className="eyebrow">DURABLE AUDIT • EXPLAINABLE EVALUATIONS</p><h1>Invoice Risk <em>Ledger.</em></h1><p className="lede">Every completed risk evaluation is derived from durable backend opportunity state, with factor-level explanations and explicit provenance.</p></div></header>
 {error&&<div className="error-banner" role="alert">Risk ledger unavailable: {error}</div>}
 <section className="ledger-grid">{entries.length===0?<div className="empty-ledger">No risk evaluations in the ledger yet. Run the market from Market pulse to generate evaluation history.</div>:entries.map(entry=><article className="ledger-entry" key={entry.id}><div className="ledger-header"><div><div className="card-label"><BadgeCheck/> {entry.verification.status} • {Math.round(entry.verification.confidence*100)}% CONFIDENCE • {entry.id}</div><h3>{entry.invoice_number} — {money(entry.amount)}</h3><p>{entry.supplier_name} → {entry.buyer_name} • Evaluated {new Date(entry.evaluated_at).toLocaleString()}</p></div><div className="risk"><span>{entry.risk.band} RISK</span><b>{entry.risk.score}</b><small>/100</small></div></div><div className="eyebrow">FACTOR-LEVEL EXPLAINABILITY ({entry.risk.factors.length} FACTORS)</div><div className="ledger-factors">{entry.risk.factors.map(factor=><div key={factor.label} className={`factor-card ${factor.impact}`}><div className="factor-title"><span>{factor.label}</span><b>{factor.points>0?`+${factor.points}`:factor.points}</b></div><p className="factor-desc">{factor.explanation}</p></div>)}</div>{entry.verification.uncertain_fields.length>0&&<div className="tag-list"><span className="eyebrow" style={{marginRight:8}}>UNCERTAINTY:</span>{entry.verification.uncertain_fields.map(field=><span key={field} className="uncertainty-tag">{field}</span>)}</div>}<footer style={{marginTop:12,fontSize:10,color:'#719087'}}><ShieldCheck style={{width:14,verticalAlign:'middle',marginRight:4}}/> Policy: {entry.risk.policy_version} • Provenance: {entry.provenance} • Synthetic assessment</footer></article>)}</section></main>
}

function ProviderOffer({ranked,winnerId,lowestRate}:{ranked:RankedOffer;winnerId?:string;lowestRate:number}){
 const o=ranked.offer,isWinner=o.id===winnerId,isLowest=o.annual_rate===lowestRate
 return <article className={`provider ${isWinner?'winner':''} ${!ranked.eligible?'ineligible':''}`}><div className="provider-title"><div className="provider-icon">{o.provider_type==='BANK'?<Building2/>:o.provider_type==='FINTECH'?<CircleDollarSign/>:<Landmark/>}</div><div><h3>{o.provider_name}</h3><small>{o.provider_type} AGENT • {o.status}</small></div><div className="offer-badges">{isLowest&&<b className="lowest">LOWEST RATE</b>}{isWinner&&<b>RECOMMENDED</b>}{!ranked.eligible&&<b className="bad">INELIGIBLE</b>}</div></div><div className="offer-stats"><div><small>RATE</small><strong>{o.annual_rate!==null?`${o.annual_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>{ranked.hard_constraint_failures.length?<p className="fail">× {ranked.hard_constraint_failures.join(' • ')}</p>:<p className={isWinner?'pass':'neutral'}>{isWinner?'✓ Satisfies every supplier hard constraint':`Rank #${ranked.rank}`} • {ranked.suitability_score}/100 suitability</p>}<details><summary>Why this offer?</summary>{o.reasons.length>0&&<ul>{o.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}{ranked.hard_constraint_failures.map(failure=><p className="factor-failure" key={failure}>Hard gate: {failure}</p>)}{ranked.factors.map(factor=><div className="factor" key={factor.name}><div><strong>{factor.name}</strong><span>{factor.score.toFixed(1)} × {Math.round(factor.weight*100)}% = {(factor.score*factor.weight).toFixed(1)}</span></div><p>{factor.explanation}</p></div>)}</details></article>
}
