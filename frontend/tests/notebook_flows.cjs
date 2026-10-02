// @lat: [[editing#Immediate navigation]]
// Run after building frontend; PLAYWRIGHT_MODULE may point to a local Playwright installation.
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
let holdClose=false,holdStart=false,heldStart,closeSource,starts=[],expiredIds=new Set(),saves=[],boots={},histories=new Map(),messagesSeen=[];
let authProfile={login:'1st1',user_id:1};
let releaseBackground;
let holdHistory=true;const historyWaiters=[];
const notebooks=['one','two','three'].map(id=>({id,title:'Notebook '+id,owner_id:1,revision:1,updated_at:1}));
notebooks.push({id:'other',title:'Other notebook',owner_id:2,revision:1,updated_at:1});
histories.set('other',{messages:[{id:'other-chat',role:'assistant',parts:[{type:'text',text:'Public conversation from another user.'}]}],revision:1});
const workspaceUsers=[{id:3,login:'zara'},{id:1,login:'1st1'},{id:2,login:'amy'}];
const nb={nbformat:4,nbformat_minor:5,metadata:{},cells:[{id:'cell',cell_type:'markdown',source:'Published content',metadata:{}}]};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');let raw='';for await(const c of req)raw+=c;const body=raw?JSON.parse(raw):{};
 res.setHeader('Content-Type','application/json');const id=u.pathname.split('/')[3];
 if(u.pathname==='/api/search')return res.end(JSON.stringify(u.searchParams.get('q')==='quantum'?[notebooks.find(n=>n.id==='two')]:[]));
 if(u.pathname==='/api/workspace')return res.end(JSON.stringify({users:workspaceUsers,notebooks}));
 if(u.pathname==='/api/users')return res.end(JSON.stringify(workspaceUsers));
 if(u.pathname==='/api/notebooks')return res.end(JSON.stringify(notebooks));
 if(u.pathname==='/api/auth/me')return res.end(JSON.stringify({can_edit:true,user:authProfile,configured:true}));
 if(u.pathname.endsWith('/chat-history')){const v=histories.get(id)||{messages:[],revision:0};if(req.method==='PUT'){histories.set(id,{messages:body.messages,revision:body.revision+1});return res.end(JSON.stringify({revision:body.revision+1}));}if(holdHistory){historyWaiters.push(()=>res.end(JSON.stringify(v)));return;}return res.end(JSON.stringify(v));}
 if(u.pathname.endsWith('/editor')){starts.push(id);const send=()=>res.end('data: '+JSON.stringify({type:'ready',editor:{name:'test',token:id+'-'+starts.length,url:'http://127.0.0.1:5187/editor-frame?id='+id}})+'\n\n');if(holdStart){res.write('data: '+JSON.stringify({type:'progress',message:'Preparing test environment…'})+'\n\n');res.write('data: '+JSON.stringify({type:'log',message:'Retained setup log'})+'\n\n');heldStart=send;return;}return send();}
 if(u.pathname.endsWith('/editor-status')){res.statusCode=expiredIds.has(id)?410:200;return res.end('{}');}
 if(u.pathname.endsWith('/save')){saves.push({id,...body});return res.end('{}');}
 if(u.pathname.endsWith('/close')){closeSource=body.source;if(holdClose)return;return res.end('{}');}
 if(u.pathname.endsWith('/fork')){const original=notebooks.find(n=>n.id===id);const fork={...original,id:'forked',owner_id:1};notebooks.push(fork);return res.end(JSON.stringify(fork));}
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
 const page=await browser.newPage();await page.clock.install();
 let authRoute,chatRoute;
 await page.route('**/api/auth/me',route=>{authRoute=route});
 await page.route('**/assets/Chat-*.js',route=>{chatRoute=route});
 await page.goto('http://127.0.0.1:5187/?notebook=one',{waitUntil:'domcontentloaded'});
 await page.getByRole('complementary',{name:'Notebook chat'}).waitFor();
 await page.getByText('Loading conversation…',{exact:true}).waitFor();
 for(let i=0;i<30&&!authRoute;i++)await tick();assert(authRoute);await authRoute.continue();await page.unroute('**/api/auth/me');
 for(let i=0;i<30&&!chatRoute;i++)await tick();assert(chatRoute);
 assert(await page.getByRole('complementary',{name:'Notebook chat'}).isVisible(),'panel remains visible before chat bundle loads');
 assert(await page.getByRole('textbox',{name:'Message'}).isDisabled());
 await chatRoute.continue();await page.unroute('**/assets/Chat-*.js');
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
 await page.getByText('Preparing test environment…',{exact:true}).waitFor();
 await page.clock.fastForward(5000);
 await aButton.click();assert.equal(await bButton.getByLabel('Editor starting').count(),1,'startup indicator survives navigation');
 await page.clock.fastForward(5000);await bButton.click();
 await page.getByText('Preparing test environment…',{exact:true}).waitFor();assert((await page.locator('[aria-label="Startup events"]').textContent()).includes('Retained setup log'));
 const elapsed=await page.locator('details[aria-label="Environment setup"]').locator('small').textContent();assert(parseInt(elapsed)>=10,'elapsed startup time must survive navigation');
 await aButton.click();
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
 const groupNames=await page.locator('.owner-toggle strong').allTextContents();assert.deepEqual(groupNames,['1st1','amy','zara']);
 assert.equal(await page.locator('.owner-toggle').filter({hasText:'amy'}).getAttribute('aria-expanded'),'false');
 await page.locator('.owner-toggle').filter({hasText:'amy'}).click();await page.getByRole('button',{name:'Other notebook',exact:true}).click();
 await page.getByText('Public conversation from another user.',{exact:true}).waitFor();
 assert.equal(await page.getByRole('textbox',{name:'Message'}).count(),0);
 assert.equal(await page.getByRole('button',{name:'Edit notebook',exact:true}).count(),0);
 assert.equal(await page.getByRole('button',{name:'Delete notebook',exact:true}).count(),0);
 assert.equal(await page.getByRole('button',{name:'New chat',exact:true}).count(),0);
 await page.getByRole('button',{name:'Fork',exact:true}).click();await page.getByRole('button',{name:'Edit notebook',exact:true}).waitFor();
 await page.getByRole('textbox',{name:'Message'}).waitFor();
 assert.equal(await page.getByText('Public conversation from another user.',{exact:true}).isVisible(),false,'fork does not copy chat');
 assert.equal(notebooks.find(n=>n.id==='forked').owner_id,1);
 await page.locator('.search').click({position:{x:3,y:3}});
 assert(await page.getByRole('textbox',{name:'Search notebooks'}).evaluate(el=>el===document.activeElement),'search padding focuses input');
 const owner=page.locator('.notebook-owner').filter({has:page.locator('.owner-toggle strong',{hasText:'1st1'})});
 const avatarBox=await owner.locator('.owner-toggle .owner-initial, .owner-toggle img').boundingBox();
 const iconBox=await owner.locator('.notebook-link > svg').first().boundingBox();
 assert(Math.abs((avatarBox.x+avatarBox.width/2)-(iconBox.x+iconBox.width/2))<1,'avatar and notebook icon centers align');
 await page.getByRole('button',{name:'New notebook',exact:true}).click();
 await page.getByRole('dialog').waitFor();
 await page.getByLabel('Notebook title').press('Escape');
 assert.equal(await page.getByRole('dialog').count(),0,'Escape dismisses creation');
 await page.getByRole('textbox',{name:'Search notebooks'}).fill('quantum');
 await page.clock.fastForward(300);
 await page.getByRole('button',{name:'Notebook two',exact:true}).waitFor();
 assert.equal(await page.getByRole('button',{name:'Notebook one',exact:true}).count(),0,'uses server results even when title does not match query');
 await page.getByRole('textbox',{name:'Search notebooks'}).fill('');
 await page.getByRole('button',{name:'Notebook one',exact:true}).waitFor();
 const beforeRefreshHeading=await page.locator('h1').textContent();
 const beforeRefreshBoots=JSON.stringify(boots);
 notebooks.push({id:'periodic-new',title:'Periodic new notebook',owner_id:1,revision:1,updated_at:2});
 await page.clock.fastForward(30_000);
 await page.getByRole('button',{name:'Periodic new notebook',exact:true}).waitFor();
 assert.equal(await page.locator('h1').textContent(),beforeRefreshHeading,'refresh preserves selected notebook');
 assert.equal(JSON.stringify(boots),beforeRefreshBoots,'refresh does not remount editors');
 authProfile={login:'amy',user_id:2};
 const amyPage=await browser.newPage();await amyPage.goto('http://127.0.0.1:5187/?notebook=other');
 await amyPage.getByRole('textbox',{name:'Message'}).waitFor();
 assert.deepEqual(await amyPage.locator('.owner-toggle strong').allTextContents(),['amy','1st1','zara'],'logged-in user is first, not a fixed account');
 assert.equal(await amyPage.locator('.owner-toggle').filter({hasText:'amy'}).getAttribute('aria-expanded'),'true');
 assert.equal(await amyPage.locator('.owner-toggle').filter({hasText:'1st1'}).getAttribute('aria-expanded'),'false');
 assert(await amyPage.getByRole('button',{name:'Edit notebook',exact:true}).isVisible());
 await amyPage.close();
 await page.setViewportSize({width:390,height:844});
 const closeChat=page.getByRole('button',{name:'Close chat',exact:true});
 if(await closeChat.isVisible())await closeChat.click();
 const mobileMenu=page.locator('.notebook-toolbar').getByRole('button',{name:'Open navigation'});
 await mobileMenu.waitFor();
 assert((await page.locator('.notebook-toolbar').boundingBox()).y<20,'mobile header avoids standalone navigation padding');
 assert((await mobileMenu.textContent()).includes('Menu'));
 await mobileMenu.click();
 assert(await page.locator('.sidebar').evaluate(el=>el.classList.contains('open')));
 await page.getByRole('button',{name:'Close navigation',exact:true}).click();
 await page.clock.fastForward(300);
 await page.locator('.sidebar').evaluate(el=>el.style.transition='none');
 if(process.env.SCREENSHOT_PATH)await page.screenshot({path:process.env.SCREENSHOT_PATH});
 console.log('PASS: automatic saved-chat opening and manual dismissal, nonblocking history loads, view chat and consent, read-only navigation, retained iframe state across notebooks and welcome, multiple live dots, disconnected dot removal, active recovery');

}finally{await browser.close();server.closeAllConnections();server.close()}})().catch(e=>{console.error(e);process.exit(1)});
