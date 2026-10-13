"""Navigation-only log panel, kept separate from the general log UI."""
# ruff: noqa: E501  # Embedded HTML/JS follows the compact device-console convention.

PANEL = '''
<section id="navlogs-panel" hidden>
  <h1>导航日志</h1>
  <p>仅导出导航、车道判断、实际灯光、模型意图和控制状态。独立记录、独立下载，不混入普通 qlog、其他诊断或视频。</p>
  <div id="navlog-state" class="notice">正在读取导航记录…</div>
  <div class="log-range"><label>开始时间<input id="navlog-start" type="datetime-local" onchange="previewNavigationLogs()"></label><label>结束时间<input id="navlog-end" type="datetime-local" onchange="previewNavigationLogs()"></label></div>
  <div class="log-actions"><button onclick="loadNavigationLogs(true)">刷新最近记录</button><button id="navlog-download" onclick="downloadNavigationLogs()" disabled>下载导航日志</button></div>
  <div id="navlog-preview" class="notice">请选择要排查的时间范围</div>
  <p>设备设置中的“导航辅助”可调整关键功能和记录开关。行驶期间自动记录，停车后下载；最多保留 128 MiB，超出后轮转最早记录。</p>
</section>
'''

SCRIPT = '''
let navigationLogStatus=null, navigationLogInitialized=false, navigationLogPreviewValid=false;
function navigationLogRange(){return {start:new Date(document.getElementById('navlog-start').value).getTime(),end:new Date(document.getElementById('navlog-end').value).getTime()};}
async function loadNavigationLogs(refresh=false){
  const state=document.getElementById('navlog-state'),download=document.getElementById('navlog-download');download.disabled=true;
  try{
    let r=await apiFetch('/api/navigation/logs/status',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);
    let data=await r.json();
    if(refresh&&!data.onroad){r=await apiFetch('/api/navigation/logs/flush',{method:'POST'});if(!r.ok)throw new Error((await r.json()).message||'刷新失败');data=await r.json();navigationLogInitialized=false;}
    navigationLogStatus=data;state.className='notice'+(data.error?' onroad':'');
    state.textContent=(data.recorder_running?(data.recording_enabled?'导航记录服务运行中':'导航记录已关闭'):'导航记录服务尚未上线')+' · '+data.file_count+' 个独立文件 · '+formatBytes(data.total_bytes)+(data.error?' · '+data.error:'');
    if(!navigationLogInitialized){const end=Date.now()+60000,start=Math.max(data.start_ms||end-1800000,end-1800000);document.getElementById('navlog-start').value=localTimeInput(start);document.getElementById('navlog-end').value=localTimeInput(end);navigationLogInitialized=true;}
    await previewNavigationLogs();
  }catch(e){state.className='notice onroad';state.textContent='导航日志读取失败：'+e;}
}
async function previewNavigationLogs(){
  const p=document.getElementById('navlog-preview'),b=document.getElementById('navlog-download'),range=navigationLogRange();b.disabled=true;navigationLogPreviewValid=false;
  if(!Number.isFinite(range.start)||!Number.isFinite(range.end)||range.end<=range.start){p.textContent='请选择有效时间范围';return;}
  try{const r=await apiFetch('/api/navigation/logs/preview?start_ms='+range.start+'&end_ms='+range.end,{cache:'no-store'}),d=await r.json();if(!r.ok)throw new Error(d.message||'预览失败');p.textContent=d.file_count+' 个导航文件 · '+formatBytes(d.total_bytes)+' · ZIP 内仅有导航 JSONL 和清单。'+(navigationLogStatus?.onroad?' 行驶中暂不下载。':'');navigationLogPreviewValid=d.file_count>0;b.disabled=!navigationLogPreviewValid||Boolean(navigationLogStatus?.onroad);}catch(e){p.textContent=String(e);}
}
function downloadNavigationLogs(){if(!navigationLogPreviewValid||navigationLogStatus?.onroad)return;const r=navigationLogRange();window.location.assign('/api/navigation/logs/download?start_ms='+r.start+'&end_ms='+r.end);}
'''
