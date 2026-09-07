-- Pure synchronization state machine; REAPER access injected by bridge.
local C=require('common')
local E={};E.__index=E
function E.new(client,baseline,checkpoint)
  return setmetatable({client=client,baseline=baseline,accepted=checkpoint or C.copy(baseline),seq=0,meta={},flight={},paused=true,status='Connect to reconcile',peers={}},E)
end
function E:check(current)
  assert(C.equal(current.config,self.accepted.config) and C.equal(current.order,self.accepted.order) and current.session==self.accepted.session,'Project structure/configuration divergence')
  local previous={}
  for id,t in pairs(self.accepted.tracks) do for iid in pairs(t.items) do previous[iid]=id end end
  for id,t in pairs(current.tracks) do
    for iid in pairs(t.items) do assert(not previous[iid] or previous[iid]==id,'Cross-track move unsupported; preserve branch') end
    if not C.equal(t,self.accepted.tracks[id]) then
      assert(self.meta[id] and self.meta[id].owner==self.client,'Unowned track edited; local work preserved')
    end
  end
end
function E:operation(id,kind,payload,current)
  assert(not self.paused,'Synchronization paused')
  self:check(current)
  assert(not self.flight[id],'Wait for pending acknowledgement')
  if kind=='claim' or kind=='release' or kind=='handover' or kind=='undo' then
    assert(C.equal(current.tracks[id],self.accepted.tracks[id]),'Drain pending edits before ownership/undo')
  end
  local m=assert(self.meta[id]);local op=C.object{protocol=1,session=self.accepted.session,id=C.id(),track=id,revision=m.revision,epoch=m.epoch,type=kind,payload=payload}
  self.flight[id]=op;return op
end
function E:snapshot(msg,current,apply)
  assert(msg.project.session==self.baseline.session and C.equal(msg.project.config,self.baseline.config) and C.equal(msg.project.order,self.baseline.order),'Incompatible snapshot')
  -- Snapshot is safe only when live data is already accepted or a known checkpoint.
  assert(C.equal(current,msg.project) or C.equal(current,self.accepted),'Restart/offline divergence: export local branch before restoring accepted state')
  if not C.equal(current,msg.project) then
    for _,id in ipairs(current.order) do
      if not C.equal(current.tracks[id],msg.project.tracks[id]) then apply(current.tracks[id],msg.project.tracks[id]) end
    end
  end
  self.accepted=C.copy(msg.project);self.meta=msg.meta;self.seq=msg.seq;self.flight={};self.paused=false;self.status='Connected'
end
function E:event(msg,current,apply)
  if msg.seq<=self.seq then return 'duplicate' end
  if msg.seq~=self.seq+1 then return 'gap' end
  assert(not self.paused,'Paused; reconcile snapshot before delivery')
  self:check(current)
  local id=msg.track
  assert(C.equal(msg.before,self.accepted.tracks[id]),'Accepted history mismatch')
  local own=self.flight[id] and self.flight[id].id==msg.id and msg.actor==self.client
  if own and (msg.kind=='properties' or msg.kind=='put_item' or msg.kind=='delete_item') then
    -- Do not touch live state: it may contain newer unsent native edits.
  else
    assert(C.equal(current.tracks[id],self.accepted.tracks[id]),'Local divergence before inbound edit')
    if not C.equal(msg.before,msg.after) then apply(msg.before,msg.after) end
  end
  self.accepted.tracks[id]=C.copy(msg.after);self.meta[id]=msg.meta;self.seq=msg.seq
  if own then self.flight[id]=nil end
  return 'applied'
end
return E
