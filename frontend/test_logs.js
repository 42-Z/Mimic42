const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 }
  });
  const page = await context.newPage();

  try {
    // Open the agent logs page
    await page.goto('http://localhost:3000/agent/30dbdfe8-f6fd-4870-aa4f-a2186eea9cc6?tab=logs', {
      waitUntil: 'networkidle',
      timeout: 30000
    });

    // Wait a bit for data to load
    await page.waitForTimeout(3000);

    // Take screenshot
    await page.screenshot({ 
      path: '/tmp/mimic42_logs_test.png',
      fullPage: true 
    });

    // Get page content to analyze
    const content = await page.content();
    const hasLogs = content.includes('Нет записей') || content.includes('incoming') || content.includes('outgoing');
    
    console.log('Page loaded successfully');
    console.log('Has logs content:', hasLogs);
    
    // Try to find log entries
    const logEntries = await page.$$eval('.font-mono', elements => elements.length);
    console.log('Number of .font-mono elements:', logEntries);

  } catch (error) {
    console.error('Error:', error.message);
    await page.screenshot({ path: '/tmp/mimic42_logs_error.png' });
  } finally {
    await browser.close();
  }
})();
