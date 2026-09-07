local dir=debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])')
package.path=dir..'lib/?.lua;'..package.path
local C=require('common');local M=require('model');local S=require('spool');local E=require('engine')
local p,projectPath=reaper.EnumProjects(-1)
assert(projectPath and projectPath~='','Save the independent local working copy first')
local root=COREAPERATE_IPC
if not root then local ok,value=reaper.GetUserInputs('Coreaperate: local IPC folder',1,'Absolute IPC directory:',reaper.GetExtState('coreaperate','ipc'));if not ok then return end;root=value end
reaper.SetExtState('coreaperate','ipc',root,true)
local config=C.read(root..'/bridge.json')
local binding=root..'/binding.json'
if C.exists(binding) then
  assert(C.read(binding).project==projectPath,'IPC directory bound to another project path. Use a separate IPC directory for each copy.')
else C.write(binding,{project=projectPath}) end
local _,raw=reaper.GetProjExtState(p,'coreaperate','baseline');assert(raw~='','Prepare the disposable baseline first')
local baseline=C.decode(raw)
local _,saved=reaper.GetProjExtState(p,'coreaperate','accepted')
local e=E.new(config.client,baseline,saved~='' and C.decode(saved) or nil)
local incoming=S.new(root,'to_bridge');local outgoing=S.new(root,'from_bridge')
local pulse=0;local clock=0;local observed;local settled=0;local lastExport='';local target=1;local replay=false
local failedSnapshot=nil;local savedFailure=false
local function bound()
  local i=0;while true do local candidate=reaper.EnumProjects(i);if not candidate then return false end;if candidate==p then return true end;i=i+1 end
end
local function checkpoint() reaper.SetProjExtState(p,'coreaperate','accepted',C.encode(e.accepted));reaper.SetProjExtState(p,'coreaperate','seq',tostring(e.seq)) end
local function preserve() lastExport=M.export(p,root,e.accepted);return lastExport end
local function apply(a,b)
  preserve() -- includes live unsaved chunks before any potentially destructive application
  M.apply_track(p,a,b)
end
local function pause(reason)
  e.paused=true;e.status=tostring(reason)
  if not savedFailure then pcall(preserve);savedFailure=true end
end
local function connect()
  assert(next(e.flight)==nil,'Pending proposals preserved. Restart bridge/companion to reconcile their outcomes first.')
  outgoing:send(C.object{type='bridge_hello',baseline=baseline})
  e.paused=true;e.status='Connecting / checking baseline';pulse=reaper.time_precise();savedFailure=false
end
local function control(kind)
  local current=M.capture(p);local id=current.order[target]
  local payload=C.object()
  if kind=='handover' then payload.owner=config.client=='A' and 'B' or 'A' end
  outgoing:send(e:operation(id,kind,payload,current))
end
local function restore()
  assert(e.paused,'Pause before recovery')
  preserve()
  local desired=failedSnapshot and failedSnapshot.project or e.accepted
  if reaper.ShowMessageBox('Live track chunks exported to:\n'..lastExport..'\n\nRestore supported musical data to the LAST RECEIVED accepted state?\nNo offline merge. Unsupported structure/content must be repaired manually first.','Explicit destructive recovery',4)~=6 then return end
  local current=M.capture(p)
  assert(C.equal(current.config,desired.config) and C.equal(current.order,desired.order),'Restore cannot repair structural divergence')
  for _,id in ipairs(current.order) do if not C.equal(current.tracks[id],desired.tracks[id]) then M.apply_track(p,current.tracks[id],desired.tracks[id]) end end
  assert(C.equal(M.capture(p),desired),'Recovery verification failed')
  e.accepted=C.copy(desired)
  checkpoint();e.status='Restored saved accepted state. Restart bridge/companion if pending; then Connect.'
end
local buttons={
  {'Connect',connect},{'Pause/disconnect',function() outgoing:send({type='disconnect'});pause('Paused; local work retained') end},
  {'Claim',function()control('claim')end},{'Release',function()control('release')end},
  {'Hand over',function()control('handover')end},{'Undo my last shared edit',function()control('undo')end},
  {'Export live recovery',preserve},{'Restore accepted...',restore}
}
gfx.init('Coreaperate v0.1 - '..config.client,780,460)
gfx.setfont(1,'Arial',16)
local down=false
local function panel()
  gfx.set(.09,.11,.14);gfx.rect(0,0,gfx.w,gfx.h,1);gfx.set(.92,.93,.95);gfx.x=12;gfx.y=10
  gfx.drawstr('EXPERIMENTAL • disposable copies • FX/samples NOT synchronized\nNative Undo is project-wide. Use scoped shared Undo below.\nSession: '..baseline.session..'   Peer presence: '..table.concat(e.peers,', ')..'\n'..(e.paused and 'PAUSED: ' or '')..e.status:sub(1,150))
  local y=100
  for i,id in ipairs(baseline.order) do
    local meta=e.meta[id] or {owner='',revision=0,epoch=0};local t=e.accepted.tracks[id]
    gfx.x=12;gfx.y=y;gfx.set(i==target and .4 or .9,.85,.9)
    gfx.drawstr((i==target and '> ' or '  ')..t.name..' | owner '..(meta.owner~='' and meta.owner or 'unclaimed')..' | rev '..meta.revision..' epoch '..meta.epoch..(e.flight[id] and ' | pending' or ''))
    if gfx.mouse_cap&1==1 and not down and gfx.mouse_y>=y and gfx.mouse_y<y+24 then target=i end
    y=y+24
  end
  y=math.max(y+12,170)
  for i,b in ipairs(buttons) do
    local x=12+((i-1)%3)*250;local by=y+math.floor((i-1)/3)*38
    gfx.set(.2,.27,.34);gfx.rect(x,by,240,30,1);gfx.set(1,1,1);gfx.x=x+8;gfx.y=by+6;gfx.drawstr(b[1])
    if gfx.mouse_cap&1==1 and not down and gfx.mouse_x>=x and gfx.mouse_x<x+240 and gfx.mouse_y>=by and gfx.mouse_y<by+30 then local ok,err=pcall(b[2]);if not ok then pause(err) end end
  end
  gfx.x=12;gfx.y=y+125;gfx.drawstr('Recovery export: '..lastExport:sub(-90))
  down=gfx.mouse_cap&1==1;gfx.update()
end
local function tick()
  if not bound() then gfx.quit();return end
  if gfx.getchar()<0 then pcall(function()outgoing:send({type='disconnect'})end);return end
  local now=reaper.time_precise()
  if now-clock>=.15 then
    clock=now
    local ok,err=xpcall(function()
      local current=M.capture(p)
      for _,entry in ipairs(incoming:receive()) do
        local msg=entry.message;local ack=true
        if msg.type=='snapshot' then
          local worked,why=pcall(function()e:snapshot(msg,current,apply)end)
          if worked then
            failedSnapshot=nil;checkpoint();current=M.capture(p);replay=false;savedFailure=false
            outgoing:send({type='ready',seq=e.seq})
          else failedSnapshot=msg;pause(why) end
        elseif msg.type=='event' then
          if e.paused then ack=false else
            local result=e:event(msg,current,apply)
            if result=='gap' then
              ack=false;if not replay then outgoing:send({type='replay',after=e.seq});replay=true end
            else checkpoint();outgoing:send({type='ack',seq=e.seq});current=M.capture(p);replay=false end
          end
        elseif msg.type=='connection' then
          if msg.connected then pulse=now else pause(msg.reason) end
        elseif msg.type=='presence' then e.peers=msg.peers
        elseif msg.type=='rejected' or msg.type=='fatal' then
          for id,op in pairs(e.flight) do if op.id==msg.id then e.flight[id]=nil end end
          pause(msg.reason)
        else error('Unknown inbound message type') end
        if ack then incoming:ack(entry.id) end
      end
      if not e.paused and now-pulse>3 then pause('Companion heartbeat lost; publication paused') end
      if not e.paused then
        e:check(current)
        if not C.equal(current,observed) then observed=C.copy(current);settled=now end
        if now-settled>=.15 then
          for _,id in ipairs(current.order) do
            if not e.flight[id] then
              local kind,payload=C.diff(e.accepted.tracks[id],current.tracks[id])
              if kind then outgoing:send(e:operation(id,kind,payload,current)) end
            end
          end
        end
      end
    end,debug.traceback)
    if not ok then pause(err) end
  end
  panel();reaper.defer(tick)
end
reaper.atexit(function() pcall(function()outgoing:send({type='disconnect'})end);gfx.quit() end)
local ok,err=pcall(connect);if not ok then pause(err) end
tick()
