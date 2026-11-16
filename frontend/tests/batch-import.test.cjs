const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../assets/batch-import.js'),'utf8');
const start=source.indexOf('  function fileResult('),end=source.indexOf('  function setMode(',start);
const fileResult=vm.runInNewContext(source.slice(start,end)+'\nfileResult',{active:job=>['running','queued'].includes(job?.status)});

test('batch results distinguish new, duplicate, pending, cancelled and failed files',()=>{
 assert.equal(fileResult({status:201,result:{paper_id:'new'}}).tone,'success');
 assert.match(fileResult({status:201,result:{duplicate:true}}).label,/未重复导入/);
 assert.equal(fileResult({status:409,result:{conflict:true}}).tone,'conflict');
 assert.equal(fileResult({status:409,error:'different conflict'}).tone,'error');
 assert.match(fileResult({status:204,result:{cancelled:true}}).label,/已取消/);
 assert.equal(fileResult({status:400,error:'broken PDF'}).tone,'error');
 assert.equal(fileResult(null).tone,'pending');
});

test('file queue enforces combined size and count while keeping original selection on overflow',()=>{
 const begin=source.indexOf('  function addFiles('),finish=source.indexOf('  function drawJob(',begin);
 const cells={};
 const initial=[{name:'existing.pdf',type:'application/pdf',size:10}];
 const context={queue:initial,uploading:false,MAX_BYTES:100,setMode(){},drawQueue(){},el:id=>cells[id]||={textContent:'',value:''}};
 const add=vm.runInNewContext(source.slice(begin,finish)+'\naddFiles',context);
 add([{name:'oversize.pdf',size:91}]);
 assert.equal(context.queue.length,1);
 assert.match(cells.batchUploadStatus.textContent,/超过/);
 add([{name:'valid.pdf',size:40}]);
 assert.equal(context.queue.length,2);
 add(Array.from({length:19},(_,i)=>({name:`${i}.pdf`,size:1})));
 assert.equal(context.queue.length,2);
 assert.match(cells.batchUploadStatus.textContent,/最多 20/);
 add([{name:'wrong.exe',size:1},{name:'empty.pdf',size:0}]);
 assert.equal(context.queue.length,2);
 assert.match(cells.batchUploadStatus.textContent,/wrong.exe/);
 assert.match(cells.batchUploadStatus.textContent,/文件为空/);
});
