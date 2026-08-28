import {describe,expect,it} from 'vitest'
import {money} from './App'
describe('Indian currency formatting',()=>{it('formats demo capital consistently',()=>expect(money(800000)).toContain('8,00,000'))})
