import {useEffect,useMemo,useState} from 'react'
import {ArrowRight,BadgeCheck,Bolt,Building2,CircleDollarSign,Gauge,Landmark,Radar,RotateCcw,ShieldCheck,Sparkles} from 'lucide-react'
import {api,Metrics,Opportunity,RankedOffer,RiskLedgerEntry} from './api'
import CapitalAgents from './CapitalAgents'

export const money=(n:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n)
const lifecycle=['Invoice','Verify','Assess risk','Discover','Compete','Match','Finance','Settle','Reallocate']
const initialMetrics:Metrics={available_liquidity:15_050_000,active_opportunities:12,offers_generated:38,financing_allocated:6_480_000,settlements:7,provider_participation_rate:.79}
const initialOffers:RankedOffer[]=[
 {offer:{id:'a',provider_id:'bank-a',provider_name:'Astra Commercial Bank',provider_type:'BANK',status:'OFFER',annual_rate:9,financed_amount:700000,fees:1400,settlement_hours:96,total_effective_cost:11756,reasons:[]},eligible:false,suitability_score:0,hard_constraint_failures:['Offers ₹7,00,000, below required ₹8,00,000.','Settlement takes 96h, beyond the 48h limit.'],rank:null},
 {offer:{id:'b',provider_id:'nbfc-b',provider_name:'VegaFlow NBFC',provider_type:'NBFC',status:'OFFER',annual_rate:11,financed_amount:850000,fees:6800,settlement_hours:24,total_effective_cost:22171,reasons:[]},eligible:true,suitability_score:91,hard_constraint_failures:[],rank:1},
 {offer:{id:'c',provider_id:'fintech-c',provider_name:'PulseTrade Capital',provider_type:'FINTECH',status:'OFFER',annual_rate:12,financed_amount:900000,fees:40000,settlement_hours:2,total_effective_cost:57753,reasons:[]},eligible:true,suitability_score:84,hard_constraint_failures:[],rank:2}]

export default function App(){
 const [view,setView]=useState<'pulse'|'capital-agents'|'risk-ledger'>('pulse')
 const [ledgerEntries,setLedgerEntries]=useState<RiskLedgerEntry[]>([])
 const [opportunity,setOpportunity]=useState<Opportunity|null>(null),[metrics,setMetrics]=useState(initialMetrics),[phase,setPhase]=useState<'idle'|'running'|'ready'|'settled'|'reallocated'|'error'>('idle'),[error,setError]=useState('')
 const offers=opportunity?.match?.ranked_offers||initialOffers,winner=offers.find(x=>x.offer.id===(opportunity?.match?.recommended_offer_id||'b'))||offers.find(x=>x.rank===1)
 const activeStep=phase==='settled'||phase==='reallocated'?9:phase==='ready'?7:phase==='running'?3:6
 const invoice=opportunity?.invoice||{invoice_number:'INV-PRATIN-1001',supplier_name:'Shakti Components',buyer_name:'Orion Auto Systems',amount:1_000_000}
 const req=opportunity?.requirements||{minimum_amount:800_000,max_settlement_hours:48,desired_tenor_days:60}
 const risk=opportunity?.evaluation?.risk||{score:24,band:'LOW–MODERATE'}
 const verification=opportunity?.evaluation?.verification||{status:'VERIFIED',confidence:.95}
 const refreshLedger=async()=>{try{const data=await api.riskLedger();setLedgerEntries(data)}catch{/* ignore */}}
 useEffect(()=>{if(view==='risk-ledger')refreshLedger()},[view])
 const run=async()=>{setError('');setPhase('running');try{await api.reset();const scenarios=await api.scenarios();const created=await api.create(scenarios.urgent);setOpportunity(created);const result=await api.run(created.id);setOpportunity(result);setMetrics(await api.metrics());setPhase('ready');refreshLedger()}catch(e){setError(e instanceof Error?e.message:'Market failed');setPhase('error')}}
 const reallocate=async()=>{setError('');setPhase('running');try{const scenarios=await api.scenarios();const created=await api.create(scenarios.strong);const result=await api.run(created.id);setOpportunity(result);setMetrics(await api.metrics());setPhase('reallocated');refreshLedger()}catch(e){setError(e instanceof Error?e.message:'Reallocation failed');setPhase('error')}}
 const settle=async()=>{if(!opportunity||!winner)return;setError('');try{await api.settle(opportunity.id,winner.offer.id);setMetrics(await api.metrics());setPhase('settled')}catch(e){setError(e instanceof Error?e.message:'Settlement failed')}}
 const winnerName=winner?.offer.provider_name||'VegaFlow NBFC'
 const agentLatency=useMemo(()=>phase==='running'?'clearing now…':'agents evaluated deterministically',[phase])
 return <div className="shell"><aside className="rail"><div className="brand"><span>P</span><div>PRATIN<small>CAPITAL NETWORK</small></div></div><nav><button className={view==='pulse'?'active':''} onClick={()=>setView('pulse')}><Gauge/>Market pulse</button><button><Radar/>Opportunities</button><button className={view==='capital-agents'?'active':''} onClick={()=>setView('capital-agents')}><Landmark/>Capital agents</button><button className={view==='risk-ledger'?'active':''} onClick={()=>setView('risk-ledger')}><ShieldCheck/>Risk ledger</button></nav><div className="rail-foot"><span className="live-dot"/> MARKET ONLINE<small>Demo rail • No real funds</small></div></aside>
 {view==='capital-agents'?<CapitalAgents/>:view==='risk-ledger'?(
  <main><header><div><p className="eyebrow">DURABLE AUDIT • EXPLAINABLE EVALUATIONS</p><h1>Invoice Risk <em>Ledger.</em></h1><p className="lede">Every invoice risk evaluation is durably logged with factor-level explainability, uncertainty parameters, and policy versions.</p></div></header>
  {error&&<div className="error-banner">Integration failed visibly: {error}. Start the backend or use Docker Compose.</div>}
  <section className="ledger-grid">
   {ledgerEntries.length===0?(
    <div className="empty-ledger">No risk evaluations in ledger yet. Run the market from "Market pulse" to generate evaluation history.</div>
   ):(
    ledgerEntries.map(entry=>(
     <article className="ledger-entry" key={entry.id}>
      <div className="ledger-header">
       <div>
        <div className="card-label"><BadgeCheck/> {entry.verification.status} • {Math.round(entry.verification.confidence*100)}% CONFIDENCE • {entry.id}</div>
        <h3>{entry.invoice_number} — {money(entry.amount)}</h3>
        <p>{entry.supplier_name} (Supplier) → {entry.buyer_name} (Buyer) • Evaluated: {new Date(entry.evaluated_at).toLocaleString()}</p>
       </div>
       <div className="risk"><span>{entry.risk.band} RISK</span><b>{entry.risk.score}</b><small>/100</small></div>
      </div>
      <div className="eyebrow">FACTOR-LEVEL EXPLAINABILITY ({entry.risk.factors.length} FACTORS)</div>
      <div className="ledger-factors">
       {entry.risk.factors.map((f,idx)=>(
        <div key={idx} className={`factor-card ${f.impact}`}>
         <div className="factor-title"><span>{f.label}</span><b>{f.points>0?`+${f.points}`:f.points}</b></div>
         <p className="factor-desc">{f.explanation}</p>
        </div>
       ))}
      </div>
      {entry.verification.uncertain_fields.length>0&&(
       <div className="tag-list">
        <span className="eyebrow" style={{marginRight:8}}>UNCERTAINTY:</span>
        {entry.verification.uncertain_fields.map(u=><span key={u} className="uncertainty-tag">{u}</span>)}
       </div>
      )}
      <footer style={{marginTop:12,fontSize:10,color:'#719087'}}>
       <ShieldCheck style={{width:14,verticalAlign:'middle',marginRight:4}}/> Policy: {entry.risk.policy_version} • Provenance: {entry.provenance} • Synthetic assessment
      </footer>
     </article>
    ))
   )}
  </section>
  </main>
 ):(
  <main><header><div><p className="eyebrow">CONTINUOUS CLEARING • LIVE DEMO MARKET</p><h1>Capital, intelligently <em>allocated.</em></h1><p className="lede">Every verified invoice enters a competitive market where autonomous providers price risk, protect portfolios and race to satisfy the supplier.</p></div><button className="primary" onClick={phase==='settled'?reallocate:run} disabled={phase==='running'}>{phase==='running'?<RotateCcw className="spin"/>:<Bolt/>}{phase==='running'?' Agents are competing':phase==='settled'?' Run next allocation':' Run flagship market'}</button></header>
  {error&&<div className="error-banner">Integration failed visibly: {error}. Start the backend or use Docker Compose.</div>}
  <section className="ticker">{lifecycle.map((x,i)=><div key={x} className={i<activeStep?'done':i===activeStep?'now':''}><span>{i<activeStep?'✓':i+1}</span>{x}{i<lifecycle.length-1&&<ArrowRight/>}</div>)}</section>
  <section className="metrics"><article><small>DEPLOYABLE CAPITAL</small><strong>{money(metrics.available_liquidity)}</strong><p><i>{phase==='settled'?'UPDATED':'LIVE'}</i> across 4 providers</p></article><article><small>ACTIVE OPPORTUNITIES</small><strong>{metrics.active_opportunities}</strong><p><i>{metrics.settlements}</i> settled autonomously</p></article><article><small>OFFERS GENERATED</small><strong>{metrics.offers_generated}</strong><p><i>{Math.round(metrics.provider_participation_rate*100)}%</i> provider participation</p></article><article><small>CAPITAL ALLOCATED</small><strong>{money(metrics.financing_allocated)}</strong><p><i>{phase==='settled'?'JUST NOW':'18h'}</i> funding signal</p></article></section>
  <div className="section-head"><div><p className="eyebrow">{phase==='settled'?'SETTLED & REALLOCATED':'LIVE MARKET'} • {opportunity?.id||'OPP-7A91C'}</p><h2>{invoice.supplier_name} seeks {money(req.minimum_amount)} within {req.max_settlement_hours} hours</h2></div><div className="risk"><span>{risk.band} RISK</span><b>{risk.score}</b><small>/100</small></div></div>
  <section className="market-grid"><article className="invoice-card"><div className="card-label"><BadgeCheck/> {verification.status} OPPORTUNITY</div><h3>{invoice.invoice_number}</h3><p>{invoice.buyer_name} → {invoice.supplier_name}</p><div className="invoice-total"><small>INVOICE VALUE</small><strong>{money(invoice.amount)}</strong></div><dl><div><dt>Minimum capital</dt><dd>{money(req.minimum_amount)}</dd></div><div><dt>Settlement ceiling</dt><dd>{req.max_settlement_hours} hours</dd></div><div><dt>Desired tenor</dt><dd>{req.desired_tenor_days} days</dd></div><div><dt>Verification confidence</dt><dd>{Math.round(verification.confidence*100)}%</dd></div></dl><footer><ShieldCheck/> Synthetic verification clearly labelled</footer></article>
  <div className="arena"><div className="arena-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i/> {agentLatency}</span></div><div className="provider-list">{offers.map(r=>{const o=r.offer,isWinner=o.id===winner?.offer.id;return <article className={`provider ${isWinner?'winner':''}`} key={o.id}><div className="provider-title"><div className="provider-icon">{o.provider_type==='BANK'?<Building2/>:o.provider_type==='FINTECH'?<CircleDollarSign/>:<Landmark/>}</div><div><h3>{o.provider_name}</h3><small>{o.provider_type} AGENT • {o.status}</small></div>{isWinner&&<b>RECOMMENDED</b>}</div><div className="offer-stats"><div><small>RATE</small><strong>{o.annual_rate?`${o.annual_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>{r.hard_constraint_failures.length?<p className="fail">× {r.hard_constraint_failures.join(' • ')}</p>:<p className={isWinner?'pass':'neutral'}>{isWinner?'✓ Satisfies every hard constraint':`Rank #${r.rank}`} • {r.suitability_score}/100 suitability</p>}</article>})}</div></div></section>
  <section className="decision"><div><p className="eyebrow">{phase==='settled'||phase==='reallocated'?'MARKET STATE UPDATED':'EXPLAINABLE CLEARING DECISION'}</p><h2>{phase==='settled'?`${winnerName} liquidity decreased. Run the next allocation.`:phase==='reallocated'?`${winnerName} now wins after VegaFlow capacity changed.`:`${winnerName} wins on total suitability, `}<span>{phase==='settled'?' Dynamic reallocation is armed.':phase==='reallocated'?' The market adapted.':'not headline rate.'}</span></h2><p>{opportunity?.match?.recommendation_reasons.join(' ')||'Astra’s lower rate looks cheapest—but it cannot deliver enough capital in time. The recommended agent satisfies the full supplier mandate while operating inside its own liquidity, risk and portfolio constraints.'}</p></div><div className="score-ring"><strong>{winner?.suitability_score||91}</strong><small>SUITABILITY</small></div>{phase!=='settled'&&phase!=='reallocated'&&<button className="settle" onClick={settle} disabled={!opportunity}>Accept & simulate settlement <ArrowRight/></button>}</section>
  </main>
 )}
 </div>}
