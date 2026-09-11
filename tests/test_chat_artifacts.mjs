// Real Chrome + real local API; fixture conversations never submit a model task.
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm, mkdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {puppeteer} from '../node_modules/chrome-devtools-mcp/build/src/third_party/index.js';

const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const python=process.env.CLARA_TEST_PYTHON || path.join(root, process.platform==='win32'?'.venv/Scripts/python.exe':'.venv/bin/python');
const chrome=process.env.CLARA_TEST_CHROME || (process.platform==='darwin'?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':path.join(process.env.ProgramFiles || 'C:\\Program Files','Google/Chrome/Application/chrome.exe'));

test('artifact cards survive replay, stay with their task, and download real files', {timeout:60000}, async()=>{
    assert.ok(existsSync(chrome), 'Set CLARA_TEST_CHROME to an installed Chrome executable.');
    const work=await mkdtemp(path.join(tmpdir(),'clara-artifact-ui-'));
    const server=spawn(python,['tests/ui_fixture.py'],{cwd:root,stdio:['ignore','pipe','pipe']});
    let browser;
    let serverError='';
    server.stderr.on('data', chunk=>serverError+=chunk);
    try{
        const fixture=await new Promise((resolve,reject)=>{
            let buffer='';
            const timer=setTimeout(()=>reject(new Error('Fixture startup timed out: '+serverError)),10000);
            server.once('error',error=>{clearTimeout(timer);reject(error);});
            server.stdout.on('data',chunk=>{
                buffer+=chunk;
                if(buffer.includes('\n')){clearTimeout(timer);resolve(JSON.parse(buffer.split('\n')[0]));}
            });
        });
        for(let attempt=0;attempt<50;attempt++){
            try { await fetch(fixture.url.split('#')[0]); break; }
            catch { await new Promise(resolve=>setTimeout(resolve,100)); }
        }
        browser=await puppeteer.launch({executablePath:chrome,headless:true,userDataDir:path.join(work,'chrome'),args:['--no-first-run','--no-default-browser-check']});
        const page=await browser.newPage();
        page.setDefaultTimeout(10000);
        const errors=[];
        page.on('pageerror',error=>errors.push(error.message));
        await page.setViewport({width:1440,height:1000});
        await page.goto(fixture.url,{waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>!state.initializing);
        assert.equal(await page.evaluate(()=>state.cid),fixture.cid,
            await page.evaluate(()=>document.body.innerText));
        await page.waitForFunction(()=>document.querySelectorAll('#messages .artifact').length===2);
        await page.waitForFunction(()=>document.querySelectorAll('#messages .message[data-job]').length===5);
        await page.waitForSelector('#activity .activity-item.failed .tool-output');
        assert.match(await page.$eval('#activity summary', n=>n.textContent), /1\.3s/);
        assert.match(await page.$eval('#activity .tool-output', n=>n.textContent), /Application Example not found/);
        assert.equal(await page.$$eval('#activity img', nodes=>nodes.length), 0);
        const diagnosticHref=await page.$eval(`[data-usage-job="${fixture.first_job}"] a[download="clara-task-diagnostics.json"]`, n=>n.getAttribute('href'));
        const diagnostic=await page.evaluate(async href=>await (await fetch(href)).json(), diagnosticHref);
        assert.equal(diagnostic.task.id, fixture.first_job);
        assert.ok(diagnostic.events.some(e=>e.data.duration_ms===1250));
        const layout=await page.evaluate(()=>{
            const group=document.querySelector('.file-message');
            return {job:group.dataset.resultJob,previous:group.previousElementSibling.dataset.job,next:group.nextElementSibling.nextElementSibling.dataset.job,
                    inline:group.querySelectorAll('.artifact').length,sidebar:document.querySelectorAll('#artifacts .artifact').length};
        });
        assert.deepEqual(layout,{job:fixture.first_job,previous:fixture.first_job,next:fixture.second_job,inline:2,sidebar:2});
        assert.equal(await page.$$eval('.usage-message',nodes=>nodes.length),2);
        assert.match(await page.$eval(`[data-usage-job="${fixture.first_job}"]`,node=>node.innerText),/5,000/);
        assert.match(await page.$eval(`[data-usage-job="${fixture.first_job}"]`,node=>node.innerText),/\$0\.0314/);
        assert.match(await page.$eval('#usage',node=>node.innerText),/5,100 tokens/);
        assert.match(await page.$eval('#usage',node=>node.innerText),/\$0\.0334/);

        const cdp=await page.createCDPSession();
        await cdp.send('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:work});
        await page.click(`#messages a[data-file="${fixture.files[0].id}"]`);
        const downloaded=path.join(work,'clara-first-test.txt');
        for(let attempt=0;attempt<50 && !existsSync(downloaded);attempt++)await new Promise(resolve=>setTimeout(resolve,100));
        assert.equal(await readFile(downloaded,'utf8'),'Clara is connected.');
        await page.click('#usage .usage-export');
        const csv=path.join(work,'clara-task-usage.csv');
        for(let attempt=0;attempt<50 && !existsSync(csv);attempt++)await new Promise(resolve=>setTimeout(resolve,100));
        const report=await readFile(csv,'utf8');
        assert.match(report,/SDK API estimate USD/);
        assert.match(report,/5000,0\.0314/);
        await page.click(`[data-usage-job="${fixture.first_job}"] a[download="clara-task-diagnostics.json"]`);
        const logPath=path.join(work,'clara-task-diagnostics.json');
        for(let attempt=0;attempt<50 && !existsSync(logPath);attempt++)await new Promise(resolve=>setTimeout(resolve,100));
        assert.equal(JSON.parse(await readFile(logPath,'utf8')).task.id,fixture.first_job);

        await page.reload({waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>document.querySelectorAll('#messages .artifact').length===2);
        assert.equal(await page.$$eval('#artifacts .artifact',nodes=>nodes.length),2);
        assert.equal(await page.$$eval('.usage-message',nodes=>nodes.length),2);
        assert.match(await page.$eval('#usage',node=>node.innerText),/\$0\.0334/);

        // Live stream replacement must not lose cards or move older task files.
        await page.evaluate(()=>{
            eventReceived({id:10001,job_id:'live-job',kind:'user',data:{text:'Create a report.'}});
            eventReceived({id:10002,job_id:'live-job',kind:'delta',data:{text:'Preparing the download.'}});
            const event={id:10003,job_id:'live-job',kind:'artifact',data:{id:'live-file',name:'report <img src=x onerror=alert(1)>.txt',size:20}};
            eventReceived(event);eventReceived(event);
            eventReceived({id:10004,job_id:'live-job',kind:'assistant',data:{text:'Your report is ready.'}});
            eventReceived({id:10005,job_id:'live-job',kind:'status',data:{status:'completed'}});
        });
        assert.equal(await page.$$eval('#messages .artifact',nodes=>nodes.length),3);
        assert.equal(await page.$$eval('#messages img',nodes=>nodes.length),0);
        assert.equal(await page.$eval('[data-result-job="live-job"]',node=>node.previousElementSibling.dataset.job),'live-job');
        assert.equal(await page.$eval('[data-result-job="live-job"] a',node=>node.getAttribute('href')),'/api/files/live-file');
        assert.equal(await page.$$eval('.usage-message',nodes=>nodes.length),3);
        assert.match(await page.$eval('[data-usage-job="live-job"]',node=>node.innerText),/Incomplete usage/);
        assert.match(await page.$eval('#usage',node=>node.innerText),/2\/3 tasks report total tokens/);
        // A repeated final event updates the task; it must never add cost twice.
        await page.evaluate(()=>eventReceived({id:10006,job_id:'live-job',kind:'usage',data:{version:2,
            total_tokens:600,tokens:{input_tokens:500,output_tokens:100,cache_read_input_tokens:0,cache_creation_input_tokens:0},
            sdk_estimated_usd:.004,coverage:'reported',scope:'main_loop',turns:1,duration_ms:500,models:[]}}));
        assert.match(await page.$eval('#usage',node=>node.innerText),/\$0\.0374/);
        await page.evaluate(()=>showView('settings'));
        await page.$eval('#budget-limit',node=>node.value='0.05');
        await page.click('#settings-form button[type="submit"], #settings-form .primary');
        await page.waitForFunction(()=>state.settings===null || document.querySelector('#toast').textContent==='Settings saved for the next task.');
        assert.equal(await page.evaluate(async()=>(await api('/api/settings')).max_budget_usd),.05);
        await page.evaluate(()=>showView('chat'));

        await page.setViewport({width:390,height:900});
        await page.$eval('[data-result-job="live-job"]',node=>node.scrollIntoView({block:'center'}));
        const bounds=await page.$eval('[data-result-job="live-job"] a',node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};});
        assert.ok(bounds.left>=0 && bounds.right<=390 && bounds.width>100);
        const usageBounds=await page.$eval('[data-usage-job="live-job"]',node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right};});
        assert.ok(usageBounds.left>=0 && usageBounds.right<=390);
        const screenshots=path.join(root,'runtime/ui-artifacts');
        await mkdir(screenshots,{recursive:true});
        await page.screenshot({path:path.join(screenshots,'mobile.png'),fullPage:true});
        await page.setViewport({width:1440,height:1000});
        await page.evaluate(()=>{$('messages').scrollTop=0;});
        await page.screenshot({path:path.join(screenshots,'desktop.png'),fullPage:true});

        await page.evaluate(cid=>openConversation(cid),fixture.empty_cid);
        assert.equal(await page.$$eval('#messages .artifact',nodes=>nodes.length),0);
        assert.equal(await page.$$eval('#artifacts .artifact',nodes=>nodes.length),0);
        assert.equal(await page.evaluate(()=>state.resultGroups.size),0);
        assert.equal(await page.evaluate(()=>state.usageReports.size),0);
        assert.equal(await page.$$eval('.usage-message',nodes=>nodes.length),0);
        assert.deepEqual(errors,[]);
        console.log('Passed history replay, task association, download contents, live streaming, deduplication, filename escaping, mobile layout, and conversation reset.');
    }finally{
        if(browser)await browser.close();
        server.kill('SIGTERM');
        await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
        await rm(work,{recursive:true,force:true});
    }
});
