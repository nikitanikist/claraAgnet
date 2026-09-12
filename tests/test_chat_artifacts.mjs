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
        assert.equal(await page.$eval('#execution-mode',node=>node.value),'autonomous');
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
        assert.match(await page.$eval(`[data-usage-job="${fixture.first_job}"]`,node=>node.innerText),/Waiting for you: 0.1 min · Working time: 0.2 min/);
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
        assert.equal(await page.$eval('#reasoning-effort',node=>node.value),'medium');
        await page.select('#reasoning-effort','high');
        await page.$eval('#budget-limit',node=>node.value='0.05');
        await page.click('#settings-form button[type="submit"], #settings-form .primary');
        await page.waitForFunction(()=>state.settings===null || document.querySelector('#toast').textContent==='Settings saved for the next task.');
        assert.equal(await page.evaluate(async()=>(await api('/api/settings')).max_budget_usd),.05);
        assert.equal(await page.evaluate(async()=>(await api('/api/settings')).reasoning_effort),'high');
        await page.select('#default-mode','ask');
        await page.click('#settings-form .primary');
        await page.waitForFunction(()=>state.settings.default_execution_mode==='ask' && $('execution-mode').value==='ask');
        await page.reload({waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>!state.initializing);
        assert.equal(await page.$eval('#execution-mode',node=>node.value),'ask');
        await page.evaluate(()=>showView('settings'));
        await page.select('#default-mode','autonomous');
        await page.click('#settings-form .primary');
        await page.waitForFunction(()=>state.settings.default_execution_mode==='autonomous' && $('execution-mode').value==='autonomous');
        // Reload cleared the synthetic live events; restore them for the mobile checks below.
        await page.evaluate(()=>{
            eventReceived({id:10001,job_id:'live-job',kind:'user',data:{text:'Create a report.'}});
            eventReceived({id:10003,job_id:'live-job',kind:'artifact',data:{id:'live-file',name:'report.txt',size:20}});
            eventReceived({id:10005,job_id:'live-job',kind:'status',data:{status:'completed'}});
        });
        await page.evaluate(()=>showView('settings'));
        await page.$eval('#max-turns',node=>node.value='500');
        await page.click('#settings-form .primary');
        await page.waitForFunction(async()=>(await api('/api/settings')).max_turns===500);
        await page.click('#unlimited-turns');
        assert.equal(await page.$eval('#max-turns',node=>node.disabled),true);
        await page.click('#settings-form .primary');
        await page.waitForFunction(async()=>(await api('/api/settings')).max_turns===null);
        await page.evaluate(()=>loadSettings());
        assert.equal(await page.$eval('#unlimited-turns',node=>node.checked),true);
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
        await page.evaluate(()=>showView('knowledge'));
        await page.waitForFunction(()=>document.querySelector('#knowledge-library').options.length===8);
        await page.type('#knowledge-title','Synthetic printing reference');
        await page.type('#knowledge-source','Test manual');
        await page.type('#knowledge-text','Use the verified Print dialog for the synthetic test application.');
        await page.click('#knowledge-form button.primary');
        await page.waitForFunction(()=>document.querySelector('#knowledge-records').innerText.includes('Synthetic printing reference'));
        assert.equal(await page.$$eval('#knowledge-records img',nodes=>nodes.length),0);
        await page.screenshot({path:path.join(screenshots,'knowledge.png'),fullPage:true});
        await page.evaluate(()=>showView('workflow'));
        await page.waitForSelector('#workflow-start:not(.hidden)');
        await page.type('#workflow-client','synthetic-client');await page.type('#workflow-year','2025');await page.type('#workflow-members','Test Person');
        await page.click('#workflow-start button.primary');
        await page.waitForFunction(()=>document.querySelector('#workflow-record').innerText.includes('t1-print'));
        assert.equal(await page.$$eval('.workflow-stages li',nodes=>nodes.length),5);
        await page.type('#workflow-review-note','Premature review should fail');
        await page.click('#workflow-review button.primary');
        await page.waitForFunction(()=>document.querySelector('#toast').innerText.includes('Complete the required stages'));
        assert.equal(await page.$eval('#workflow-unlimited-turns',node=>node.checked),true);
        await page.click('#workflow-unlimited-turns');
        await page.$eval('#workflow-turns',n=>n.value='500');
        await page.type('#workflow-budget-note','Synthetic test budget update');await page.click('#workflow-budget button');
        await page.waitForFunction(()=>document.querySelector('#toast').innerText==='Workflow budget updated.');
        await page.waitForFunction(async()=>((await api('/api/conversations/'+state.cid+'/workflow')).workflow.limits.max_turns)===500);
        await page.click('#workflow-unlimited-turns');
        assert.equal(await page.$eval('#workflow-turns',node=>node.disabled),true);
        await page.click('#workflow-budget button');
        await page.waitForFunction(async()=>((await api('/api/conversations/'+state.cid+'/workflow')).workflow.limits.max_turns)===null);
        await page.reload({waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>!state.initializing);
        await page.evaluate(cid=>openConversation(cid),fixture.empty_cid);
        await page.evaluate(()=>showView('workflow'));
        await page.waitForFunction(()=>document.querySelector('#workflow-unlimited-turns').checked);
        assert.equal(await page.$eval('#workflow-turns',node=>node.disabled),true);
        assert.match(await page.$eval('#workflow-record',node=>node.innerText),/Workflow turns: no limit/);
        assert.ok(await page.$eval('#workflow-unlimited-turns',node=>node.getBoundingClientRect().width<30));
        await page.$eval('#workflow-budget',node=>node.scrollIntoView({block:'start'}));
        await page.screenshot({path:path.join(screenshots,'workflow.png'),fullPage:true});
        await page.evaluate(()=>showView('settings'));
        await page.$eval('#unlimited-turns',node=>node.scrollIntoView({block:'center'}));
        await page.screenshot({path:path.join(screenshots,'turn-settings.png'),fullPage:true});
        await page.evaluate(cid=>openConversation(cid),fixture.recovery_cid);
        const original=await page.evaluate(async cid=>(await api('/api/conversations/'+cid)).jobs,fixture.recovery_cid);
        await page.evaluate(()=>showView('workflow'));
        await page.waitForSelector('#review-usage');
        await page.$eval('#usage-recovery',node=>node.scrollIntoView({block:'center'}));
        assert.match(await page.$eval('#usage-recovery',node=>node.innerText),/Missing usage stays unknown/);
        await page.click('#usage-recovery summary');
        assert.match(await page.$eval('#usage-recovery',node=>node.innerText),/26.1 seconds/);
        await page.screenshot({path:path.join(screenshots,'resume-recovery.png'),fullPage:true});
        await page.click('#review-usage');
        await page.waitForFunction(()=>$('prompt').value.startsWith('Continue the existing task'));
        assert.equal(await page.$eval('#execution-mode',node=>node.value),'autonomous');
        assert.equal(await page.evaluate(()=>state.cid),fixture.recovery_cid);
        const reviewed=await page.evaluate(async()=>await api('/api/conversations/'+state.cid+'/workflow'));
        assert.equal(reviewed.workflow.budget.partial,true);
        assert.equal(reviewed.workflow.budget.requires_usage_review,false);
        assert.equal(reviewed.workflow.stages.intake.status,'verified');
        assert.deepEqual(await page.evaluate(async cid=>(await api('/api/conversations/'+cid)).jobs,fixture.recovery_cid),original);
        await page.reload({waitUntil:'domcontentloaded'});
        await page.waitForFunction(()=>!state.initializing);
        await page.evaluate(cid=>openConversation(cid),fixture.recovery_cid);
        await page.evaluate(()=>showView('workflow'));
        await page.waitForSelector('#usage-recovery');
        assert.equal(await page.$('#review-usage'),null);
        assert.match(await page.$eval('#usage-recovery',node=>node.innerText),/Continuation with incomplete usage has been recorded/);

        // Real pending-input endpoint: choices never submit themselves, legacy
        // paragraphs remain intact, and free-form multiline answers survive.
        await page.evaluate(cid=>openConversation(cid),fixture.questions_cid);
        await page.waitForSelector('.question-choices');
        assert.equal(await page.$eval('#pending h3',n=>n.textContent),'Where should I upload the test PDFs?');
        assert.equal(await page.$eval('.question-context',n=>getComputedStyle(n).whiteSpace),'pre-wrap');
        assert.equal(await page.$eval('.question-details',n=>n.open),false);
        const questionState=await page.evaluate(async()=>await api('/api/conversations/'+state.cid));
        assert.equal(questionState.pending.length,1);
        await page.screenshot({path:path.join(screenshots,'question-card.png'),fullPage:true});
        await page.type('.question-answer','Preserve this draft');
        await page.evaluate(()=>renderPending());
        assert.equal(await page.$eval('.question-answer',n=>n.value),'Preserve this draft');
        await page.click('.question-details summary');
        assert.equal(await page.$$eval('#pending img',nodes=>nodes.length),0);
        assert.match(await page.$eval('.question-details',n=>n.innerText),/Literal text: <img/);
        await page.screenshot({path:path.join(screenshots,'question-desktop.png'),fullPage:true});
        await page.setViewport({width:390,height:900});
        const questionBounds=await page.$eval('#pending',node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,scroll:node.scrollWidth,client:node.clientWidth};});
        assert.ok(questionBounds.left>=0 && questionBounds.right<=390 && questionBounds.scroll<=questionBounds.client+1);
        await page.screenshot({path:path.join(screenshots,'question-mobile.png'),fullPage:true});
        await page.click('.question-choice');
        await page.waitForFunction(()=>$('pending').innerText.includes('Clara needs your input'));
        assert.equal(await page.$eval('#pending h3',n=>n.textContent),'Clara needs your input');
        assert.match(await page.$eval('.question-context',n=>n.textContent),/\n\nWhich test folder/);
        await page.type('.question-answer','Use the test folder.');
        await page.focus('.question-answer');await page.keyboard.press('Enter');
        await page.type('.question-answer','Keep the existing files.');
        assert.equal(await page.$eval('.question-answer',n=>n.value),'Use the test folder.\nKeep the existing files.');
        await page.click('#pending .primary');
        await page.waitForFunction(()=>$('pending').classList.contains('hidden'));
        const answers=await page.evaluate(async()=>{
            const detail=await api('/api/conversations/'+state.cid);
            const diagnostics=await api('/api/jobs/'+detail.jobs[0].id+'/diagnostics.json');
            return diagnostics.events.filter(e=>e.kind==='answer').map(e=>e.data.answer);
        });
        assert.deepEqual(answers,['Ask me for the existing test-folder link.','Use the test folder.\nKeep the existing files.']);
        assert.deepEqual(errors,[]);
        console.log('Passed history replay, task association, download contents, live streaming, deduplication, filename escaping, mobile layout, and conversation reset.');
    }finally{
        if(browser)await browser.close();
        server.kill('SIGTERM');
        await new Promise(resolve=>server.exitCode!==null?resolve():server.once('exit',resolve));
        await rm(work,{recursive:true,force:true});
    }
});
