import { chromium } from 'playwright'
const b = await chromium.launch()
const page = await b.newPage({ viewport:{width:1500,height:1100} })
await page.goto('https://chat.growmiq.io/login', { waitUntil:'domcontentloaded', timeout:25000 })
await page.fill('input[type="email"]', process.env.PF_EMAIL); await page.fill('input[type="password"]', process.env.PF_PASS)
await page.click('button[type="submit"]'); await page.waitForTimeout(3500)
await page.goto('https://chat.growmiq.io/platform/plans', { waitUntil:'domcontentloaded', timeout:25000 })
await page.waitForTimeout(3000)
const feat = page.locator('section.table-panel').filter({ hasText:'Complete feature availability' })
const wrap = feat.locator('.table-wrap')
// The real question: does the table overflow its wrapper, i.e. are the plan
// columns off-screen?
const m = await wrap.evaluate(el => ({ client: el.clientWidth, scroll: el.scrollWidth }))
console.log('wrapper', m.client, 'table', m.scroll, '=> overflows:', m.scroll > m.client + 2)
const heads = feat.locator('thead th')
for (let i = 0; i < await heads.count(); i++) {
  const h = heads.nth(i)
  const box = await h.boundingBox()
  console.log(`  col ${i}: "${(await h.textContent()||'').trim().split('\n')[0]}" visible=${!!box && box.x + box.width <= m.client + 40}`)
}
console.log('category group rows:', await feat.locator('.group-row').count())
await page.screenshot({ path:'./fv.png', fullPage:true })
await b.close()
