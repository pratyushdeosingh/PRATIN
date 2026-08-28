// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import {cleanup,render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import App from './App'
import {api} from './api'

vi.mock('./api',()=>({api:{reset:vi.fn(),scenarios:vi.fn(),create:vi.fn(),run:vi.fn(),settle:vi.fn(),metrics:vi.fn(),providers:vi.fn(),audit:vi.fn(),health:vi.fn()}}))

const offer=(overrides:Record<string,unknown>)=>({id:'offer',provider_id:'provider',provider_name:'Provider',provider_type:'BANK',status:'OFFER',annual_rate:10,advance_rate:.8,financed_amount:800000,fees:1000,tenor_days:60,settlement_hours:24,total_effective_cost:12000,expected_return:10.5,reasons:['Provider constraint checks passed.'],...overrides})
const factor={name:'Capital',score:92,weight:.28,explanation:'Advances enough usable capital.'}
const first={id:'OPP-FIRST',status:'MARKET_RUN',invoice:{invoice_number:'INV-PRATIN-1001',supplier_name:'Shakti Components',buyer_name:'Orion Auto Systems',amount:1000000},requirements:{minimum_amount:800000,max_settlement_hours:48,desired_tenor_days:60},evaluation:{verification:{status:'VERIFIED',confidence:.95,reasons:[]},risk:{score:24,band:'LOW',factors:[]}},integration_status:{invoice_risk:'SERVICE',capital_market:'SERVICE'},match:{recommended_offer_id:'vega',policy_version:'matching-policy-1.1-demo',recommendation_reasons:['VegaFlow satisfies every supplier hard constraint.'],ranked_offers:[
 {offer:offer({id:'astra',provider_id:'bank-a',provider_name:'Astra Commercial Bank',annual_rate:8.22,financed_amount:700000,settlement_hours:96}),eligible:false,suitability_score:0,factors:[],hard_constraint_failures:['Offers ₹700,000, below required ₹800,000.','Settlement takes 96h, beyond the 48h limit.'],rank:null},
 {offer:offer({id:'vega',provider_id:'nbfc-b',provider_name:'VegaFlow NBFC',provider_type:'NBFC',annual_rate:9.42,financed_amount:870000}),eligible:true,suitability_score:88.4,factors:[factor],hard_constraint_failures:[],rank:1},
]}}
const second={...first,id:'OPP-SECOND',invoice:{...first.invoice,invoice_number:'INV-PRATIN-1002',supplier_name:'Nova Pharma Pack'},match:{...first.match,recommended_offer_id:'meridian',recommendation_reasons:['Meridian satisfies every supplier hard constraint.'],ranked_offers:[{offer:offer({id:'meridian',provider_id:'fund-d',provider_name:'Meridian Yield Fund',provider_type:'FUND',annual_rate:10.11,financed_amount:1120000,settlement_hours:48}),eligible:true,suitability_score:82.1,factors:[factor],hard_constraint_failures:[],rank:1}]}}
const metrics={available_liquidity:14600000,active_opportunities:1,offers_generated:3,financing_allocated:870000,settlements:1,provider_participation_rate:.75}
const before=[{id:'nbfc-b',name:'VegaFlow NBFC',available_liquidity:1650000,current_exposure:1300000}]
const after=[{id:'nbfc-b',name:'VegaFlow NBFC',available_liquidity:780000,current_exposure:2170000}]

beforeEach(()=>{
 vi.mocked(api.reset).mockResolvedValue({status:'reset',notice:'reset'})
 vi.mocked(api.scenarios).mockResolvedValue({urgent:{},strong:{}})
 vi.mocked(api.create).mockResolvedValueOnce(first as never).mockResolvedValueOnce(second as never)
 vi.mocked(api.run).mockResolvedValueOnce(first as never).mockResolvedValueOnce(second as never)
 vi.mocked(api.metrics).mockResolvedValue(metrics)
 vi.mocked(api.providers).mockResolvedValueOnce(before).mockResolvedValueOnce(after).mockResolvedValue(after)
 vi.mocked(api.audit).mockResolvedValue([{id:'AUD-1',timestamp:'2026-08-28T00:00:00Z',event_type:'SETTLEMENT_COMPLETED',opportunity_id:'OPP-FIRST',detail:'Settlement and provider state updated atomically.'}])
 vi.mocked(api.health).mockResolvedValue({status:'ok',service:'pratin-core',mode:'required',database:'supabase-postgres',version:'1.0.0'})
 vi.mocked(api.settle).mockResolvedValue({id:'STL-123',opportunity_id:'OPP-FIRST',offer_id:'vega',provider_id:'nbfc-b',amount:870000,status:'SIMULATED_SETTLED',settled_at:'2026-08-28T00:00:00Z',notice:'Simulation only. No real funds moved.'})
})
afterEach(()=>{cleanup();vi.clearAllMocks()})

describe('PRATIN cockpit',()=>{
 it('starts truthfully without fabricated metrics, offers, or acceptance',()=>{
  render(<App/>)
  expect(screen.getByText('No allocation has run yet.')).toBeInTheDocument()
  expect(screen.queryByText('Astra Commercial Bank')).not.toBeInTheDocument()
  expect(screen.queryByRole('button',{name:/accept/i})).not.toBeInTheDocument()
  expect(screen.getAllByText('—').length).toBeGreaterThan(0)
  expect(screen.getAllByText(/UNAVAILABLE/)).toHaveLength(3)
 })

 it('shows backend provenance, lowest-rate loss, explanations, settlement mutation, and retained reallocation history',async()=>{
  const user=userEvent.setup()
  render(<App/>)
  await user.click(screen.getByRole('button',{name:/run flagship market/i}))
  await screen.findByText('Astra Commercial Bank')
  expect(screen.getAllByText('● SERVICE')).toHaveLength(2)
  expect(screen.getByText('● SUPABASE POSTGRES')).toBeInTheDocument()
  expect(screen.getByText('LOWEST RATE')).toBeInTheDocument()
  expect(screen.getByText('INELIGIBLE')).toBeInTheDocument()
  expect(screen.getByText('RECOMMENDED')).toBeInTheDocument()
  await user.click(screen.getAllByText('Why this offer?')[1])
  expect(screen.getByText('Advances enough usable capital.')).toBeInTheDocument()
  await user.click(screen.getByRole('button',{name:/accept & simulate settlement/i}))
  await screen.findByText(/SIMULATED SETTLEMENT • STL-123/)
  expect(screen.getAllByText(/₹16,50,000/).length).toBeGreaterThan(0)
  expect(screen.getAllByText(/₹7,80,000/).length).toBeGreaterThan(0)
  await user.click(screen.getByRole('button',{name:/run next allocation/i}))
  await screen.findByText(/Meridian Yield Fund wins allocation two/)
  expect(screen.getByText('VegaFlow NBFC',{selector:'.history-item strong'})).toBeInTheDocument()
  expect(screen.getByText('Meridian Yield Fund',{selector:'.history-item strong'})).toBeInTheDocument()
  expect(screen.getByText(/second winner changed because settlement changed provider capacity/i)).toBeInTheDocument()
 })

 it('shows API failures and never fabricates success',async()=>{
  vi.mocked(api.reset).mockRejectedValueOnce(new Error('Required integration unavailable'))
  const user=userEvent.setup()
  render(<App/>)
  await user.click(screen.getByRole('button',{name:/run flagship market/i}))
  await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('Required integration unavailable'))
  expect(screen.queryByText('RECOMMENDED')).not.toBeInTheDocument()
  expect(screen.queryByRole('button',{name:/accept/i})).not.toBeInTheDocument()
 })

 it('labels degraded fixture provenance without calling it service',async()=>{
  vi.mocked(api.run).mockReset().mockResolvedValueOnce({...first,integration_status:{invoice_risk:'DEGRADED_FIXTURE',capital_market:'FIXTURE'}} as never)
  const user=userEvent.setup()
  render(<App/>)
  await user.click(screen.getByRole('button',{name:/run flagship market/i}))
  await screen.findByText('● DEGRADED FIXTURE')
  expect(screen.getByText('● FIXTURE')).toBeInTheDocument()
  expect(screen.getByText(/service was unavailable/i)).toBeInTheDocument()
  expect(screen.queryByText(/both responses came through validated HTTP/i)).not.toBeInTheDocument()
 })

 it('disables the primary action while the market request is active',async()=>{
  let finishReset:(value:{status:string;notice:string})=>void=()=>undefined
  vi.mocked(api.reset).mockReset().mockImplementationOnce(()=>new Promise(resolve=>{finishReset=resolve}))
  const user=userEvent.setup()
  render(<App/>)
  const button=screen.getByRole('button',{name:/run flagship market/i})
  await user.click(button)
  expect(screen.getByRole('button',{name:/agents are competing/i})).toBeDisabled()
  finishReset({status:'reset',notice:'reset'})
  await screen.findByText('Astra Commercial Bank')
 })
})
