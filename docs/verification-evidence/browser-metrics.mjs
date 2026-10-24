import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
const root=process.cwd(), out=path.join(root,'docs/verification-evidence');
const source=await fs.readFile(path.join(out,'browser-check.mjs'),'utf8');
const pageHtml=source.split('const html=`')[1].split('`;\nconst server')[0];
const server=http.createServer(async(req,res)=>{try{if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end(pageHtml);return;}const p=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]));if(!p.startsWith(root+path.sep))throw Error();res.setHeader('Content-Type',p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':'application/octet-stream');res.end(await fs.readFile(p));}catch{res.writeHead(404);res.end();}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}/`;
const profile=path.join(out,'edge-metrics-profile');const edge=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'],{stdio:'ignore'});
let ws;try{let port;for(let i=0;i<100;i++){try{port=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{await new Promise(r=>setTimeout(r,100));}}if(!port)throw Error('No CDP endpoint');const targets=await(await fetch(`http://127.0.0.1:${port}/json/list`)).json();ws=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let seq=0;const pending=new Map();ws.addEventListener('message',ev=>{const m=JSON.parse(ev.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result)}});const cdp=(method,params={})=>new Promise((resolve,reject)=>{const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});const evaljs=async expression=>{const r=await cdp('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value};await cdp('Page.enable');await cdp('Page.navigate',{url});for(let i=0;i<100&&!await evaljs('window.ready===true');i++)await new Promise(r=>setTimeout(r,100));
const layouts=[];
for(const width of [760,1080]){await cdp('Emulation.setDeviceMetricsOverride',{width,height:880,deviceScaleFactor:1,mobile:false});for(const page of ['sources','settings']){await evaljs(`window.show('${page}')`);if(page==='sources')await evaljs(`document.querySelector('[data-pick="brave"]')?.click()`);await new Promise(r=>setTimeout(r,200));
const m=await evaljs(`(()=>{
 const lum=c=>{const v=c.map(x=>{x/=255;return x<=.03928?x/12.92:((x+.055)/1.055)**2.4});return .2126*v[0]+.7152*v[1]+.0722*v[2]};
 const parse=s=>{const m=s.match(/rgba?\\(([^)]+)\\)/);if(!m)return null;const p=m[1].split(',').map(Number);return {rgb:p.slice(0,3),a:p.length>3?p[3]:1}};
 const bg=el=>{for(let n=el;n;n=n.parentElement){const c=parse(getComputedStyle(n).backgroundColor);if(c&&c.a>0)return c.rgb}return [255,255,255]};
 const ratio=(a,b)=>{const [x,y]=[lum(a),lum(b)].sort((m,n)=>n-m);return +((x+.05)/(y+.05)).toFixed(2)};
 const pick=s=>[...document.querySelectorAll(s)].find(e=>e.offsetParent!==null);
 const styles={};
 for(const s of ['.sidebar-caption','.note','.status-text','h2','.eyebrow']){
   const el=pick(s);if(!el){styles[s]='absent';continue}const fg=parse(getComputedStyle(el).color);styles[s]={ratio:ratio(fg.rgb,bg(el)),font:getComputedStyle(el).fontSize,text:el.textContent.trim().slice(0,24)};
 }
 const textEls=[...document.querySelectorAll('body *')].filter(e=>e.offsetParent!==null&&[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));
 const fonts=textEls.map(e=>parseFloat(getComputedStyle(e).fontSize)).filter(Boolean);
 return {sidebar:document.querySelector('.sidebar').getBoundingClientRect().width,main:document.querySelector('main').getBoundingClientRect().width,innerWidth:window.innerWidth,scrollWidth:document.documentElement.scrollWidth,minFont:Math.min(...fonts),styles,overflow:[...document.querySelectorAll('button,input,select,textarea')].filter(e=>{const r=e.getBoundingClientRect();return r.width&&(r.right>innerWidth+1||r.left< -1)}).length,active:document.activeElement.tagName};
})()`);layouts.push({width,page,...m});}}
const tabs=[];await evaljs(`document.body.focus()`);for(let i=0;i<5;i++){await cdp('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await cdp('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});tabs.push(await evaljs(`(()=>{const e=document.activeElement,s=getComputedStyle(e);return {tag:e.tagName,text:(e.textContent||e.getAttribute('aria-label')||'').trim().slice(0,24),outline:s.outlineStyle+' '+s.outlineWidth}})()`));}
const result={url,mockOnly:true,layouts,tabs};await fs.writeFile(path.join(out,'browser-metrics.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await cdp('Browser.close');}finally{ws?.close();edge.kill();await new Promise(r=>server.close(r));console.log('Mock HTTP server and isolated Edge stopped');}
