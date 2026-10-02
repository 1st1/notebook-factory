// @lat: [[architecture#Notebook search]]
// PGLITE_MODULE points to an isolated @electric-sql/pglite installation.
const {PGlite}=require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('backend/search.py','utf8');
const schema=source.match(/SEARCH_SCHEMA = """([\s\S]*?)"""/)[1];
const query=source.match(/SEARCH_QUERY = text\("""([\s\S]*?)"""\)/)[1].replaceAll(':query','$1');
(async()=>{
 const db=new PGlite();
 try {
 await db.exec('CREATE TABLE notebooks (id text PRIMARY KEY, owner_id integer, title text, published text, source text, updated_at integer, revision integer, render_url text)');
 await db.exec(schema);
 await db.exec(schema);
 await db.exec('CREATE INDEX notebooks_search_idx ON notebooks USING gin(search_vector)');
 const doc=(source,output='outputsecret')=>JSON.stringify({cells:[{source,outputs:[{text:output}]}]});
 for(const [id,title,body] of [['a','Galaxies','ordinary text'],['b','Space','galaxies'],['c','Other','nothing']]){
  await db.query('INSERT INTO notebooks VALUES ($1,1,$2,$3,$4,1,1,NULL,DEFAULT)',[id,title,doc(body),'privatesecret']);
 }
 const find=async q=>(await db.query(query,[q])).rows.map(r=>r.id);
 assert.deepEqual(await find('galaxy'),['a','b']);
 assert.deepEqual(await find('privatesecret'),[]);
 assert.deepEqual(await find('outputsecret'),[]);
 await db.query('UPDATE notebooks SET published=$1 WHERE id=$2',[doc(['orbital ','mechanics']), 'c']);
 assert.deepEqual(await find('orbital mechanics'),['c']);
 assert.deepEqual(await find('galaxy -ordinary'),['b']);
 await db.query('UPDATE notebooks SET title=$1 WHERE id=$2',['Renamedunique','a']);
 assert.deepEqual(await find('renamedunique'),['a']);
 await db.exec('SET enable_seqscan=off');
 const plan=JSON.stringify((await db.query('EXPLAIN '+query,['galaxy'])).rows);
 assert(plan.includes('notebooks_search_idx'),plan);
 console.log('PASS: PostgreSQL generated vector, GIN plan, stemming, ranking, exclusions, array sources and automatic updates');
 } finally {await db.close()}
})().catch(e=>{console.error(e);process.exit(1)});
