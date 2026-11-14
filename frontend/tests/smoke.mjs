// Run against an owned Brave CDP session on 9224 and controlled server on 8093.
import { writeFileSync } from "node:fs";
const tabs = await (await fetch("http://127.0.0.1:9224/json/list")).json();
const ws = new WebSocket(tabs[0].webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let serial = 0;
const pending = new Map(),
  errors = [];
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id) {
    pending.get(m.id)?.(m);
    pending.delete(m.id);
  } else if (m.method === "Runtime.exceptionThrown") errors.push(m.params);
};
const send = (method, params = {}) =>
  new Promise((resolve) => {
    const id = ++serial;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
const evaluate = async (expression) => {
  const m = await send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (m.result?.exceptionDetails || m.error) throw Error(JSON.stringify(m));
  return m.result.result.value;
};
const wait = (expression) =>
  evaluate(
    `new Promise((resolve,reject)=>{let n=0;const t=setInterval(()=>{if(${expression}){clearInterval(t);resolve(true)}else if(++n>100){clearInterval(t);reject(Error('Timed out: '+${JSON.stringify(expression)}))}},50)})`,
  );
await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8093/" });
await wait(`document.querySelector('#new-chat')&&!document.querySelector('#new-chat').disabled`);
await evaluate(`document.querySelector('#new-chat').click()`);
await wait(
  `document.querySelector('#upload')&&!document.querySelector('#upload').disabled`,
);
await evaluate(
  `(()=>{const c=document.createElement('canvas');c.width=3200;c.height=800;const ctx=c.getContext('2d');ctx.fillStyle='#f5f1e6';ctx.fillRect(0,0,3200,800);ctx.strokeStyle='#334b3b';ctx.lineWidth=8;ctx.strokeRect(40,40,200,160);ctx.font='36px sans-serif';ctx.fillStyle='#334b3b';ctx.fillText('SAUNA',70,140);const bytes=Uint8Array.from(atob(c.toDataURL().split(',')[1]),c=>c.charCodeAt(0)),dt=new DataTransfer();dt.items.add(new File([bytes],'Floor plan.png',{type:'image/png'}));dt.items.add(new File(['<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 200 100"><rect id="wall" x="20" y="30" width="100" height="50"/></svg>'],'Detail.svg',{type:'image/svg+xml'}));document.querySelector('#upload').files=dt.files;document.querySelector('#upload').dispatchEvent(new Event('change'))})()`,
);
await wait(
  `document.querySelectorAll('.drawing').length===2&&!document.querySelector('#upload').disabled`,
);
await evaluate(`document.querySelectorAll('.drawing input')[1].click()`);
const ask = async (question) => {
  const count = await evaluate(
    `document.querySelectorAll('.message.assistant').length`,
  );
  await evaluate(
    `document.querySelector('#question').value=${JSON.stringify(question)};document.querySelector('#question').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))`,
  );
  await wait(
    `document.querySelectorAll('.message.assistant').length===${count + 1}&&!document.querySelector('#send').disabled`,
  );
};
await ask("Kuinka monta saunaa?");
await wait(`document.querySelector('.badge.proposal')`);
await evaluate(`document.querySelector('.citation').click()`);
await wait(
  `document.querySelector('.preview img')?.naturalWidth>0&&document.querySelector('.preview rect')`,
);
const highlighted = await evaluate(
  `({viewBox:document.querySelector('.preview svg').getAttribute('viewBox'),x:document.querySelector('.preview rect').getAttribute('x'),width:document.querySelector('.preview rect').getAttribute('width'),user:document.querySelector('.message.user').textContent})`,
);
if (
  highlighted.viewBox !== "0 0 3200 800" ||
  highlighted.x !== "40" ||
  highlighted.width !== "200" ||
  !highlighted.user.includes("Kuinka")
)
  throw Error(JSON.stringify(highlighted));
await evaluate(
  `document.querySelector('[data-action=focus-evidence]').click()`,
);
await wait(
  `document.querySelector('.preview').clientWidth>document.querySelector('.preview-viewport').clientWidth*2`,
);
const zoomed = await evaluate(
  `({preview:document.querySelector('.preview').clientWidth,viewport:document.querySelector('.preview-viewport').clientWidth,aligned:document.querySelector('.preview svg').getBoundingClientRect().width===document.querySelector('.preview img').getBoundingClientRect().width})`,
);
if (!zoomed.aligned) throw Error(JSON.stringify(zoomed));
await ask("Estimate how many of those saunas?");
await wait(`document.querySelector('.badge.estimate')`);
await ask("What is their volume?");
await wait(`document.querySelector('.badge.abstain')`);
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 960,
  deviceScaleFactor: 1,
  mobile: false,
});
let shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(
  "/private/tmp/stoa42-desktop.png",
  Buffer.from(shot.result.data, "base64"),
);
await send("Emulation.setDeviceMetricsOverride", {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
});
const fits = await evaluate(`document.documentElement.scrollWidth<=innerWidth`);
if (!fits) throw Error("Mobile horizontal overflow");
shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(
  "/private/tmp/stoa42-mobile-evidence.png",
  Buffer.from(shot.result.data, "base64"),
);
await evaluate(`document.querySelector('#close-evidence').click()`);
shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(
  "/private/tmp/stoa42-mobile-chat.png",
  Buffer.from(shot.result.data, "base64"),
);
await evaluate(`document.querySelector('#new-chat').click()`);
await wait(
  `document.querySelectorAll('.chat-button').length>=2&&document.querySelectorAll('.message').length===0`,
);
await evaluate(`document.querySelectorAll('.chat-button')[1].click()`);
await wait(`document.querySelectorAll('.message.assistant').length===3`);
await send("Page.reload");
await wait(
  `document.querySelector('.chat-button')&&!document.querySelector('#new-chat').disabled`,
);
await evaluate(`document.querySelectorAll('.chat-button')[1].click()`);
await wait(`document.querySelectorAll('.message.assistant').length===3`);
const resumed = await evaluate(
  `({selected:document.querySelectorAll('.drawing input:checked').length,drawings:document.querySelectorAll('.drawing').length,messages:document.querySelectorAll('.message').length})`,
);
if (
  resumed.selected !== 1 ||
  resumed.drawings !== 2 ||
  resumed.messages !== 6 ||
  errors.length
)
  throw Error(JSON.stringify({ resumed, errors }));
await evaluate(
  `document.querySelector('#delete-chat').click();document.querySelector('#confirm-delete').click()`,
);
await wait(`document.querySelectorAll('.message').length===0`);
await evaluate(`document.querySelector('#new-chat').click()`);
await wait(`!document.querySelector('#upload').disabled`);
await evaluate(String.raw`(()=>{
  const source = "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nFILE_NAME('','',(),(),'','','');\nFILE_SCHEMA(('IFC4'));\nENDSEC;\n"
    + ' '.repeat(51 * 1024 * 1024)
    + "\nDATA;\n#1=IFCPROJECT('0000000000000000000000',$,'Large model',$,$,$,$,$,$);\nENDSEC;\nEND-ISO-10303-21;\n";
  const files = new DataTransfer();
  files.items.add(new File([source], 'Large model.IFC', {type:'application/x-step'}));
  document.querySelector('#upload').files = files.files;
  document.querySelector('#upload').dispatchEvent(new Event('change'));
})()`);
await wait(`document.querySelector('.drawing')?.textContent.includes('Large model.IFC')&&!document.querySelector('#upload').disabled`);
const largeIfc = await evaluate(`({uploaded:document.querySelector('.drawing').textContent,limits:document.querySelector('#upload-hint').textContent})`);
if (!largeIfc.limits.includes('512 MiB')) throw Error(JSON.stringify(largeIfc));
await evaluate(`document.querySelector('#delete-chat').click();document.querySelector('#confirm-delete').click()`);
await wait(`document.querySelectorAll('.drawing').length===0`);
console.log(
  JSON.stringify({ highlighted, zoomed, resumed, largeIfc, mobileFits: fits, errors }),
);
ws.close();
