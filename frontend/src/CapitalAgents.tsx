import {Provider} from './api'
import {money} from './format'

export default function CapitalAgents({providers,error}:{providers:Provider[];error:string}){
 return <main><header><div><p className="eyebrow">BACKEND PROVIDER STATE • SYNTHETIC DEMO</p><h1>Capital <em>agents.</em></h1><p className="lede">Provider policies and mutable portfolio state come from the backend. Liquidity and exposure change only through simulated settlement.</p></div></header>
 {error&&<div className="error-banner" role="alert">Capital agents unavailable: {error}</div>}
 <section className="agent-grid">{providers.length===0?<div className="empty-ledger">No provider state is available.</div>:providers.map(provider=><article className="agent-card" key={provider.id}><div><small>{provider.provider_type} AGENT • {provider.id}</small><h3>{provider.name}</h3></div><dl><div><dt>Available liquidity</dt><dd>{money(provider.available_liquidity)}</dd></div><div><dt>Current exposure</dt><dd>{money(provider.current_exposure)}</dd></div><div><dt>Portfolio capacity</dt><dd>{money(provider.portfolio_capacity)}</dd></div><div><dt>Maximum ticket</dt><dd>{money(provider.max_ticket_size)}</dd></div><div><dt>Risk appetite</dt><dd>{provider.risk_appetite}/100</dd></div><div><dt>Minimum return</dt><dd>{provider.min_return_rate}%</dd></div><div><dt>Settlement speed</dt><dd>{provider.settlement_hours}h</dd></div></dl></article>)}</section>
 </main>
}
