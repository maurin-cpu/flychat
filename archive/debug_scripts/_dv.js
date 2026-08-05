const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const page = await b.newPage({ viewport:{width:720,height:1000} });
  await page.goto('http://127.0.0.1:5000/static/torn_test.html',{waitUntil:'networkidle'});
  await page.waitForTimeout(900);
  const el = await page.$('#b');
  await el.screenshot({path:'/tmp/dv_full.png'});  // element screenshot = full content
  console.log('done');
  await b.close();
})();
