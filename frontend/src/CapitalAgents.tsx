import {useEffect,useState} from 'react'
import {Activity,BadgeCheck,Banknote,CircleDollarSign,Gauge,Landmark,Radar,ShieldCheck,Sparkles} from 'lucide-react'

const money=(n:number|null|undefined)=>n===null||n===undefined?'—':new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n)
const pct=(n:number|null|undefined)=>n===null||n===undefined?'—':`${(n*100).toFixed(0)}%`

type Factor={label:string;score:number;explanation:string}
type Attractiveness={score:number;factors:Factor[]}
type Pricing={base_return_rate:number;risk_premium:number;tenor_adjustment:number;industry_adjustment:number;liquidity_adjustment:number;portfolio_adjustment:number;market_adjustment:number;final_rate:number;lines:string[]}
type ProviderState={id:string;name:string;provider_type:string;available_liquidity:number;risk_appetite:number;min_return_rate:number;max_ticket_size:number;preferred_industries:string[];settlement_hours:number;max_concentration_ratio:number;current_exposure:number;portfolio_capacity:number;base_advance_rate:number;fee_rate:number}
type Hard={passed:boolean;failures:string[]}
type Offer={status:'OFFER'|'DECLINE';advance_rate:number|null;financed_amount:number|null;tenor_days:number|null;fees:number|null;total_effective_cost:number|null;expected_return:number|null;settlement_hours:number|null;reasons:string[];post_allocation_exposure_ratio:number|null}
type Market={regime:string;source:string;description:string}
type Analysis={provider:ProviderState;hard:Hard;attractiveness:Attractiveness|null;pricing:Pricing|null;offer:Offer;market:Market}

const base=import.meta.env.VITE_CAPITAL_MARKET_URL||'http://127.0.0.1:8002'

// Manual MarketRequest payload mirroring the backend demo fixtures (urgent scenario).
const sampleRequest={
 opportunity_id:'OPP-CAPITAL-AGENTS',
 invoice:{invoice_number:'INV-PRATIN-1001',supplier_name:'Shakti Components',buyer_name:'Orion Auto Systems',amount:1000000,currency:'INR',issue_date:'2026-08-20',due_date:'2026-10-19',industry:'Manufacturing',gstin:'27ABCDE1234F1Z5',purchase_order_reference:'PO-2026-1188',buyer_rating:0.88,supplier_history_months:38,on_time_payment_ratio:0.93,prior_defaults:0},
 requirements:{minimum_amount:800000,max_settlement_hours:48,desired_tenor_days:60},
 verification:{status:'VERIFIED',confidence:0.95,verified_fields:['invoice_number','supplier_name','buyer_name','amount','issue_date','due_date'],uncertain_fields:[],reasons:['Invoice fields are internally consistent under the synthetic verification policy.']},
 risk:{score:24,band:'LOW',confidence:0.9,factors:[],missing_information:[]},
 providers:[
  {id:'bank-a',name:'Astra Commercial Bank',provider_type:'BANK',available_liquidity:5000000,risk_appetite:42,min_return_rate:8.2,max_ticket_size:700000,preferred_industries:['Manufacturing','Automotive'],settlement_hours:96,max_concentration_ratio:0.60,current_exposure:900000,portfolio_capacity:8000000,base_advance_rate:0.70,fee_rate:0.002},
  {id:'nbfc-b',name:'VegaFlow NBFC',provider_type:'NBFC',available_liquidity:1650000,risk_appetite:68,min_return_rate:9.4,max_ticket_size:1500000,preferred_industries:['Manufacturing','Logistics','Retail'],settlement_hours:24,max_concentration_ratio:0.72,current_exposure:1300000,portfolio_capacity:6000000,base_advance_rate:0.85,fee_rate:0.008},
  {id:'fintech-c',name:'PulseTrade Capital',provider_type:'FINTECH',available_liquidity:2400000,risk_appetite:78,min_return_rate:10.5,max_ticket_size:1200000,preferred_industries:['Technology','Retail'],settlement_hours:2,max_concentration_ratio:0.82,current_exposure:1100000,portfolio_capacity:4000000,base_advance_rate:0.92,fee_rate:0.04},
  {id:'fund-d',name:'Meridian Yield Fund',provider_type:'FUND',available_liquidity:6000000,risk_appetite:58,min_return_rate:10.1,max_ticket_size:2500000,preferred_industries:['Pharma','Automotive'],settlement_hours:48,max_concentration_ratio:0.50,current_exposure:2600000,portfolio_capacity:10000000,base_advance_rate:0.80,fee_rate:0.012},
 ],
}

export default function CapitalAgents(){
 const [analyses,setAnalyses]=useState<Analysis[]>([])
 const [phase,setPhase]=useState<'idle'|'loading'|'ready'|'error'>('idle')
 const [error,setError]=useState('')

 const run=async()=>{
  setError('');setPhase('loading')
  try{
   const response=await fetch(`${base}/analysis`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(sampleRequest)})
   const payload=await response.json().catch(()=>null)
   if(!response.ok)throw new Error(payload&&typeof payload==='object'&&'detail' in payload?String(payload.detail):`Agent request failed: ${response.status}`)
   if(!payload||!Array.isArray(payload.offers))throw new Error('Agent returned an unexpected payload')
   setAnalyses(payload.offers);setPhase('ready')
  }catch(e){setError(e instanceof Error?e.message:'Capital agents failed');setPhase('error')}
 }

 useEffect(()=>{if(analyses.length===0&&phase==='idle')void run()},[analyses.length,phase])

 const offers=analyses.filter(a=>a.offer.status==='OFFER')
 const declines=analyses.filter(a=>a.offer.status==='DECLINE')

 return <main>
  <header><div><p className="eyebrow">CAPITAL PROVIDERS • AGENT STACK</p><h1>Capital <em>agents.</em></h1><p className="lede">Autonomous provider agents that evaluate invoices and compete under their own liquidity, risk and portfolio constraints. Each agent runs a deterministic pipeline: observe the opportunity, evaluate attractiveness, enforce hard constraints, decide, price, and explain.</p></div><button className="primary" onClick={run} disabled={phase==='loading'}>{phase==='loading'?<Activity className="spin"/>:<Sparkles/>}{phase==='loading'?'Agents are analysing…':'Re-run agent analysis'}</button></header>
  {error&&<div className="error-banner" role="alert"><strong>Agent request failed.</strong> {error} <button onClick={run} disabled={phase==='loading'}>Retry</button></div>}

  <section className="provenance" aria-label="Agent provenance"><div><small>CAPITAL MARKET AGENT</small><span className={phase==='ready'?'service':phase==='error'?'unavailable':'fixture'}>● {phase==='ready'?'SERVICE':phase==='error'?'UNAVAILABLE':'PENDING'}</span></div><div><small>MARKET REGIME</small><span>{analyses[0]?analyses[0].market.regime:'—'}</span></div><div><small>SOURCE</small><span>{analyses[0]?analyses[0].market.source:'—'}</span></div><p>{analyses[0]?analyses[0].market.description:'No agent analysis received yet.'}</p></section>

  <section className="metrics"><article><small>PROVIDERS EVALUATED</small><strong>{analyses.length||'—'}</strong><p>Independent agent runs, one per provider</p></article><article><small>OFFERS</small><strong>{offers.length||'—'}</strong><p>{declines.length?`${declines.length} declined on hard constraints`:'All providers participated'}</p></article><article><small>MARKET REGIME</small><strong>{analyses[0]?.market.regime||'—'}</strong><p>Deterministic demo fallback</p></article><article><small>INVOICE RISK</small><strong>{sampleRequest.risk.score}</strong><p>{sampleRequest.risk.band} band • supplied as input</p></article></section>

  {phase==='idle'||phase==='loading'?<section className="empty-market"><Activity className={phase==='loading'?'spin':''}/><div><p className="eyebrow">AGENT PIPELINE</p><h2>{phase==='loading'?'Providers are evaluating the opportunity.':'Ready to run the agent stack.'}</h2><p>Each provider independently decides participation, financing amount, advance rate, rate, tenor, fees, settlement speed, expected return — and explains every number.</p></div></section>:
  phase==='error'?<section className="empty-market"><ShieldCheck/><div><p className="eyebrow">AGENT UNAVAILABLE</p><h2>Could not reach the capital agent at {base}.</h2><p>Ensure the capital-market service is running on :8002, then retry. The tab renders live agent output only — no fabricated decisions.</p></div></section>:
  <div className="arena"><div className="arena-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i/> {analyses.length} providers • {offers.length} offers • {declines.length} declines</span></div>
   <div className="provider-list">{analyses.map(a=><AgentCard key={a.provider.id} analysis={a}/>)}</div></div>}
 </main>
}

function AgentCard({analysis}:{analysis:Analysis}){
 const p=analysis.provider,o=analysis.offer,a=analysis.attractiveness,pr=analysis.pricing
 const declined=o.status==='DECLINE'
 return <article className={`provider ${declined?'ineligible':''}`}>
  <div className="provider-title"><div className="provider-icon">{p.provider_type==='BANK'?<Landmark/>:p.provider_type==='FINTECH'?<CircleDollarSign/>:<Banknote/>}</div><div><h3>{p.name}</h3><small>{p.provider_type} AGENT • {o.status}</small></div><div className="offer-badges">{!declined&&<b>OFFER</b>}{declined&&<b className="bad">DECLINED</b>}{a&&a.score>=80&&<b className="lowest">ATTRACTIVE</b>}</div></div>
  <div className="offer-stats"><div><small>RATE</small><strong>{pr?`${pr.final_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>
  {declined?<p className="fail">× {o.reasons.join(' • ')}</p>:<p className="pass">✓ Finances {money(o.financed_amount)} at {pr?.final_rate}% for {o.tenor_days} days</p>}
  <details><summary>Agent stack — why this decision?</summary>
   {a&&<div className="agent-block"><div className="eyebrow">OPPORTUNITY ATTRACTIVENESS • {a.score}/100</div><div className="ledger-factors">{a.factors.map(f=><div key={f.label} className={`factor-card ${f.score>=50?'positive':'negative'}`}><div className="factor-title"><span>{f.label}</span><b>{f.score.toFixed(0)}</b></div><p className="factor-desc">{f.explanation}</p></div>)}</div></div>}
   {pr&&<div className="agent-block"><div className="eyebrow">PRICING DECOMPOSITION</div><div className="pricing-lines">{pr.lines.map((line,i)=><div key={i} className={i===pr.lines.length-1?'pricing-final':'pricing-line'}><span>{line}</span>{i<pr.lines.length-1&&<small>{['base','risk','tenor','industry','liquidity','portfolio','market'][i]}</small>}</div>)}</div></div>}
   {!declined&&<div className="agent-block"><div className="eyebrow">TERMS</div><div className="term-grid"><span>Financed amount</span><b>{money(o.financed_amount)}</b><span>Advance rate</span><b>{pct(o.advance_rate)}</b><span>Fees</span><b>{money(o.fees)}</b><span>Total effective cost</span><b>{money(o.total_effective_cost)}</b><span>Expected annualised return</span><b>{o.expected_return}%</b><span>Post-allocation exposure</span><b>{o.post_allocation_exposure_ratio!==null?`${(o.post_allocation_exposure_ratio*100).toFixed(0)}% of capacity`:'—'}</b></div></div>}
   {declined&&<div className="agent-block"><div className="eyebrow">HARD CONSTRAINT GATES</div>{analysis.hard.failures.map(f=><p className="factor-failure" key={f}>× {f}</p>)}</div>}
   <div className="agent-block"><div className="eyebrow">REASONS</div><ul>{o.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul></div>
   <div className="agent-block"><div className="eyebrow">PROVIDER STATE</div><div className="term-grid"><span>Available liquidity</span><b>{money(p.available_liquidity)}</b><span>Current exposure</span><b>{money(p.current_exposure)}</b><span>Portfolio capacity</span><b>{money(p.portfolio_capacity)}</b><span>Risk appetite</span><b>{p.risk_appetite}/100</b><span>Max ticket</span><b>{money(p.max_ticket_size)}</b><span>Settlement speed</span><b>{p.settlement_hours}h</b></div></div>
  </details>
 </article>
}
