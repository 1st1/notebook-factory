// @lat: [[editing#Immediate navigation]]
// Run after building frontend; PLAYWRIGHT_MODULE may point to a local Playwright installation.
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
let holdClose=false,holdStart=false,heldStart,closeSource,starts=[],expiredIds=new Set(),saves=[],boots={},histories=new Map(),messagesSeen=[];
let releaseBackground;
let holdHistory=true;const historyWaiters=[];
const notebooks=['one','two','three'].map(id=>({id,title:'Notebook '+id,revision:1,updated_at:1}));
const nb={nbformat:4,nbformat_minor:5,metadata:{},cells:[{id:'cell',cell_type:'markdown',source:'Published content',metadata:{}}]};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');let raw='';for await(const c of req)raw+=c;const body=raw?JSON.parse(raw):{};
 res.setHeader('Content-Type','application/json');const id=u.pathname.split('/')[3];
 if(u.pathname==='/api/notebooks')return res.end(JSON.stringify(notebooks));
 if(u.pathname==='/api/auth/me')return res.end(JSON.stringify({can_edit:true,user:{login:'1st1'},configured:true}));
 if(u.pathname.endsWith('/chat-history')){const v=histories.get(id)||{messages:[],revision:0};if(req.method==='PUT'){histories.set(id,{messages:body.messages,revision:body.revision+1});return res.end(JSON.stringify({revision:body.revision+1}));}if(holdHistory){historyWaiters.push(()=>res.end(JSON.stringify(v)));return;}return res.end(JSON.stringify(v));}
 if(u.pathname.endsWith('/editor')){starts.push(id);const send=()=>res.end('data: '+JSON.stringify({type:'ready',editor:{name:'test',token:id+'-'+starts.length,url:'http://127.0.0.1:5187/editor-frame?id='+id}})+'\n\n');if(holdStart){heldStart=send;return;}return send();}
 if(u.pathname.endsWith('/editor-status')){res.statusCode=expiredIds.has(id)?410:200;return res.end('{}');}
 if(u.pathname.endsWith('/save')){saves.push({id,...body});return res.end('{}');}
 if(u.pathname.endsWith('/close')){closeSource=body.source;if(holdClose)return;return res.end('{}');}
 if(u.pathname.endsWith('/download'))return res.end(JSON.stringify(nb));
 if(u.pathname.endsWith('/render')){res.setHeader('Content-Type','text/html');return res.end('Published '+id);}
 if(u.pathname.endsWith('/chat')){
 messagesSeen.push(body);const all=body.messages.flatMap(m=>m.parts);const toolOutput=all.findLast(p=>p.type.startsWith('tool-')&&p.state==='output-available');const text=all.filter(p=>p.type==='text').map(p=>p.text).join(' ');const name=text.includes('background')?'insert_cell':text.includes('change')?'request_editing':'read_notebook';
 res.setHeader('Content-Type','text/event-stream');res.setHeader('x-vercel-ai-ui-message-stream','v1');
 const events=[{type:'start',messageId:'assistant-'+messagesSeen.length},{type:'start-step'}];
 if(!toolOutput)events.push({type:'tool-input-available',toolCallId:'tool-'+messagesSeen.length,toolName:name,input:name==='request_editing'?{reason:'I can update the chart.'}:{}});
 else events.push({type:'text-start',id:'text'},{type:'text-delta',id:'text',delta:toolOutput.output.user_declined?'Staying in viewing mode.':body.token?'Editor is ready.':'This notebook contains published content.'},{type:'text-end',id:'text'});
 events.push({type:'finish-step'},{type:'finish'});
 const finish=()=>res.end(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')+'data: [DONE]\n\n');
 if(text.includes('background')&&!toolOutput){res.flushHeaders();releaseBackground=finish;return;}return finish();
 }
 if(u.pathname==='/editor-frame'){boots[u.searchParams.get('id')]=(boots[u.searchParams.get('id')]||0)+1;res.setHeader('Content-Type','text/html');return res.end(`<script>addEventListener('message',e=>{if(e.data.type==='vercel-notebook-tool'){window.lastTool=e.data.tool;parent.postMessage({type:'vercel-notebook-tool-result',id:e.data.id,result:{ok:true}},'*')}if(e.data.type==='vercel-notebook-export')setTimeout(()=>parent.postMessage({type:'vercel-notebook-saved',id:e.data.id,source:JSON.stringify({live:'unsaved document'})},'*'),300);if(e.data.type==='vercel-notebook-capabilities')parent.postMessage({type:'vercel-notebook-tool-result',id:e.data.id,result:{protocol:2,ready:true,connected:window.connected!==false}},'*')})</script>Editor`);}
 const file=path.join(process.cwd(),'frontend/dist',u.pathname==='/'?'index.html':u.pathname);res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
const tick=()=>new Promise(r=>setTimeout(r,100));
(async()=>{await new Promise(r=>server.listen(5187,'127.0.0.1',r));const browser=await chromium.launch();try{
 const page=await browser.newPage();await page.clock.install();await page.goto('http://127.0.0.1:5187/?notebook=one');
 await page.getByRole('heading',{name:'Notebook one',exact:true}).waitFor();
 for(let i=0;i<30&&!historyWaiters.length;i++)await tick();assert(historyWaiters.length,'history request is deliberately stalled');
 for(const button of await page.getByRole('navigation',{name:'Notebooks'}).getByRole('button').all())assert.equal(await button.isEnabled(),true,'history loading must not disable sidebar');
 await page.getByRole('button',{name:'Notebook two',exact:true}).click();await page.getByRole('heading',{name:'Notebook two',exact:true}).waitFor();await tick();
 assert.equal(await page.getByRole('button',{name:'Notebook one',exact:true}).isEnabled(),true);
 await page.getByRole('button',{name:'Notebook one',exact:true}).click();await page.getByRole('heading',{name:'Notebook one',exact:true}).waitFor();
 holdHistory=false;for(const release of historyWaiters)release();await tick();await page.getByRole('textbox',{name:'Message'}).fill('explain');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByText('This notebook contains published content.').waitFor();assert.equal(starts.length,0);assert(messagesSeen.at(-1).messages.flatMap(x=>x.parts).some(p=>p.output?.cells?.[0]?.source==='Published content'));

 await page.getByRole('button',{name:'Notebook three',exact:true}).click();await page.getByRole('heading',{name:'Notebook three',exact:true}).waitFor();await tick();assert.equal(await page.getByRole('button',{name:'Chat',exact:true}).getAttribute('aria-expanded'),'true','new notebooks open chat even without history');
 await page.getByRole('button',{name:'Notebook one',exact:true}).click();await page.getByText('This notebook contains published content.').waitFor();assert.equal(await page.getByRole('button',{name:'Chat',exact:true}).getAttribute('aria-expanded'),'true','saved history opens chat automatically');
 await page.getByRole('button',{name:'Close chat',exact:true}).click();await tick();assert.equal(await page.getByRole('button',{name:'Chat',exact:true}).getAttribute('aria-expanded'),'false','manual dismissal stays closed');
 await page.getByRole('button',{name:'Chat',exact:true}).click();
 await page.getByRole('button',{name:'New chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('change chart');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByRole('button',{name:'No',exact:true}).click();await page.getByText('Staying in viewing mode.').waitFor();assert.equal(starts.length,0);
 await page.getByRole('button',{name:'New chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('change chart');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByRole('button',{name:'Yes',exact:true}).waitFor();await page.getByRole('button',{name:'Edit notebook',exact:true}).click();await page.getByText('Editor is ready.',{exact:true}).waitFor();assert.equal(await page.getByRole('button',{name:'Yes',exact:true}).count(),0,'manual editor startup resolves pending consent');assert.equal(starts.length,1);assert(messagesSeen.at(-1).token);assert.equal(await page.getByRole('button',{name:'Exit',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:/Reconnect/}).count(),0);
 await page.getByRole('button',{name:'Close chat',exact:true}).click();await tick();
 const aFrame=page.frameLocator('iframe[title="Jupyter editor: Notebook one"]');
 await aFrame.locator('body').evaluate(()=>{window.retainedValue=42});
 const aButton=page.getByRole('button',{name:'Notebook one',exact:false});
 const bButton=page.getByRole('button',{name:'Notebook two',exact:false});
 assert.equal(await aButton.getByLabel('Editor connected').count(),1);
 await bButton.click();await page.getByRole('heading',{name:'Notebook two',exact:true}).waitFor({timeout:1000});await page.getByTitle('Rendered notebook').waitFor();
 assert.equal(starts.length,1,'navigation must not start another editor');
 await page.waitForTimeout(400);assert(saves.some(save=>save.id==='one'&&JSON.parse(save.source).live==='unsaved document'));
 await aButton.click();await page.getByTitle('Jupyter editor: Notebook one').waitFor();assert.equal(await aFrame.locator('body').evaluate(()=>window.retainedValue),42);assert.equal(boots.one,1,'returning must not reload iframe');
 await bButton.click();holdStart=true;await page.getByRole('button',{name:'Edit notebook',exact:true}).click();await bButton.getByLabel('Editor starting').waitFor();
 await aButton.click();assert.equal(await bButton.getByLabel('Editor starting').count(),1,'startup indicator survives navigation');
 for(let i=0;i<30&&!heldStart;i++)await tick();assert(heldStart);holdStart=false;heldStart();
 await bButton.getByLabel('Editor connected').waitFor();assert.equal(await bButton.getByLabel('Editor starting').count(),0);await bButton.click();await page.getByTitle('Jupyter editor: Notebook two').waitFor();assert.equal(starts.length,2);
 assert.equal(await aButton.getByLabel('Editor connected').count(),1);assert.equal(await bButton.getByLabel('Editor connected').count(),1);
 await aButton.click();await page.getByRole('button',{name:'New chat',exact:true}).waitFor();
 await page.getByRole('button',{name:'New chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('background edit');await page.getByRole('button',{name:'Send',exact:true}).click();
 for(let i=0;i<30&&!releaseBackground;i++)await tick();assert(releaseBackground);
 await aButton.getByLabel('Agent working').waitFor();assert(await bButton.isEnabled());
 await bButton.click();await page.getByRole('heading',{name:'Notebook two',exact:true}).waitFor();releaseBackground();
 for(let i=0;i<30&&await aButton.getByLabel('Agent working').count();i++)await tick();
 assert.equal(await aFrame.locator('body').evaluate(()=>window.lastTool),'insert_cell','hidden agent targets its original notebook');
 assert.equal(await page.frameLocator('iframe[title="Jupyter editor: Notebook two"]').locator('body').evaluate(()=>window.lastTool),undefined,'selected notebook must not receive background tools');
 assert(messagesSeen.at(-1).token.startsWith('one-'),'continuation retains original notebook token');
 const savesBeforeBlur=saves.length;await page.evaluate(()=>window.dispatchEvent(new Event('blur')));await page.waitForTimeout(700);assert(saves.length>savesBeforeBlur,'switching browser focus triggers database save');
 await aButton.click();await page.getByText('Editor is ready.',{exact:true}).waitFor();assert.equal(await aButton.getByLabel('Agent working').count(),0);assert.equal(await aButton.getByLabel('Editor connected').count(),1);
 await page.locator('a.brand').click();await page.getByRole('heading',{name:'Choose a notebook.'}).waitFor();await aButton.click();assert.equal(await aFrame.locator('body').evaluate(()=>window.retainedValue),42);assert.equal(boots.one,1);assert.equal(boots.two,1);
 await page.frameLocator('iframe[title="Jupyter editor: Notebook two"]').locator('body').evaluate(()=>{window.connected=false});
 await page.clock.fastForward(15001);for(let i=0;i<30&&await bButton.getByLabel('Editor connected').count();i++)await tick();assert.equal(await bButton.getByLabel('Editor connected').count(),0,'kernel disconnection clears background dot');assert.equal(starts.length,2);
 expiredIds.add('two');await page.clock.fastForward(15001);await tick();await bButton.click();await page.getByTitle('Rendered notebook').waitFor();await page.clock.fastForward(15001);await tick();assert.equal(starts.length,2,'disconnected background editor stays read-only until explicitly opened');
 await aButton.click();expiredIds.add('one');await page.clock.fastForward(15001);for(let i=0;i<40&&starts.length<3;i++)await tick();assert.equal(starts.at(-1),'one');assert(starts.length>=3,'selected expired editor auto recovers');
 if(process.env.SCREENSHOT_PATH)await page.screenshot({path:process.env.SCREENSHOT_PATH});
 console.log('PASS: automatic saved-chat opening and manual dismissal, nonblocking history loads, view chat and consent, read-only navigation, retained iframe state across notebooks and welcome, multiple live dots, disconnected dot removal, active recovery');

}finally{await browser.close();server.closeAllConnections();server.close()}})().catch(e=>{console.error(e);process.exit(1)});
