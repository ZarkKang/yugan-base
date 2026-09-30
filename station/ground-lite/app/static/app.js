const API = `${location.origin}/api`;
const WS = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`;
let selectedDroneId = 1;
let sockets = [];
let objectUrls = [];
let videoReconnectTimer = null;
let lastVideoConnectAt = 0;
const videoStats = {
  raw: {connected:false, lastFrameAt:0, frames:0, fps:0, bytes:0, serverUpdatedAt:0, serverFrameCount:0, lastServerFrameCount:0, lastServerChangeAt:0, error:'\u672a\u8fde\u63a5'},
  processed: {connected:false, lastFrameAt:0, frames:0, fps:0, bytes:0, serverUpdatedAt:0, serverFrameCount:0, lastServerFrameCount:0, lastServerChangeAt:0, error:'\u672a\u8fde\u63a5'},
};
let qrDetectionEnabled = false;
let qrDetectionMode = 'off';
let selectedShelfIds = [];
let cachedShelves = [];
let cachedTasks = [];
let inventoryBindings = [];
let inventoryQrItems = [];
let inventoryRfidItems = [];
let rfidItems = [];
let rfidStatus = null;

const $ = id => document.getElementById(id);
const fmtTime = ts => ts ? new Date(ts * 1000).toLocaleString('zh-CN', {hour12:false}) : '-';
const esc = value => String(value ?? '-').replace(/[&<>"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s]));
const fmtCoord = value => {
  if(value === null || value === undefined || value === '') return '-';
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(4) : String(value);
};
const isShelfQrText = value => /^SHELF-[A-Z0-9]+-[A-Z0-9]+$/i.test(String(value || '').trim());

async function getJson(url){ const r = await fetch(url); if(!r.ok) throw new Error(await r.text()); return r.json(); }
async function postJson(url, body={}){ const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}); if(!r.ok) throw new Error(await r.text()); return r.json(); }
function statusLabel(status){
  const map = {online:'在线', busy:'任务中', completed:'任务完成', error:'错误'};
  return map[status] || status || '离线';
}
function badge(status){
  const cls = ['online','completed'].includes(status) ? 'online' : (status === 'error' ? 'error' : (status === 'busy' ? 'warn' : ''));
  return `<span class="badge ${cls}">${esc(statusLabel(status))}</span>`;
}

async function loadAll(){
  await Promise.all([loadHealth(), loadQrControl(), loadDrones(), loadShelves(), loadTasks(), loadQrRecords()]);
}

function switchPage(page){
  document.querySelectorAll('.page').forEach(el => el.classList.toggle('active', el.id === `${page}Page`));
  document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.page === page));
  $('pageTitle').textContent = page === 'publish' ? '任务发布' : (page === 'inventory' ? '盘点判定' : (page === 'database' ? '数据库查看' : (page === 'assistant' ? 'AI 助理' : '无人机监控')));
  if(page === 'inventory') refreshInventoryPage().catch(()=>{});
  if(page === 'database') refreshDatabasePage().catch(()=>{});
}

function updateQrButton(){
  const btn = $('qrToggleBtn');
  if(!btn) return;
  const taskMode = qrDetectionMode === 'task';
  btn.disabled = taskMode;
  btn.textContent = taskMode ? '任务检测中' : (qrDetectionEnabled ? '关闭二维码检测' : '开始检测二维码');
  btn.className = 'toggle-btn ' + ((qrDetectionEnabled || taskMode) ? 'on' : 'off');
}
async function loadQrControl(){
  try{
    const res = await getJson(API + '/qr-control');
    qrDetectionEnabled = !!res.data?.enabled;
    qrDetectionMode = res.data?.mode || 'off';
    updateQrButton();
  }catch(e){ updateQrButton(); }
}
async function toggleQrDetection(){
  const next = !qrDetectionEnabled;
  const res = await postJson(`${API}/qr-control`, {enabled: next});
  qrDetectionEnabled = !!res.data?.enabled;
  updateQrButton();
  renderQrList([]);
  if(qrDetectionEnabled) loadQrRecords().catch(()=>{});
}
async function loadHealth(){
  try{
    const h = await getJson(API + '/health');
    qrDetectionEnabled = !!h.video?.qr_detection_enabled;
    qrDetectionMode = h.video?.qr_detection_mode || qrDetectionMode || 'off';
    updateQrButton();
    const qrState = qrDetectionMode === 'task' ? '任务航点检测中' : (qrDetectionEnabled ? '前端测试开启' : '关闭');
    $('systemStatus').textContent = '服务正常\n视频源：' + (h.video?.source || '-') + '\n二维码检测：' + qrState;
  }catch(e){ $('systemStatus').textContent = '服务异常'; }
}
async function loadDrones(){
  const drones = await getJson(`${API}/drones`);
  if(!drones.some(d => d.id === selectedDroneId) && drones.length) selectedDroneId = drones[0].id;
  $('droneRows').innerHTML = drones.map(d => `<tr class="${d.id===selectedDroneId?'active':''}" onclick="selectDrone(${d.id})"><td>${d.id}</td><td>${esc(d.drone_code)}</td><td>${badge(d.display_status || 'online')}</td><td>${esc(d.battery_level ?? '-')}%</td></tr>`).join('') || '<tr><td colspan="4">暂无无人机</td></tr>';
  const d = drones.find(x => x.id === selectedDroneId) || drones[0];
  renderDetail(d);
}
function renderDetail(d){
  if(!d){ $('droneDetail').innerHTML = '<div class="metric"><strong>-</strong><span>暂无数据</span></div>'; return; }
  $('droneDetail').innerHTML = `
    <div class="metric"><strong>${badge(d.display_status || 'online')}</strong><span>当前状态</span></div>
    <div class="metric"><strong>${esc(d.battery_level ?? '-')}%</strong><span>电池电量</span></div>
    <div class="metric"><strong>(${esc(fmtCoord(d.position_x))}, ${esc(fmtCoord(d.position_y))}, ${esc(fmtCoord(d.position_z))})</strong><span>位置坐标</span></div>
    <div class="metric"><strong>${fmtTime(d.last_seen)}</strong><span>最后心跳</span></div>`;
}

async function loadShelves(){
  const rows = await getJson(`${API}/shelves`);
  cachedShelves = rows;
  renderShelfSelects();
  $('shelfRows').innerHTML = rows.map(s => {
    const code = String(s.shelf_code || '');
    const checked = selectedShelfIds.includes(code) ? 'checked' : '';
    return `<tr><td><input type="checkbox" ${checked} onchange="toggleShelf('${esc(code)}', this.checked)"></td><td>${esc(code)}</td><td>${esc(s.shelf_name)}</td><td>(${esc(fmtCoord(s.position_x))}, ${esc(fmtCoord(s.position_y))}, ${esc(fmtCoord(s.position_z))})</td><td>${fmtTime(s.last_synced_at)}</td></tr>`;
  }).join('') || '<tr><td colspan="5">暂无货架数据</td></tr>';
  renderSelectedShelves();
}
function toggleShelf(code, checked){
  if(checked && !selectedShelfIds.includes(code)) selectedShelfIds.push(code);
  if(!checked) selectedShelfIds = selectedShelfIds.filter(x => x !== code);
  renderSelectedShelves();
}
function renderSelectedShelves(){
  const box = $('selectedShelves');
  if(!box) return;
  box.textContent = selectedShelfIds.length ? selectedShelfIds.join(' -> ') : '未选择货架';
}
function clearShelves(){ selectedShelfIds = []; loadShelves(); }

async function loadTasks(){
  const box = $('taskRows');
  if(!box) return;
  const rows = await getJson(`${API}/tasks`);
  cachedTasks = rows;
  renderInventoryTaskSelect();
  box.innerHTML = rows.map(t => `<tr onclick="selectTask('${esc(t.task_code)}')"><td>${esc(t.task_code)}</td><td>${esc(t.status)}</td><td>${esc(t.drone_id)}</td><td>${esc((t.shelf_ids||[]).length)}</td><td>${fmtTime(t.updated_at)}</td></tr>`).join('') || '<tr><td colspan="5">暂无任务</td></tr>';
}
function selectTask(taskCode){ $('taskCodeInput').value = taskCode; }
async function publishTask(){
  const task_code = $('taskCodeInput').value.trim();
  const name = $('taskNameInput').value.trim() || task_code;
  const drone_id = Number($('taskDroneInput').value || selectedDroneId || 1);
  await postJson(`${API}/tasks`, {task_code, name, drone_id, shelf_ids: selectedShelfIds});
  await loadTasks();
  alert('任务已发布，无人机桥接将获取任务顺序');
}
async function startTask(){
  const taskCode = $('taskCodeInput').value.trim();
  if(!taskCode){ alert('请先选择或填写任务编号'); return; }
  await postJson(`${API}/tasks/${encodeURIComponent(taskCode)}/start`, {});
  await loadTasks();
  alert('启动命令已下发，等待无人机桥接轮询执行');
}

async function abortCurrentTask(){
  const droneId = Number($('taskDroneInput').value || selectedDroneId || 1);
  if(!confirm(`确定终止无人机 ${droneId} 当前正在执行的任务吗？`)) return;
  const result = await postJson(`${API}/drones/${encodeURIComponent(droneId)}/tasks/current/abort`, {});
  await loadTasks();
  alert(`任务 ${result.data.task_code} 已终止，后续任务可以继续下发`);
}

async function loadQrRecords(){
  if(!qrDetectionEnabled){ renderQrList([]); return; }
  const rows = await getJson(`${API}/qr-records?limit=80`);
  renderQrList(rows.map(r => ({text:r.text,type:r.type,bbox:{x:r.bbox_x,y:r.bbox_y,w:r.bbox_w,h:r.bbox_h},ts:r.first_seen_at || r.frame_time || r.created_at,confirm_count:r.confirm_count,task_code:r.task_code || '', shelf_code:r.shelf_code || '', waypoint_id:r.waypoint_id || '', waypoint_index:r.waypoint_index ?? ''})));
}
function renderQrList(items){
  const box = $('qrList');
  if(!items.length){ box.className='qr-list empty'; box.textContent=qrDetectionEnabled ? '暂无二维码识别结果' : '二维码检测已关闭'; return; }
  box.className='qr-list';
  const unique = new Map();
  items.forEach(i => { const key = `${String(i.text || '').trim()}|${i.shelf_code || ''}|${i.waypoint_id || ''}`; if(String(i.text || '').trim() && !unique.has(key)) unique.set(key, i); });
  box.innerHTML = Array.from(unique.values()).map(i => `<div class="qr-item"><strong>${esc(i.text)}</strong><span>${esc(i.type || 'QR')} · x:${esc(i.bbox?.x)} y:${esc(i.bbox?.y)} w:${esc(i.bbox?.w)} h:${esc(i.bbox?.h)} · 确认:${esc(i.confirm_count || 1)} · ${fmtTime(i.ts)} · task_code:${esc(i.task_code || '')} · shelf:${esc(i.shelf_code || '-')} · waypoint:${esc(i.waypoint_id || '-')}</span></div>`).join('');
}
function selectDrone(id){ selectedDroneId = id; $('taskDroneInput').value = id; loadDrones(); connectVideo(); }

function closeVideo(){
  sockets.forEach(ws => {try{ws.close()}catch(e){}});
  sockets=[];
  objectUrls.forEach(u=>URL.revokeObjectURL(u));
  objectUrls=[];
  for(const mode of ['raw','processed']){
    Object.assign(videoStats[mode], {connected:false, lastFrameAt:0, frames:0, fps:0, bytes:0, error:selectedDroneId ? '\u8fde\u63a5\u5df2\u5173\u95ed' : '\u8bf7\u9009\u62e9\u65e0\u4eba\u673a'});
  }
  renderVideoStatus();
}
function connectVideo(){ lastVideoConnectAt = Date.now(); closeVideo(); connectOne('raw', 'rawBox'); connectOne('processed', 'processedBox'); }
function connectOne(mode, boxId){
  const box = $(boxId);
  const stat = videoStats[mode];
  if(!selectedDroneId){
    box.innerHTML = '<span>\u8bf7\u9009\u62e9\u65e0\u4eba\u673a</span>';
    stat.connected = false;
    stat.error = '\u8bf7\u9009\u62e9\u65e0\u4eba\u673a';
    renderVideoStatus();
    return;
  }
  box.innerHTML = '<span>\u7b49\u5f85\u89c6\u9891\u6d41...</span>';
  stat.connected = false;
  stat.error = '\u8fde\u63a5\u4e2d';
  renderVideoStatus();
  const ws = new WebSocket(`${WS}/video/${selectedDroneId}/${mode}`);
  ws.binaryType = 'arraybuffer';
  sockets.push(ws);
  let img = null, currentUrl = '';
  ws.onopen = () => { stat.connected = true; stat.error = ''; renderVideoStatus(); };
  ws.onmessage = ev => {
    if(typeof ev.data === 'string'){
      try{ const msg = JSON.parse(ev.data); if(msg.type === 'qr' && qrDetectionEnabled) renderQrList((msg.items||[]).map(x => ({...x, ts: x.first_seen_at || msg.updated_at, task_code:x.task_code || '', shelf_code:x.shelf_code || '', waypoint_id:x.waypoint_id || '', waypoint_index:x.waypoint_index ?? ''}))); }catch(e){}
      return;
    }
    const blob = ev.data instanceof Blob ? ev.data : new Blob([ev.data], {type:'image/jpeg'});
    const url = URL.createObjectURL(blob); objectUrls.push(url);
    if(!img){ img = document.createElement('img'); box.innerHTML=''; box.appendChild(img); }
    const old = currentUrl; currentUrl = url; img.onload = () => { if(old) URL.revokeObjectURL(old); }; img.src = url;
    if(objectUrls.length > 24){ const u = objectUrls.shift(); if(u !== currentUrl && u !== old) URL.revokeObjectURL(u); }
    stat.connected = true;
    stat.lastFrameAt = Date.now();
    stat.frames += 1;
    stat.bytes = blob.size || 0;
    stat.error = '';
    renderVideoStatus();
  };
  ws.onclose = () => { stat.connected = false; stat.error = 'WebSocket \u5df2\u65ad\u5f00'; if(!img) box.innerHTML = '<span>\u89c6\u9891\u8fde\u63a5\u5df2\u65ad\u5f00</span>'; renderVideoStatus(); };
  ws.onerror = () => { stat.connected = false; stat.error = 'WebSocket \u5f02\u5e38'; if(!img) box.innerHTML = '<span>\u89c6\u9891\u8fde\u63a5\u5f02\u5e38</span>'; renderVideoStatus(); };
}

function updateVideoServerStats(video){
  if(!video || !selectedDroneId) return;
  const id = String(selectedDroneId);
  const updatedAt = Number(video.updated_at?.[id] || 0) * 1000;
  const frameCount = Number(video.frame_count?.[id] || 0);
  for(const mode of ['raw','processed']){
    const stat = videoStats[mode];
    if(updatedAt) stat.serverUpdatedAt = updatedAt;
    stat.serverFrameCount = frameCount;
    if(frameCount !== stat.lastServerFrameCount){
      stat.lastServerFrameCount = frameCount;
      stat.lastServerChangeAt = Date.now();
    }
  }
}

async function pollVideoHealth(){
  try{
    const h = await getJson(API + '/health');
    updateVideoServerStats(h.video || null);
  }catch(e){}
  renderVideoStatus();
}

function fmtAge(ms){
  if(!Number.isFinite(ms) || ms < 0) return '-';
  if(ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms/1000).toFixed(1)} s`;
}

function maybeReconnectVideo(){
  if(!selectedDroneId) return;
  const now = Date.now();
  if(now - lastVideoConnectAt < 5000) return;
  const hasServerFrames = ['raw','processed'].some(mode => {
    const stat = videoStats[mode];
    const serverAge = stat.serverUpdatedAt ? now - stat.serverUpdatedAt : Infinity;
    return stat.serverFrameCount > 0 && serverAge < 5000;
  });
  const frontendDisconnected = ['raw','processed'].some(mode => !videoStats[mode].connected);
  if(hasServerFrames && frontendDisconnected){
    connectVideo();
  }
}

function renderVideoStatus(){
  const now = Date.now();
  for(const mode of ['raw','processed']){
    const stat = videoStats[mode];
    const el = mode === 'raw' ? $('rawVideoStatus') : $('processedVideoStatus');
    if(!el) continue;
    const clientAge = stat.lastFrameAt ? now - stat.lastFrameAt : Infinity;
    const serverAge = stat.serverUpdatedAt ? now - stat.serverUpdatedAt : Infinity;
    const serverStale = stat.lastServerChangeAt ? now - stat.lastServerChangeAt : Infinity;
    let level = 'ok';
    let label = '\u6b63\u5e38';
    if(!selectedDroneId){ level = ''; label = '\u672a\u9009\u62e9\u65e0\u4eba\u673a'; }
    else if(!stat.connected){ level = 'error'; label = stat.error || '\u524d\u7aef\u672a\u8fde\u63a5'; }
    else if(clientAge > 8000 || serverAge > 8000 || serverStale > 8000){ level = 'error'; label = '\u89c6\u9891\u65ad\u5f00/\u65e0\u65b0\u5e27'; }
    else if(clientAge > 2000 || serverAge > 2000 || serverStale > 3000){ level = 'warn'; label = '\u89c6\u9891\u5361\u987f'; }
    el.className = `video-status ${level}`.trim();
    el.innerHTML = `\u89c6\u9891\u72b6\u6001\uff1a${label} \uff5c \u524d\u7aef\u5e27\u9f84 ${fmtAge(clientAge)} \uff5c \u5730\u9762\u7aef\u5e27\u9f84 ${fmtAge(serverAge)} \uff5c \u5e27\u8ba1\u6570 ${stat.serverFrameCount || 0} \uff5c \u524d\u7aefFPS ${stat.fps || 0} \uff5c \u6700\u8fd1\u5305 ${(stat.bytes/1024).toFixed(0)} KB`;
  }
}

setInterval(() => {
  for(const mode of ['raw','processed']){
    const stat = videoStats[mode];
    const frames = stat.frames || 0;
    stat.fps = frames - (stat._lastFrames || 0);
    stat._lastFrames = frames;
  }
  pollVideoHealth();
  maybeReconnectVideo();
}, 1000);


async function loadInventoryBindings(){
  inventoryBindings = await getJson(`${API}/inventory-bindings`);
}
function renderShelfSelects(){
  const select = $('bindShelfSelect');
  if(!select) return;
  select.innerHTML = cachedShelves.map(s => `<option value="${esc(s.shelf_code)}">${esc(s.shelf_code)} ${esc(s.shelf_name || '')}</option>`).join('') || '<option value="">暂无货架</option>';
}
function renderInventoryTaskSelect(){
  const select = $('inventoryTaskSelect');
  if(!select) return;
  select.innerHTML = cachedTasks.map(t => `<option value="${esc(t.task_code)}">${esc(t.task_code)} · ${esc(t.status)} · ${(t.shelf_ids||[]).length}个货架</option>`).join('') || '<option value="">暂无任务</option>';
}
function renderRfidShelfSelect(){
  const select = $('rfidShelfSelect');
  if(!select) return;
  select.innerHTML = '<option value="">不指定货架</option>' + cachedShelves.map(s => `<option value="${esc(s.shelf_code)}">${esc(s.shelf_code)} ${esc(s.shelf_name || '')}</option>`).join('');
}
function rfidResultLabel(item){
  const result = item.result || item.match_status || '-';
  return result === 'matched' ? '位置正确' : result;
}
function renderRfidStatus(){
  const box = $('rfidSummary');
  if(!box) return;
  const ports = Array.isArray(rfidStatus?.ports) ? rfidStatus.ports : [];
  box.innerHTML = `
    <div><strong>${rfidStatus?.connected ? '已连接' : '未连接'}</strong><span>连接状态</span></div>
    <div><strong>${esc(rfidStatus?.port || '-')}</strong><span>当前串口</span></div>
    <div><strong>${esc(rfidStatus?.power_dbm ?? '-')} dBm</strong><span>当前功率</span></div>
    <div><strong>${ports.length}</strong><span>可用串口</span></div>`;
  const select = $('rfidPortSelect');
  if(select){
    const current = select.value || rfidStatus?.port || '';
    select.innerHTML = ports.map(p => `<option value="${esc(p)}">${esc(p)}</option>`).join('') || `<option value="${esc(rfidStatus?.port || '/dev/ttyUSB0')}">${esc(rfidStatus?.port || '/dev/ttyUSB0')}</option>`;
    if(current) select.value = current;
  }
}
function renderRfidRows(records){
  const box = $('rfidRows');
  if(!box) return;
  rfidItems = records || rfidItems || [];
  box.innerHTML = rfidItems.map(r => `<tr><td>${esc(r.epc || r.rfid)}</td><td>${esc(r.rssi ?? '-')}</td><td><span class="result ${resultClass(rfidResultLabel(r))}">${esc(rfidResultLabel(r))}</span></td><td>${esc(r.sku || '-')}</td><td>${esc(r.bound_shelf || r.shelf_code || '-')}</td><td>${esc(r.note || '-')}</td></tr>`).join('') || '<tr><td colspan="6">暂无 RFID 读取结果</td></tr>';
}
async function loadRfidStatus(){
  try{
    const [statusRes, portsRes] = await Promise.all([getJson(`${API}/rfid/status`), getJson(`${API}/rfid/ports`)]);
    rfidStatus = {...(statusRes.data || {}), ports: portsRes.data?.ports || []};
  }catch(e){
    rfidStatus = {connected:false, port:'/dev/ttyUSB0', ports:[], last_error:e.message};
  }
  renderRfidStatus();
}
function rfidRequestBody(){
  return {
    port: $('rfidPortSelect')?.value || '/dev/ttyUSB0',
    power_dbm: Number($('rfidPowerInput')?.value || 12),
    shelf_code: $('rfidShelfSelect')?.value || '',
    task_code: $('inventoryTaskSelect')?.value || $('taskCodeInput')?.value?.trim() || ''
  };
}
async function connectRfid(){
  const res = await postJson(`${API}/rfid/connect`, rfidRequestBody());
  rfidStatus = res.data || rfidStatus;
  await loadRfidStatus();
}
async function stopRfid(){
  const res = await postJson(`${API}/rfid/stop`, {});
  rfidStatus = res.data || rfidStatus;
  await loadRfidStatus();
}
function handleRfidScanResponse(res){
  const records = res.data?.records || [];
  const saved = res.data?.saved?.records || [];
  const merged = saved.length ? saved : records;
  if(!merged.length && res.data?.no_tag){
    renderRfidRows([{epc:'-', rssi:'-', result:'未读到标签', sku:'-', bound_shelf:'-', note:res.data.message || '本次未读到 RFID 标签，请调整距离、角度或改用限时扫描。'}]);
  }else{
    renderRfidRows(merged);
  }
  const first = merged.find(x => x.epc || x.rfid);
  if(first && $('bindRfidInput')) $('bindRfidInput').value = first.epc || first.rfid;
  return merged;
}
async function scanRfidOnce(){
  const res = await postJson(`${API}/rfid/scan-once`, rfidRequestBody());
  handleRfidScanResponse(res);
  await loadRfidStatus();
}
async function scanRfidWindow(){
  const body = {...rfidRequestBody(), duration:3};
  const res = await postJson(`${API}/rfid/scan-window`, body);
  handleRfidScanResponse(res);
  await loadRfidStatus();
}
async function refreshInventoryPage(){
  try{ await loadInventoryBindings(); }
  catch(e){ console.warn('inventory bindings load failed', e); inventoryBindings = []; }
  renderShelfSelects();
  renderRfidShelfSelect();
  renderInventoryTaskSelect();
  await loadRfidStatus();
  renderBindings();
  renderJudgeSummary([]);
  if(!$('judgeRows').innerHTML) $('judgeRows').innerHTML = '<tr><td colspan="6">请选择任务并加载二维码结果</td></tr>';
}
async function addInventoryBinding(){
  const rfid = $('bindRfidInput').value.trim();
  const sku = $('bindSkuInput').value.trim();
  const shelf = $('bindShelfSelect').value.trim();
  if(!rfid || !sku || !shelf){ alert('请填写 RFID、SKU 并选择货架'); return; }
  await postJson(`${API}/inventory-bindings`, {rfid, sku, shelf_code:shelf});
  $('bindRfidInput').value = '';
  $('bindSkuInput').value = '';
  await refreshInventoryPage();
}
async function deleteInventoryBinding(id){
  if(!confirm('确认删除这条 RFID-SKU-货架绑定？')) return;
  const r = await fetch(`${API}/inventory-bindings/${encodeURIComponent(id)}`, {method:'DELETE'});
  if(!r.ok) throw new Error(await r.text());
  await refreshInventoryPage();
}
async function clearInventoryBindings(){
  const input = prompt('清空后端数据库中的全部 RFID-SKU-货架绑定。请输入 inventory_bindings 确认：');
  if(input !== 'inventory_bindings') return;
  const r = await fetch(`${API}/inventory-bindings`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify({confirm:'inventory_bindings'})});
  if(!r.ok) throw new Error(await r.text());
  await refreshInventoryPage();
}
function renderBindings(){
  const box = $('bindingRows');
  if(!box) return;
  box.innerHTML = inventoryBindings.map(b => `<tr><td>${esc(b.rfid)}</td><td>${esc(b.sku)}</td><td>${esc(b.shelf_code)}</td><td><button onclick="removeInventoryBinding(${Number(b.id)})">删除</button></td></tr>`).join('') || '<tr><td colspan="4">暂无后端绑定，请先录入 RFID、SKU 与货架</td></tr>';
}
async function loadInventoryTaskQr(){
  const taskCode = $('inventoryTaskSelect').value || $('taskCodeInput').value.trim();
  if(!taskCode){ alert('请选择任务'); return; }
  const [qrRows, rfidRows] = await Promise.all([
    getJson(`${API}/tasks/${encodeURIComponent(taskCode)}/qr-records?limit=500`),
    getJson(`${API}/tasks/${encodeURIComponent(taskCode)}/rfid-records?limit=1000`)
  ]);
  inventoryQrItems = qrRows.map(r => ({sku:String(r.text || '').trim(), task_code:r.task_code, shelf_code:r.shelf_code || '', waypoint_id:r.waypoint_id || '', waypoint_index:r.waypoint_index, ts:r.first_seen_at || r.frame_time || r.created_at})).filter(x => x.sku && !isShelfQrText(x.sku));
  inventoryRfidItems = rfidRows.map(r => ({epc:String(r.epc || r.rfid || '').trim().toUpperCase(), rssi:r.rssi, bound_sku:r.bound_sku || '', bound_shelf:r.bound_shelf || '', match_status:r.match_status || ''})).filter(x => x.epc);
  judgeInventory();
}
function judgeInventory(){
  const taskCode = $('inventoryTaskSelect').value || $('taskCodeInput').value.trim();
  const task = cachedTasks.find(t => t.task_code === taskCode) || {};
  const taskShelves = task.shelf_ids || [];
  const scanned = new Set(inventoryQrItems.map(x => x.sku));
  const scannedRfid = new Set(inventoryRfidItems.map(x => x.epc));
  const bySku = new Map(inventoryBindings.map(b => [b.sku, b]));
  const byRfid = new Map(inventoryBindings.map(b => [String(b.rfid || '').trim().toUpperCase(), b]));
  const results = [];
  inventoryQrItems.forEach(item => {
    const scannedShelf = item.shelf_code || '';
    const bind = bySku.get(item.sku);
    if(!bind){
      results.push({sku:item.sku, rfid:'-', shelf:'-', taskShelf:scannedShelf || taskShelves.join(' -> ') || '-', result:'疑似缺失', note:'本次识别到 SKU，但基础绑定中不存在，需人工确认是否未入库或绑定遗漏'});
      return;
    }
    const inTaskShelf = scannedShelf ? scannedShelf === bind.shelf_code : taskShelves.includes(bind.shelf_code);
    results.push({
      sku:item.sku,
      rfid:bind.rfid,
      shelf:bind.shelf_code,
      taskShelf:scannedShelf || taskShelves.join(' -> ') || '-',
      result:inTaskShelf ? '位置正确' : '放错',
      note:inTaskShelf ? 'SKU 已识别，且识别货架与绑定货架一致' : 'SKU 已识别，但识别货架与绑定货架不一致'
    });
  });
  inventoryBindings.forEach(bind => {
    const shouldScan = !taskShelves.length || taskShelves.includes(bind.shelf_code);
    if(shouldScan && !scanned.has(bind.sku)){
      const rfidSeen = scannedRfid.has(String(bind.rfid || '').trim().toUpperCase());
      results.push(rfidSeen
        ? {sku:bind.sku, rfid:bind.rfid, shelf:bind.shelf_code, taskShelf:taskShelves.join(' -> ') || '-', result:'漏扫', note:'任务 RFID 已读取到该货物，但二维码未识别；建议复核二维码遮挡、相机角度或停留时间'}
        : {sku:bind.sku, rfid:bind.rfid, shelf:bind.shelf_code, taskShelf:taskShelves.join(' -> ') || '-', result:'疑似缺失', note:'二维码与 RFID 均未在本次任务结果中识别到；可能由遮挡、距离、角度或标签问题导致，不能直接证明不在库'}
      );
    }
  });
  inventoryRfidItems.forEach(item => {
    if(!byRfid.has(item.epc)){
      results.push({sku:'-', rfid:item.epc, shelf:'-', taskShelf:taskShelves.join(' -> ') || '-', result:'未绑定', note:'本次任务读取到未建立 RFID-SKU-货架基础绑定的标签，需人工核实'});
    }
  });
  renderJudgeRows(results);
  renderJudgeSummary(results);
}
function resultClass(result){ return {'位置正确':'ok','疑似缺失':'missing','放错':'wrong','漏扫':'missed','未绑定':'missing'}[result] || ''; }
function renderJudgeRows(results){
  results = (results || []).filter(r => !isShelfQrText(r.sku));
  const box = $('judgeRows');
  if(!box) return;
  box.innerHTML = results.map(r => `<tr><td>${esc(r.sku)}</td><td>${esc(r.rfid)}</td><td>${esc(r.shelf)}</td><td>${esc(r.taskShelf)}</td><td><span class="result ${resultClass(r.result)}">${esc(r.result)}</span></td><td>${esc(r.note)}</td></tr>`).join('') || '<tr><td colspan="6">暂无可判定数据</td></tr>';
}
function renderJudgeSummary(results){
  const box = $('judgeSummary');
  if(!box) return;
  const names = ['位置正确','疑似缺失','放错','漏扫'];
  const counts = Object.fromEntries(names.map(n => [n, results.filter(r => r.result === n).length]));
  box.innerHTML = names.map(n => `<div><strong>${counts[n]}</strong><span>${n}</span></div>`).join('') + `<div><strong>${inventoryQrItems.length}</strong><span>任务识别 SKU</span></div>`;
}


let dbTables = [];
let currentDbData = null;
function tableLabel(name){
  const map = {
    drones:'无人机表', shelves:'货架表', inspection_tasks:'任务表', inspection_task_shelves:'任务货架顺序',
    inventory_bindings:'RFID绑定表', rfid_scan_sessions:'RFID扫描会话', rfid_scan_records:'RFID扫描记录',
    drone_commands:'无人机指令', drone_task_context:'当前任务上下文', qr_records:'二维码记录'
  };
  return map[name] || name;
}
function formatDbValue(key, value){
  if(value === null || value === undefined || value === '') return '-';
  if(['created_at','updated_at','last_seen','published_at','started_at','stopped_at','completed_at','consumed_at','frame_time','first_seen_at','last_seen_at','last_synced_at'].includes(key)){
    return fmtTime(Number(value));
  }
  if(typeof value === 'object') return JSON.stringify(value);
  const text = String(value);
  return text.length > 180 ? `${text.slice(0, 180)}...` : text;
}
async function refreshDatabasePage(){
  dbTables = await getJson(`${API}/db/tables`);
  const select = $('dbTableSelect');
  if(!select) return;
  const current = select.value;
  select.innerHTML = dbTables.map(t => `<option value="${esc(t.name)}">${tableLabel(t.name)} (${esc(t.name)}) · ${t.count}</option>`).join('') || '<option value="">暂无表</option>';
  if(current && dbTables.some(t => t.name === current)) select.value = current;
  if(select.value) await loadDbTable();
}
async function loadDbTable(){
  const table = $('dbTableSelect').value;
  if(!table) return;
  const data = await getJson(`${API}/db/tables/${encodeURIComponent(table)}?limit=120`);
  currentDbData = data;
  const columns = data.columns.map(c => c.name);
  const canDelete = !!data.can_delete;
  $('dbSummary').innerHTML = `
    <div><strong>${tableLabel(data.table)}</strong><span>表名：${esc(data.table)}</span></div>
    <div><strong>${data.count}</strong><span>总记录</span></div>
    <div><strong>${columns.length}</strong><span>字段数</span></div>
    <div><strong>${canDelete ? '可删除' : '只读'}</strong><span>操作权限</span></div>`;
  $('clearDbTableBtn').disabled = !canDelete;
  const actionHead = canDelete && columns.includes('id') ? '<th>操作</th>' : '';
  $('dbTableHead').innerHTML = `<tr>${actionHead}${columns.map(c => `<th>${esc(c)}</th>`).join('')}</tr>`;
  $('dbTableBody').innerHTML = data.rows.map(row => {
    const action = canDelete && columns.includes('id') ? `<td><button class="mini danger" onclick="deleteDbRow(${Number(row.id)})">删除</button></td>` : '';
    return `<tr>${action}${columns.map(c => `<td title="${esc(row[c])}">${esc(formatDbValue(c, row[c]))}</td>`).join('')}</tr>`;
  }).join('') || `<tr><td colspan="${columns.length + (actionHead ? 1 : 0) || 1}">暂无数据</td></tr>`;
}
function exportDbTable(){
  const table = $('dbTableSelect').value;
  if(!table) return;
  window.location.href = `${API}/db/tables/${encodeURIComponent(table)}/export`;
}
async function deleteDbRow(id){
  const table = $('dbTableSelect').value;
  if(!table || !id) return;
  if(!confirm(`确认删除 ${table} 表中 ID=${id} 的记录？`)) return;
  const r = await fetch(`${API}/db/tables/${encodeURIComponent(table)}`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids:[id]})});
  if(!r.ok) throw new Error(await r.text());
  await refreshDatabasePage();
}
async function clearDbTable(){
  const table = $('dbTableSelect').value;
  if(!table) return;
  if(!currentDbData?.can_delete){ alert('该表为只读保护表，不能在页面清空'); return; }
  const input = prompt(`清空 ${tableLabel(table)} 会删除该表全部 ${currentDbData.count} 条记录。请输入表名确认：${table}`);
  if(input !== table) return;
  const r = await fetch(`${API}/db/tables/${encodeURIComponent(table)}`, {method:'DELETE', headers:{'Content-Type':'application/json'}, body:JSON.stringify({confirm:table})});
  if(!r.ok) throw new Error(await r.text());
  await refreshDatabasePage();
}

window.toggleShelf = toggleShelf;
window.selectDrone = selectDrone;
window.selectTask = selectTask;
window.removeInventoryBinding = id => deleteInventoryBinding(id).catch(e => alert(`删除绑定失败：${e.message}`));
window.deleteDbRow = id => deleteDbRow(id).catch(e => alert(`删除失败：${e.message}`));

document.querySelectorAll('.nav-item').forEach(btn => btn.onclick = () => switchPage(btn.dataset.page));
$('refreshBtn').onclick = loadAll;
$('qrToggleBtn').onclick = () => toggleQrDetection().catch(() => alert('二维码检测开关失败'));
$('publishTaskBtn').onclick = () => publishTask().catch(e => alert(`任务发布失败：${e.message}`));
$('startTaskBtn').onclick = () => startTask().catch(e => alert(`任务启动失败：${e.message}`));
$('abortTaskBtn').onclick = () => abortCurrentTask().catch(e => alert(`任务终止失败：${e.message}`));
$('clearShelfBtn').onclick = clearShelves;
if($('addBindingBtn')) $('addBindingBtn').onclick = () => addInventoryBinding().catch(e => alert(`绑定保存失败：${e.message}`));
if($('clearBindingsBtn')) $('clearBindingsBtn').onclick = () => clearInventoryBindings().catch(e => alert(`清空绑定失败：${e.message}`));
if($('loadInventoryTaskBtn')) $('loadInventoryTaskBtn').onclick = () => loadInventoryTaskQr().catch(e => alert(`任务结果加载失败：${e.message}`));
if($('judgeInventoryBtn')) $('judgeInventoryBtn').onclick = judgeInventory;
if($('rfidConnectBtn')) $('rfidConnectBtn').onclick = () => connectRfid().catch(e => alert(`RFID 连接失败：${e.message}`));
if($('rfidStopBtn')) $('rfidStopBtn').onclick = () => stopRfid().catch(e => alert(`RFID 停止失败：${e.message}`));
if($('rfidScanOnceBtn')) $('rfidScanOnceBtn').onclick = () => scanRfidOnce().catch(e => alert(`RFID 单次读取异常，请检查串口连接：${e.message}`));
if($('rfidScanWindowBtn')) $('rfidScanWindowBtn').onclick = () => scanRfidWindow().catch(e => alert(`RFID 限时扫描失败：${e.message}`));
if($('loadDbTableBtn')) $('loadDbTableBtn').onclick = () => loadDbTable().catch(e => alert(`数据库读取失败：${e.message}`));
if($('exportDbTableBtn')) $('exportDbTableBtn').onclick = exportDbTable;
if($('clearDbTableBtn')) $('clearDbTableBtn').onclick = () => clearDbTable().catch(e => alert(`清空失败：${e.message}`));
if($('dbTableSelect')) $('dbTableSelect').onchange = () => loadDbTable().catch(e => alert(`数据库读取失败：${e.message}`));
loadInventoryBindings().catch(()=>{});
loadRfidStatus().catch(()=>{});
updateQrButton();
loadAll().then(() => { refreshInventoryPage().catch(()=>{}); connectVideo(); });
setInterval(loadAll, 3000);
