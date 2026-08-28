export type IntegrationStatus='SERVICE'|'FIXTURE'|'DEGRADED_FIXTURE'|'UNAVAILABLE'
export type Offer={id:string;provider_id:string;provider_name:string;provider_type:string;status:'OFFER'|'DECLINE';annual_rate:number|null;advance_rate:number|null;financed_amount:number|null;fees:number|null;tenor_days:number|null;settlement_hours:number|null;total_effective_cost:number|null;expected_return:number|null;reasons:string[]}
export type ScoreFactor={name:string;score:number;weight:number;explanation:string}
export type RankedOffer={offer:Offer;eligible:boolean;suitability_score:number;factors:ScoreFactor[];hard_constraint_failures:string[];rank:number|null}
export type Opportunity={id:string;status:string;invoice:{invoice_number:string;supplier_name:string;buyer_name:string;amount:number};requirements:{minimum_amount:number;max_settlement_hours:number;desired_tenor_days:number};evaluation?:{verification:{status:string;confidence:number;reasons:string[]};risk:{score:number;band:string;factors:Array<{label:string;impact:string;points:number;explanation:string}>}};match?:{recommended_offer_id:string|null;ranked_offers:RankedOffer[];recommendation_reasons:string[];policy_version:string};integration_status:Record<string,IntegrationStatus>}
export type Metrics={available_liquidity:number;active_opportunities:number;offers_generated:number;financing_allocated:number;settlements:number;provider_participation_rate:number}
export type Provider={id:string;name:string;available_liquidity:number;current_exposure:number}
export type Settlement={id:string;opportunity_id:string;offer_id:string;provider_id:string;amount:number;status:string;settled_at:string;notice:string}
export type AuditEvent={id:string;timestamp:string;event_type:string;opportunity_id:string|null;detail:string}
export type Health={status:string;service:string;mode:string;database:'sqlite'|'supabase-postgres';version:string}

const base=import.meta.env.VITE_API_BASE_URL||'http://127.0.0.1:8000'

async function request<T>(path:string,init?:RequestInit):Promise<T>{
 const response=await fetch(base+path,{headers:{'Content-Type':'application/json'},...init})
 const payload=await response.json().catch(()=>null)
 if(!response.ok){
  const detail=payload&&typeof payload==='object'&&'detail' in payload?String(payload.detail):`Request failed: ${response.status}`
  throw new Error(detail)
 }
 if(payload===null)throw new Error(`Invalid JSON response from ${path}`)
 return payload as T
}

export const api={
 scenarios:()=>request<Record<string,unknown>>('/api/scenarios'),
 reset:()=>request<{status:string;notice:string}>('/api/demo/reset',{method:'POST'}),
 create:(body:unknown)=>request<Opportunity>('/api/opportunities',{method:'POST',body:JSON.stringify(body)}),
 run:(id:string)=>request<Opportunity>(`/api/opportunities/${id}/run-market`,{method:'POST'}),
 settle:(id:string,offerId:string)=>request<Settlement>(`/api/opportunities/${id}/accept/${offerId}`,{method:'POST'}),
 metrics:()=>request<Metrics>('/api/platform/metrics'),
 providers:()=>request<Provider[]>('/api/providers'),
 audit:()=>request<AuditEvent[]>('/api/audit'),
 health:()=>request<Health>('/health'),
}
