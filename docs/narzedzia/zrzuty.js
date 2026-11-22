// Odświeżenie zrzutów ekranu do dokumentacji (docs/img/*.jpg).
//   1. LLM_ENABLED=0 python -m odw2json web --port 8765
//   2. node docs/narzedzia/zrzuty.js <hacknation-2026>/dane
// Wczytuje fikcyjne sprawy przyklad_01..03 ze zbioru treningowego UZP i robi zrzuty kolejnych ekranów.
const { chromium } = require('playwright');
const path = require('path');
const D = path.resolve(process.argv[2] || '../hacknation-2026/dane') + '/';
const OUT = path.join(__dirname, '..', 'img') + '/';
const snap = (p, n) => p.screenshot({ path: OUT + n + '.jpg', type: 'jpeg', quality: 82 });
(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  await p.goto('http://127.0.0.1:8765/');
  await p.waitForTimeout(800);
  if (await p.locator('#whoDlg[open]').count()) { await p.fill('#whoIn', 'Anna Kowalska'); await p.click('#whoForm button[type=submit]'); }
  for (const c of ['przyklad_01', 'przyklad_02', 'przyklad_03']) { await p.setInputFiles('#pickFolder', D + c); await p.waitForTimeout(400); }
  await p.waitForTimeout(12000);
  await snap(p, 'sprawa');
  await p.click('nav.side [data-go=start]'); await p.waitForTimeout(600); await snap(p, 'start');
  await p.click('nav.side [data-case=przyklad_01]'); await p.waitForTimeout(600);
  await p.locator('tr', { hasText: 'odwolanie.pdf' }).locator('button', { hasText: 'Otwórz' }).click();
  await p.waitForTimeout(2500); await snap(p, 'dokument');
  await p.locator('#panel button', { hasText: /^Wszystkie$/ }).click(); await p.waitForTimeout(500);
  const f = p.locator('.field[data-path*="nip"]').first(); console.log(await f.getAttribute('data-path')); await f.click();
  await p.waitForTimeout(1800); await snap(p, 'zrodlo');
  await p.click('#back'); await p.waitForTimeout(500);
  await p.click('button:has-text("Kontrola formalna i pismo")'); await p.waitForTimeout(1500); await snap(p, 'kontrola');
  await p.locator('#h-pismo').scrollIntoViewIfNeeded(); await p.waitForTimeout(500); await snap(p, 'pismo');
  for (const v of ['rejestr', 'terminy', 'klasy']) { await p.click(`nav.side [data-go=${v}]`); await p.waitForTimeout(1200); await snap(p, v); }
  await p.click('nav.side [data-case=przyklad_02]'); await p.waitForTimeout(600);
  await p.evaluate(() => document.documentElement.setAttribute('data-theme', 'dark')); await p.waitForTimeout(400); await snap(p, 'ciemny');
  await b.close();
})();
