import { chromium } from 'playwright';
import { fileURLToPath } from 'node:url';

const screenshotPath = fileURLToPath(new URL('../../logged-in.png', import.meta.url));
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
await page.goto('http://localhost:5173/login', { waitUntil: 'load', timeout: 10000 });
await page.waitForTimeout(500);
await page.fill('input[type="email"]', 'user@example.test');
await page.fill('input[type="password"]', 'ChangeMe123!');
await page.click('button:has-text("登录")');
await page.waitForTimeout(2000);
await page.screenshot({ path: screenshotPath, fullPage: true });
console.log('logged-in done');
await browser.close();
