// @lat: [[editing#Immediate navigation]]
// Run after building frontend; PLAYWRIGHT_MODULE may point to a local Playwright installation.
const http=require('http'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
let holdClose=false,holdStart=false,heldStart,closeSource,starts=[],expired=false,histories=new Map(),messagesSeen=[];
const notebooks=['one','two','three'].map(id=>({id,title:'Notebook '+id,revision:1,updated_at:1}));
const nb={nbformat:4,nbformat_minor:5,metadata:{},cells:[{id:'cell',cell_type:'markdown',source:'Published content',metadata:{}}]};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');let raw='';for await(const c of req)raw+=c;const body=raw?JSON.parse(raw):{};
 res.setHeader('Content-Type','application/json');const id=u.pathname.split('/')[3];
 if(u.pathname==='/api/notebooks')return res.end(JSON.stringify(notebooks));
 if(u.pathname==='/api/auth/me')return res.end(JSON.stringify({can_edit:true,user:{login:'1st1'},configured:true}));
 if(u.pathname.endsWith('/chat-history')){const v=histories.get(id)||{messages:[],revision:0};if(req.method==='PUT'){histories.set(id,{messages:body.messages,revision:body.revision+1});return res.end(JSON.stringify({revision:body.revision+1}));}return res.end(JSON.stringify(v));}
 if(u.pathname.endsWith('/editor')){starts.push(id);const send=()=>res.end('data: '+JSON.stringify({type:'ready',editor:{name:'test',token:id+'-'+starts.length,url:'http://127.0.0.1:5187/editor-frame?id='+id}})+'\n\n');if(holdStart){heldStart=send;return;}return send();}
 if(u.pathname.endsWith('/editor-status')){res.statusCode=expired?410:200;return res.end('{}');}
 if(u.pathname.endsWith('/save'))return res.end('{}');
 if(u.pathname.endsWith('/close')){closeSource=body.source;if(holdClose)return;return res.end('{}');}
 if(u.pathname.endsWith('/download'))return res.end(JSON.stringify(nb));
 if(u.pathname.endsWith('/render')){res.setHeader('Content-Type','text/html');return res.end('Published '+id);}
 if(u.pathname.endsWith('/chat')){
 messagesSeen.push(body);const all=body.messages.flatMap(m=>m.parts);const toolOutput=all.findLast(p=>p.type.startsWith('tool-')&&p.state==='output-available');const text=all.filter(p=>p.type==='text').map(p=>p.text).join(' ');const name=text.includes('change')?'request_editing':'read_notebook';
 res.setHeader('Content-Type','text/event-stream');res.setHeader('x-vercel-ai-ui-message-stream','v1');
 const events=[{type:'start',messageId:'assistant-'+messagesSeen.length},{type:'start-step'}];
 if(!toolOutput)events.push({type:'tool-input-available',toolCallId:'tool-'+messagesSeen.length,toolName:name,input:name==='request_editing'?{reason:'I can update the chart.'}:{}});
 else events.push({type:'text-start',id:'text'},{type:'text-delta',id:'text',delta:toolOutput.output.user_declined?'Staying in viewing mode.':body.token?'Editor is ready.':'This notebook contains published content.'},{type:'text-end',id:'text'});
 events.push({type:'finish-step'},{type:'finish'});return res.end(events.map(e=>'data: '+JSON.stringify(e)+'\n\n').join('')+'data: [DONE]\n\n');
 }
 if(u.pathname==='/editor-frame'){res.setHeader('Content-Type','text/html');return res.end(`<script>addEventListener('message',e=>{if(e.data.type==='vercel-notebook-export')setTimeout(()=>parent.postMessage({type:'vercel-notebook-saved',id:e.data.id,source:JSON.stringify({live:'unsaved document'})},'*'),300);if(e.data.type==='vercel-notebook-capabilities')parent.postMessage({type:'vercel-notebook-tool-result',id:e.data.id,result:{protocol:2,ready:true}},'*')})</script>Editor`);}
 const file=path.join(process.cwd(),'frontend/dist',u.pathname==='/'?'index.html':u.pathname);res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
});
const tick=()=>new Promise(r=>setTimeout(r,100));
(async()=>{await new Promise(r=>server.listen(5187,'127.0.0.1',r));const browser=await chromium.launch();try{
 const page=await browser.newPage();await page.clock.install();await page.goto('http://127.0.0.1:5187/?notebook=one');await tick();await page.getByRole('button',{name:'Chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('explain');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByText('This notebook contains published content.').waitFor();assert.equal(starts.length,0);assert(messagesSeen.at(-1).messages.flatMap(x=>x.parts).some(p=>p.output?.cells?.[0]?.source==='Published content'));
 await page.getByRole('button',{name:'New chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('change chart');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByRole('button',{name:'No',exact:true}).click();await page.getByText('Staying in viewing mode.').waitFor();assert.equal(starts.length,0);
 await page.getByRole('button',{name:'New chat',exact:true}).click();await page.getByRole('textbox',{name:'Message'}).fill('change chart');await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByRole('button',{name:'Yes',exact:true}).click();await page.getByText('Editor is ready.',{exact:true}).waitFor();assert.equal(starts.length,1);assert(messagesSeen.at(-1).token);assert.equal(await page.getByRole('button',{name:'Exit',exact:true}).count(),0);assert.equal(await page.getByRole('button',{name:/Reconnect/}).count(),0);
 await page.getByRole('button',{name:'Close chat',exact:true}).click();await tick();holdClose=true;holdStart=true;await page.getByRole('button',{name:'Notebook two',exact:true}).click();await page.getByRole('heading',{name:'Notebook two',exact:true}).waitFor({timeout:1000});await page.getByTitle('Rendered notebook').waitFor();for(let i=0;i<30&&!heldStart;i++)await tick();assert(heldStart,'new editor starts while outgoing close is blocked');assert.equal(JSON.parse(closeSource).live,'unsaved document');heldStart();holdStart=false;await page.getByTitle('Jupyter notebook editor').waitFor();assert.equal(starts.at(-1),'two');
 holdClose=false;expired=true;await page.clock.fastForward(15001);for(let i=0;i<30&&starts.length<3;i++)await tick();assert.equal(starts.at(-1),'two');assert(starts.length>=3,'expired editor auto recovers');if(process.env.SCREENSHOT_PATH)await page.screenshot({path:process.env.SCREENSHOT_PATH});console.log('PASS: viewing chat, read context, No/Yes consent and continuation, immediate navigation with published preview, background close, automatic recovery');
}finally{await browser.close();server.closeAllConnections();server.close()}})().catch(e=>{console.error(e);process.exit(1)});
