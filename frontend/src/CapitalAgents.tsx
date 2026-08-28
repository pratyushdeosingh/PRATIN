import {useEffect,useState} from 'react'
import {Activity,BadgeCheck,Banknote,CircleDollarSign,ExternalLink,Gauge,Globe,Landmark,RefreshCw,Search,ShieldCheck,Sparkles} from 'lucide-react'
import {Provider} from './api'
import './CapitalAgents.css'

const money=(n:number|null|undefined)=>n===null||n===undefined?'—':new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n)
const pct=(n:number|null|undefined)=>n===null||n===undefined?'—':`${(n*100).toFixed(0)}%`
const time=(iso:string|null|undefined)=>iso?new Date(iso).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'

type Factor={label:string;score:number;explanation:string}
type Attractiveness={score:number;factors:Factor[]}
type Pricing={base_return_rate:number;risk_premium:number;tenor_adjustment:number;industry_adjustment:number;liquidity_adjustment:number;portfolio_adjustment:number;market_adjustment:number;research_adjustment:number;final_rate:number;lines:string[]}
type ProviderState={id:string;name:string;provider_type:string;available_liquidity:number;risk_appetite:number;min_return_rate:number;max_ticket_size:number;preferred_industries:string[];settlement_hours:number;max_concentration_ratio:number;current_exposure:number;portfolio_capacity:number;base_advance_rate:number;fee_rate:number}
type Hard={passed:boolean;failures:string[]}
type Offer={status:'OFFER'|'DECLINE';advance_rate:number|null;financed_amount:number|null;tenor_days:number|null;fees:number|null;total_effective_cost:number|null;expected_return:number|null;settlement_hours:number|null;reasons:string[];post_allocation_exposure_ratio:number|null}
type Market={regime:string;source:string;description:string}
type Analysis={provider:ProviderState;hard:Hard;attractiveness:Attractiveness|null;pricing:Pricing|null;offer:Offer;market:Market}

type Fact={field:string;value:string;kind:'SOURCE_FACT'|'AGENT_INFERENCE';confidence:number;source_url:string;source_title:string;retrieved_at:string;evidence:string}
type ResearchedProvider={provider_name:string;provider_type:string;source_url:string;source_title:string;retrieved_at:string;facts:Fact[]}
type Telemetry={searches:number;providers_researched:number;pages_scraped:number;cache_hits:number;cache_misses:number;last_research_at:string|null;source:string}
type Research={status:'live'|'cached'|'unavailable';providers:ResearchedProvider[];telemetry:Telemetry;error:string|null}
type ScoreDimension={name:string;score:number;weight:number;evidence:string;explanation:string;confidence:number}
type ProviderScore={total:number;confidence:number;dimensions:ScoreDimension[]}
type Intelligence={provider:ResearchedProvider;score:ProviderScore;suitability_score:number;suitable:boolean;suitability_reasons:string[];rate_adjustment:number;advance_adjustment:number;facts:Fact[];inferences:Fact[]}
type TraceStep={key:string;label:string;state:'pending'|'running'|'done'|'failed'|'skipped';detail:string;at:string}
type Trace={started_at:string;finished_at:string|null;error:string|null;steps:TraceStep[]}
type CompanyFact={field:string;value:string;kind:'SOURCE_FACT'|'AGENT_INFERENCE';confidence:number;source_url:string;source_title:string;retrieved_at:string;evidence:string}
type CompanyResearch={name:string;status:'live'|'cached'|'unavailable';source_url:string;source_title:string;retrieved_at:string;facts:CompanyFact[];inferences:CompanyFact[];error:string|null}
type Companies={seller:CompanyResearch;client:CompanyResearch;telemetry:{searches:number;pages_scraped:number;cache_hits:number;cache_misses:number}}
type Payload={offers:Analysis[];research:{research:Research;providers:Intelligence[];rate_adjustment:number;advance_adjustment:number}|null;companies:Companies|null;trace:Trace|null}

// Real invoice + risk context the agent needs. Sourced either from a parsed
// PDF upload or from the latest real opportunity in the marketplace.
type MarketInput={
 invoice:{invoice_number?:string;supplier_name?:string;buyer_name?:string;amount:number;industry?:string;[key:string]:unknown}
 requirements:{minimum_amount:number;max_settlement_hours:number;desired_tenor_days:number}
 verification:Record<string,unknown>
 risk:{score:number;band:string;[key:string]:unknown}
}

const base=import.meta.env.VITE_CAPITAL_MARKET_URL||'http://127.0.0.1:8002'
const apiBase=import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000'

const traceIcon=(state:string)=>{
 if(state==='done')return <span className="trace-mark done">✓</span>
 if(state==='failed')return <span className="trace-mark failed">×</span>
 if(state==='running')return <span className="trace-mark running">◉</span>
 if(state==='skipped')return <span className="trace-mark skipped">→</span>
 return <span className="trace-mark">○</span>
}

export default function CapitalAgents({providers,error:providerError}:{providers:Provider[];error:string}){
 const [payload,setPayload]=useState<Payload|null>(null)
 const [phase,setPhase]=useState<'idle'|'loading'|'ready'|'error'>('idle')
 const [error,setError]=useState('')
 const [refresh,setRefresh]=useState(false)
 const [file,setFile]=useState<File|null>(null)
 const [parsing,setParsing]=useState(false)
 const [parseError,setParseError]=useState('')
 const [marketInput,setMarketInput]=useState<MarketInput|null>(null)

 const buildRequest=(market:MarketInput,providerList:Provider[])=>{
  return {
   opportunity_id:`OPP-${market.invoice.invoice_number||'CAPITAL-AGENTS'}`,
   invoice:market.invoice,
   requirements:market.requirements,
   verification:market.verification,
   risk:market.risk,
   providers:providerList.map(p=>({...p,preferred_industries:p.preferred_industries??[]})),
  }
 }

 const run=async(forceRefresh=false,market?:MarketInput)=>{
  setError('');setPhase('loading');setRefresh(forceRefresh)
  try{
   const marketData=market||marketInput
   if(!marketData)throw new Error('No invoice data. Upload a PDF invoice to begin.')
   let liveProviders=providers
   if(!liveProviders.length){
    const res=await fetch(`${apiBase}/api/providers`)
    if(!res.ok)throw new Error('Provider state unavailable from the marketplace.')
    liveProviders=await res.json() as Provider[]
   }
   if(!liveProviders.length)throw new Error('No capital providers available in the marketplace.')
   const body:any=buildRequest(marketData,liveProviders)
   body.companies={seller:marketData.invoice.supplier_name??null,client:marketData.invoice.buyer_name??null,amount:marketData.invoice.amount??null}
   const url=forceRefresh?`${base}/analysis?refresh=true`:`${base}/analysis`
   const response=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
   const responseBody=await response.json().catch(()=>null)
   if(!response.ok)throw new Error(responseBody&&typeof responseBody==='object'&&'detail' in responseBody?String(responseBody.detail):`Agent request failed: ${response.status}`)
   if(!responseBody||!Array.isArray(responseBody.offers))throw new Error('Agent returned an unexpected payload')
   setPayload(responseBody);setPhase('ready')
  }catch(e){setError(e instanceof Error?e.message:'Capital agents failed');setPhase('error')}
 }

 const parseAndRun=async(parsedFile:File)=>{
  setParsing(true);setParseError('')
  try{
   const formData=new FormData()
   formData.append('file',parsedFile)
   const res=await fetch(`${apiBase}/api/invoices/parse-pdf`,{method:'POST',body:formData})
   const parseBody=await res.json().catch(()=>null)
   if(!res.ok)throw new Error(parseBody&&typeof parseBody==='object'&&'detail' in parseBody?String(parseBody.detail):`Invoice parse failed: ${res.status}`)
   if(!parseBody?.invoice||!parseBody?.evaluation)throw new Error('Invoice parsed but insufficient data for the capital agent.')
   const market:MarketInput={
    invoice:parseBody.invoice,
    requirements:{minimum_amount:Math.round(parseBody.invoice.amount*0.8),max_settlement_hours:48,desired_tenor_days:60},
    verification:parseBody.evaluation.verification,
    risk:parseBody.evaluation.risk,
   }
   setMarketInput(market)
   await run(false,market)
  }catch(e){setParseError(e instanceof Error?e.message:'Invoice parse failed')}
  finally{setParsing(false)}
 }

 // On first visit, load the latest real opportunity from the marketplace so
 // the agent analyses real backend data — never a hardcoded scenario.
 useEffect(()=>{
  if(payload||phase!=='idle'||marketInput)return
  const load=async()=>{
   try{
    const res=await fetch(`${apiBase}/api/opportunities`)
    if(!res.ok)return
    const items=await res.json()
    const latest=(items||[]).find((item:any)=>item.invoice&&item.evaluation?.risk&&item.evaluation?.verification)
    if(latest)setMarketInput({invoice:latest.invoice,requirements:latest.requirements,verification:latest.evaluation.verification,risk:latest.evaluation.risk})
   }catch{/* stay waiting for an invoice */}
  }
  void load()
 },[payload,phase,marketInput])

 useEffect(()=>{
  if(payload||phase!=='idle'||!marketInput)return
  void run(false)
 },[payload,phase,marketInput])

 const analyses=payload?.offers||[]
 const offers=analyses.filter(a=>a.offer.status==='OFFER')
 const declines=analyses.filter(a=>a.offer.status==='DECLINE')
 const research=payload?.research?.research||null
 const intelligences=payload?.research?.providers||[]
 const companies=payload?.companies||null
 const trace=payload?.trace||null
 const telemetry=research?.telemetry
 const cached=research?.status==='cached'
 const invoice=marketInput?.invoice
 const risk=marketInput?.risk

 return <main>
  <header><div><p className="eyebrow">CAPITAL PROVIDERS • CAPITAL INTELLIGENCE</p><h1>Capital <em>agents.</em></h1><p className="lede">Autonomous provider agents that research the real capital market, score official provider intelligence, and price working capital under their own liquidity, risk and portfolio constraints.</p></div><div className="ca-actions"><button className="primary" onClick={()=>void run(false)} disabled={phase==='loading'||!marketInput}>{phase==='loading'?<Activity className="spin"/>:<Sparkles/>}{phase==='loading'?'Agent is analysing…':'Run agent analysis'}</button>{payload&&<button className="ca-refresh" onClick={()=>void run(true)} disabled={phase==='loading'}><RefreshCw/> Refresh research</button>}</div></header>
  {(error||providerError)&&<div className="error-banner" role="alert"><strong>Agent request failed.</strong> {error||providerError} <button onClick={()=>void run(false)} disabled={phase==='loading'}>Retry</button></div>}

  <section className="ca-panel ca-invoice-input"><div className="ca-panel-head"><div><ShieldCheck/> INVOICE INPUT</div><span className="ca-trace-time">{invoice?'Invoice data loaded from the marketplace':'Upload a PDF invoice to drive the agent'}</span></div><div className="ca-invoice-row"><input type="file" accept=".pdf,application/pdf" onChange={e=>setFile(e.target.files?.[0]||null)}/><button className="ca-refresh" onClick={()=>file&&void parseAndRun(file)} disabled={!file||parsing||phase==='loading'}>{parsing?<Activity className="spin"/>:<Banknote/>}{parsing?'Parsing invoice…':'Parse & run agent'}</button></div>{parseError&&<div className="error-banner" role="alert"><strong>Invoice parse failed.</strong> {parseError}</div>}{invoice&&<div className="ca-invoice-summary"><div><small>SELLER</small><strong>{invoice.supplier_name||'—'}</strong></div><div><small>CLIENT</small><strong>{invoice.buyer_name||'—'}</strong></div><div><small>INVOICE AMOUNT</small><strong>{money(invoice.amount)}</strong></div></div>}</section>

  <section className="provenance" aria-label="Agent provenance"><div><small>CAPITAL MARKET AGENT</small><span className={phase==='ready'?'service':phase==='error'?'unavailable':'fixture'}>● {phase==='ready'?'SERVICE':phase==='error'?'UNAVAILABLE':'PENDING'}</span></div><div><small>MARKET REGIME</small><span>{analyses[0]?analyses[0].market.regime:'—'}</span></div><div><small>RESEARCH</small><span>{telemetry?`${telemetry.searches} search • ${telemetry.pages_scraped} pages`:'—'}</span></div><p>{cached?'Using cached provider intelligence — no new web research this run.':telemetry?'Live Firecrawl research with real official sources.':'No agent analysis received yet.'}</p></section>

  {phase==='loading'?<section className="empty-market"><Activity className="spin"/><div><p className="eyebrow">CAPITAL AGENT ACTIVITY</p><h2>Running the capital intelligence pipeline.</h2><p>Invoice received → risk loaded → capital market searched → providers researched → terms extracted → providers scored → suitability evaluated → constraints checked → price calculated → offer generated.</p></div></section>:
  phase==='error'?<section className="empty-market"><ShieldCheck/><div><p className="eyebrow">AGENT UNAVAILABLE</p><h2>Could not reach the capital agent at {base}.</h2><p>Ensure the capital-market service is running on :8002, then retry. The tab renders live agent output only — no fabricated decisions.</p></div></section>:
  phase==='ready'&&payload?<>
  <div className="ca-grid">
   <div className="ca-main">
    {research&&<section className="ca-panel"><div className="ca-panel-head"><div><Globe/> CAPITAL MARKET INTELLIGENCE</div><span className={`ca-pill ${research.status}`}>{research.status==='live'?'LIVE WEB RESEARCH':research.status==='cached'?'CACHED INTELLIGENCE':'RESEARCH UNAVAILABLE'}</span></div><div className="ca-research-meta"><span>Last research <b>{time(telemetry?.last_research_at)}</b></span><span>Providers researched <b>{telemetry?.providers_researched||0}</b></span><span>Cached <b>{telemetry?.cache_hits||0}</b></span><span>Firecrawl</span></div>{research.error&&<p className="factor-failure">× {research.error}</p>}</section>}

    {trace&&<section className="ca-panel"><div className="ca-panel-head"><div><Activity/> CAPITAL AGENT ACTIVITY</div><span className="ca-trace-time">{time(trace.started_at)} → {time(trace.finished_at)}</span></div><div className="ca-trace">{trace.steps.map(step=><div key={step.key} className={`ca-trace-step ${step.state}`}>{traceIcon(step.state)}<span>{step.label}</span>{step.detail&&<small>{step.detail}</small>}</div>)}</div></section>}

    {intelligences.length>0&&<section className="ca-panel"><div className="ca-panel-head"><div><Search/> PROVIDER INTELLIGENCE</div><span className="ca-trace-time">Official sources researched</span></div><div className="ca-intel-grid">{intelligences.map(intel=><ProviderIntelligenceCard key={intel.provider.source_url} intel={intel}/>)}</div></section>}

    {companies&&<section className="ca-panel"><div className="ca-panel-head"><div><Globe/> COMPANY REFERENCE</div><span className="ca-trace-time">Public company information for the invoice parties</span></div><div className="ca-intel-grid"><CompanyPanel title="SELLER INFORMATION" research={companies.seller}/><CompanyPanel title="CLIENT INFORMATION" research={companies.client}/></div></section>}

    <section className="ca-panel"><div className="ca-panel-head"><div><Sparkles/> AGENT OFFER ARENA</div><span><i className="ca-dot"/> {analyses.length} providers • {offers.length} offers • {declines.length} declines</span></div><div className="provider-list">{analyses.map(a=><AgentCard key={a.provider.id} analysis={a} rateAdjustment={payload?.research?.rate_adjustment||0} invoiceAmount={invoice?.amount||0} riskScore={risk?.score||0} riskBand={risk?.band||'—'}/>)}</div></section>
   </div>

   <aside className="ca-side">
    <section className="ca-panel ca-budget"><div className="ca-panel-head"><div><Gauge/> WEB RESEARCH BUDGET</div></div><dl className="ca-budget-grid"><div><dt>Searches</dt><dd>{telemetry?.searches??'—'}</dd></div><div><dt>Pages scraped</dt><dd>{telemetry?.pages_scraped??'—'}</dd></div><div><dt>Cache hits</dt><dd>{telemetry?.cache_hits??'—'}</dd></div><div><dt>Cache misses</dt><dd>{telemetry?.cache_misses??'—'}</dd></div></dl><p className="ca-budget-note">{cached?'Provider data cached ✓ — re-runs reuse the cache without new Firecrawl calls.':'Provider data cached ✓ after this run.'}</p></section>
    <section className="ca-panel ca-decision"><div className="ca-panel-head"><div><Landmark/> CAPITAL AGENT DECISION</div></div><DecisionSection analyses={analyses} intelligences={intelligences}/></section>
   </aside>
  </div>
  </>:
  <section className="empty-market"><Banknote/><div><p className="eyebrow">WAITING FOR INVOICE DATA</p><h2>Upload an invoice PDF to start the agent.</h2><p>The Capital Agent analyses real marketplace data only — no demo scenarios. Upload a PDF invoice above, or run the flagship market from Market pulse to populate real opportunities.</p></div></section>}
 </main>
}

function CompanyPanel({title,research}:{title:string;research:CompanyResearch}){
 const sourceFacts=research.facts.filter(f=>f.confidence>0&&f.field!=='signal')
 const signalFacts=research.facts.filter(f=>f.field==='signal'&&f.confidence>0)
 return <article className="ca-intel-card ca-company-card">
  <div className="ca-intel-head"><div><h3>{research.name||'—'}</h3><small>{title}</small></div>{research.status!=='unavailable'?<span className={`ca-pill ${research.status}`}>{research.status==='live'?'LIVE WEB DATA':research.status==='cached'?'CACHED':'—'}</span>:<span className="ca-pill unavailable">UNAVAILABLE</span>}</div>
  {research.error&&<p className="factor-failure">× {research.error}</p>}
  <div className="ca-company-facts">
   {sourceFacts.map(f=><div key={f.field} className="ca-fact"><b>{f.field}</b><span>{f.value.length>200?f.value.slice(0,200)+'…':f.value}</span><small>{f.source_title||'Source'} • {Math.round(f.confidence*100)}% confidence</small></div>)}
   {sourceFacts.length===0&&<p className="ca-none">No public company details found for this party.</p>}
  </div>
  {signalFacts.length>0&&<div className="ca-company-signals"><p className="eyebrow">FINANCIAL / RISK SIGNALS</p>{signalFacts.map((f,i)=><div key={i} className="ca-fact signal"><span>{f.value.length>200?f.value.slice(0,200)+'…':f.value}</span><small>{f.source_title||'Source'}</small></div>)}</div>}
  {research.inferences.length>0&&<div className="ca-company-inferences"><p className="eyebrow">AGENT INFERENCES</p>{research.inferences.map((f,i)=><div key={i} className="ca-fact inference"><span>{f.value}</span><small>Derived by the agent from source facts</small></div>)}</div>}
  <div className="ca-provenance-row"><small>{time(research.retrieved_at)}</small>{research.source_url?<a href={research.source_url} target="_blank" rel="noreferrer">View Source <ExternalLink/></a>:null}</div>
 </article>
}

function ProviderIntelligenceCard({intel}:{intel:Intelligence}){
 const p=intel.provider,s=intel.score
 return <article className="ca-intel-card">
  <div className="ca-intel-head"><div><h3>{p.provider_name}</h3><small>{p.provider_type}</small></div><div className="ca-score-ring"><strong>{s.total.toFixed(0)}</strong><small>/ 100</small></div></div>
  <div className="ca-score-dims">{s.dimensions.map(dim=><div key={dim.name} className="ca-score-dim" title={`${dim.explanation}\nEvidence: ${dim.evidence}`}><span>{dim.name}</span><b>{dim.confidence>0?dim.score.toFixed(0):'UNKNOWN'}</b><i style={{width:`${Math.min(100,Math.max(0,Math.round(dim.score*(dim.confidence>0?1:0.1))))}%`}} className={dim.confidence===0?'unknown':''}/></div>)}</div>
  <details className="ca-evidence"><summary>Source evidence</summary><div className="ca-facts"><p className="eyebrow">SOURCE FACTS</p>{intel.facts.filter(f=>f.confidence>0).map(f=><div key={`${f.field}-${f.value}`} className="ca-fact"><b>{f.field}</b><span>{f.value.length>160?f.value.slice(0,160)+'…':f.value}</span><small><a href={f.source_url} target="_blank" rel="noreferrer">{f.source_title||'Official source'}</a> • {Math.round(f.confidence*100)}% confidence</small></div>)}<p className="eyebrow">AGENT INFERENCES</p>{intel.inferences.length?intel.inferences.map(f=><div key={`i-${f.field}`} className="ca-fact inference"><b>{f.field}</b><span>{f.value}</span><small>Derived by the agent from source facts</small></div>):<p className="ca-none">No inferences drawn.</p>}</div></details>
  <div className="ca-financing"><p className="eyebrow">FINANCING INTELLIGENCE</p>{['rate','tenor','limit','advance','fees','settlement','eligibility'].map(field=>{const f=p.facts.find(x=>x.field===field);return <div key={field} className="ca-fin-row"><span>{field}</span><b className={f&&f.confidence>0?'':'unknown'}>{f&&f.confidence>0?(f.value.length>80?f.value.slice(0,80)+'…':f.value):'UNKNOWN'}</b></div>})}</div>
  <div className="ca-provenance-row"><small>LIVE WEB DATA • {time(p.retrieved_at)}</small><a href={p.source_url} target="_blank" rel="noreferrer">View Source <ExternalLink/></a></div>
 </article>
}

function DecisionSection({analyses,intelligences}:{analyses:Analysis[];intelligences:Intelligence[]}){
 const winners=analyses.filter(a=>a.offer.status==='OFFER').sort((a,b)=>((b.offer.financed_amount||0)-(a.offer.financed_amount||0)))
 const winner=winners[0]
 const researched=intelligences.filter(i=>i.suitable)
 const topIntel=researched.sort((a,b)=>b.score.total-a.score.total)[0]
 if(!winner)return <p className="ca-none">No provider offer generated.</p>
 return <div className="ca-decision-body">
  <div className="ca-decision-offer"><span className="ca-pill offer">OFFER</span><strong>{money(winner.offer.financed_amount)}</strong><div className="ca-decision-terms"><span>{pct(winner.offer.advance_rate)} Advance</span><span>{winner.pricing?`${winner.pricing.final_rate}%`:'—'} Rate</span><span>{winner.offer.tenor_days} Days</span></div><p>Expected return <b>{winner.offer.expected_return}%</b> • Fees {money(winner.offer.fees)}</p></div>
  <div className="ca-why"><p className="eyebrow">WHY THIS OFFER?</p>{winner.offer.reasons.slice(0,6).map(r=><div key={r} className="ca-why-row"><span>{r.startsWith('−')||r.startsWith('- ')?'−':'✓'}</span><p>{r}</p></div>)}{topIntel&&<div className="ca-why-row"><span>✓</span><p>{topIntel.provider.provider_name} researched with a provider score of {topIntel.score.total.toFixed(0)}/100 — published terms support the financing structure.</p></div>}</div>
 </div>
}

function AgentCard({analysis,rateAdjustment,invoiceAmount,riskScore,riskBand}:{analysis:Analysis;rateAdjustment:number;invoiceAmount:number;riskScore:number;riskBand:string}){
 const p=analysis.provider,o=analysis.offer,a=analysis.attractiveness,pr=analysis.pricing
 const declined=o.status==='DECLINE'
 return <article className={`provider ${declined?'ineligible':''}`}>
  <div className="provider-title"><div className="provider-icon">{p.provider_type==='BANK'?<Landmark/>:p.provider_type==='FINTECH'?<CircleDollarSign/>:<Banknote/>}</div><div><h3>{p.name}</h3><small>{p.provider_type} AGENT • {o.status}</small></div><div className="offer-badges">{!declined&&<b>OFFER</b>}{declined&&<b className="bad">DECLINED</b>}{a&&a.score>=80&&<b className="lowest">ATTRACTIVE</b>}</div></div>
  <div className="offer-stats"><div><small>RATE</small><strong>{pr?`${pr.final_rate}%`:'—'}</strong></div><div><small>ADVANCE</small><strong>{o.financed_amount?money(o.financed_amount):'DECLINED'}</strong></div><div><small>SETTLE</small><strong>{o.settlement_hours?`${o.settlement_hours}h`:'—'}</strong></div></div>
  {declined?<p className="fail">× {o.reasons.join(' • ')}</p>:<p className="pass">✓ Finances {money(o.financed_amount)} at {pr?.final_rate}% for {o.tenor_days} days</p>}
  <details><summary>Decision trace — why this decision?</summary>
   <div className="agent-block"><div className="eyebrow">OBSERVE</div><p className="ca-trace-line">Invoice {money(invoiceAmount)} • Risk {riskScore}/100 ({riskBand})</p></div>
   {a&&<div className="agent-block"><div className="eyebrow">OPPORTUNITY ATTRACTIVENESS • {a.score}/100</div><div className="ledger-factors">{a.factors.map(f=><div key={f.label} className={`factor-card ${f.score>=50?'positive':'negative'}`}><div className="factor-title"><span>{f.label}</span><b>{f.score.toFixed(0)}</b></div><p className="factor-desc">{f.explanation}</p></div>)}</div></div>}
   {pr&&<div className="agent-block"><div className="eyebrow">PRICE</div><div className="pricing-lines">{pr.lines.map((line,i)=><div key={i} className={i===pr.lines.length-1?'pricing-final':'pricing-line'}><span>{line}</span>{i<pr.lines.length-1&&<small>{['base','risk','tenor','industry','liquidity','portfolio','market','research'][i]}</small>}</div>)}</div>{rateAdjustment!==0&&<p className="ca-trace-line">Researched provider intelligence shifted pricing by {rateAdjustment>0?'+':''}{rateAdjustment} points.</p>}</div>}
   {!declined&&<div className="agent-block"><div className="eyebrow">DECIDE</div><div className="term-grid"><span>Financed amount</span><b>{money(o.financed_amount)}</b><span>Advance rate</span><b>{pct(o.advance_rate)}</b><span>Fees</span><b>{money(o.fees)}</b><span>Total effective cost</span><b>{money(o.total_effective_cost)}</b><span>Expected annualised return</span><b>{o.expected_return}%</b><span>Post-allocation exposure</span><b>{o.post_allocation_exposure_ratio!==null?`${(o.post_allocation_exposure_ratio*100).toFixed(0)}% of capacity`:'—'}</b></div></div>}
   {declined&&<div className="agent-block"><div className="eyebrow">CONSTRAINT GATES</div>{analysis.hard.failures.map(f=><p className="factor-failure" key={f}>× {f}</p>)}</div>}
   <div className="agent-block"><div className="eyebrow">REASONS</div><ul>{o.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul></div>
   <div className="agent-block"><div className="eyebrow">PROVIDER STATE</div><div className="term-grid"><span>Available liquidity</span><b>{money(p.available_liquidity)}</b><span>Current exposure</span><b>{money(p.current_exposure)}</b><span>Portfolio capacity</span><b>{money(p.portfolio_capacity)}</b><span>Risk appetite</span><b>{p.risk_appetite}/100</b><span>Max ticket</span><b>{money(p.max_ticket_size)}</b><span>Settlement speed</span><b>{p.settlement_hours}h</b></div></div>
  </details>
 </article>
}
