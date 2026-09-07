local C=require('common')
local R=reaper
local M={}
local function ext(obj,api,key,value)
  local ok,s=api(obj,'P_EXT:coreaperate_'..key,value or '',value~=nil)
  assert(ok or value==nil,'Extension state write failed');return s or ''
end
local function native(it) local _,id=R.GetSetMediaItemInfo_String(it,'GUID','',false);return id end
function M.identify(p,prepare)
  local seen,originals,pools={},{},{}
  assert(R.CountMediaItems(p)<=128,'Project exceeds 128 MIDI items')
  local totalNotes=0
  for i=0,R.CountMediaItems(p)-1 do originals[native(R.GetMediaItem(p,i))]=true end
  for i=0,R.CountMediaItems(p)-1 do
    local it=R.GetMediaItem(p,i);local tk=R.GetActiveTake(it)
    assert(tk and R.CountTakes(it)==1 and R.TakeIsMIDI(tk),'Only single-take MIDI items supported')
    local _,nc,cc,tx=R.MIDI_CountEvts(tk);totalNotes=totalNotes+nc
    assert(nc<=2048 and totalNotes<=4096 and cc<=1 and tx==0,'MIDI size/content limit exceeded; preserve branch')
    local id=ext(it,R.GetSetMediaItemInfo_String,'id')
    local birth=ext(it,R.GetSetMediaItemInfo_String,'birth')
    if birth~='' and birth~=native(it) then
      assert(originals[birth],'Ambiguous copied identity: original is missing; preserve branch')
      id='';ext(tk,R.GetSetMediaItemTakeInfo_String,'id','')
    end
    if id=='' then id=C.id();ext(it,R.GetSetMediaItemInfo_String,'id',id);ext(it,R.GetSetMediaItemInfo_String,'birth',native(it)) end
    local tid=ext(tk,R.GetSetMediaItemTakeInfo_String,'id')
    if tid=='' then tid=C.id();ext(tk,R.GetSetMediaItemTakeInfo_String,'id',tid) end
    assert(not seen[id] and not seen[tid] and id~=tid,'Ambiguous identity collision');seen[id]=true;seen[tid]=true
    local ok,chunk=R.GetItemStateChunk(it,'',false);assert(ok,'Cannot inspect MIDI source')
    local pool=chunk:match('POOLEDEVTS%s+([^%s]+)')
    if pool then assert(not pools[pool],'Pooled MIDI unsupported');pools[pool]=true end
    assert(not chunk:find('IGNTEMPO 1',1,true),'Ignore project tempo unsupported')
  end
end
local function notes(tk,position)
  local ok,raw=R.MIDI_GetAllEvts(tk,'');assert(ok and #raw<262144,'MIDI source too large')
  local pos,tick=1,0;local messages={}
  while pos<=#raw do
    local delta,flags,msg;delta,flags,msg,pos=string.unpack('i4Bs4',raw,pos);tick=tick+delta
    if #msg>0 then messages[#messages+1]={tick=tick,flags=flags,msg=msg} end
  end
  local sourceQN,isQN=R.GetMediaSourceLength(R.GetMediaItemTake_Source(tk))
  assert(isQN,'MIDI source must use musical time')
  local noteEvents=0
  for i,e in ipairs(messages) do
    local status=e.msg:byte(1)>>4
    local note=#e.msg==3 and (status==8 or status==9)
    if note then
      noteEvents=noteEvents+1
      assert(status~=8 or e.msg:byte(3)==0,'Nonzero note-off velocity unsupported; preserved')
    end
    -- Stock REAPER terminator: final, unselected/unmuted CC123 ch1, exactly at source end.
    local ending=i==#messages and e.msg==string.char(0xb0,123,0) and e.flags==0 and
      math.abs(R.MIDI_GetProjQNFromPPQPos(tk,e.tick)-position-sourceQN)<0.000001
    assert(note or ending,'Unsupported MIDI content (CC/SysEx/text/metadata). Preserved; synchronization paused')
    assert((e.flags & 0xfc)==0,'Unsupported MIDI event flags')
  end
  local _,count=R.MIDI_CountEvts(tk);assert(count<=2048,'Note limit exceeded')
  assert(noteEvents==2*count,'Unpaired/raw MIDI note events unsupported; preserved')
  local result=C.array();local selected={};local records={}
  for i=0,count-1 do
    local found,sel,mute,a,b,ch,pitch,vel=R.MIDI_GetNote(tk,i);assert(found)
    local n=C.array{C.q(R.MIDI_GetProjQNFromPPQPos(tk,a)-position),C.q(R.MIDI_GetProjQNFromPPQPos(tk,b)-R.MIDI_GetProjQNFromPPQPos(tk,a)),pitch,vel,ch,mute and 1 or 0,0}
    assert(n[1]>=0 and n[2]>0,'Unsupported negative/zero-length note')
    result[#result+1]=n
    records[#records+1]={note=n,selected=sel,index=i}
    local key=C.encode(n);selected[key]=selected[key] or {};table.insert(selected[key],sel)
  end
  table.sort(result,C.note_less);return result,selected,records
end
function M.capture(p)
  assert(R.ValidatePtr(p,'ReaProject*'),'Bound project closed')
  assert((R.GetPlayStateEx(p)&4)==0,'Recording unsupported; synchronization paused')
  assert(R.CountTempoTimeSigMarkers(p)==0,'Tempo/meter markers unsupported')
  assert(R.Master_GetPlayRate(p)==1,'Project play rate must be 1')
  local num,den,tempo=R.TimeMap_GetTimeSigAtTime(p,0)
  local _,session=R.GetProjExtState(p,'coreaperate','session');assert(session~='','Run prepare.lua first')
  local out=C.object{session=session,config=C.object{tempo=C.q(tempo),numerator=num,denominator=den},order=C.array(),tracks=C.object()}
  local refs={};local total=R.CountTracks(p);assert(total>=1 and total<=16,'Track count outside v0.1 limits')
  M.identify(p)
  for i=0,total-1 do
    local tr=R.GetTrack(p,i);local id=R.GetTrackGUID(tr)
    assert(not out.tracks[id],'Track identity collision')
    assert(R.GetMediaTrackInfo_Value(tr,'I_FOLDERDEPTH')==0,'Folder tracks unsupported')
    assert(R.GetMediaTrackInfo_Value(tr,'I_FREEMODE')==0,'Track lanes unsupported')
    assert(R.GetMediaTrackInfo_Value(tr,'B_MAINSEND')==1 and R.GetMediaTrackInfo_Value(tr,'I_NCHAN')==2,'Only default stereo master routing supported')
    -- I_PANMODE may be -1 (inherit project default). Validate the resolved mode
    -- without changing the track setting or accepting an inherited stereo/dual pan.
    local panok,_,_,panmode=R.GetTrackUIPan(tr)
    assert(panok,'Cannot read effective track pan mode')
    assert(panmode==0 or panmode==3,'Use stereo balance pan mode, not dual/stereo pan (effective mode '..tostring(panmode)..')')
    assert(R.CountTrackEnvelopes(tr)==0,'Automation envelopes unsupported')
    assert(R.GetTrackNumSends(tr,0)==0 and R.GetTrackNumSends(tr,-1)==0 and R.GetTrackNumSends(tr,1)==0,'Routing sends unsupported')
    local _,name=R.GetSetMediaTrackInfo_String(tr,'P_NAME','',false)
    local t=C.object{id=id,name=name,volume=C.q(R.GetMediaTrackInfo_Value(tr,'D_VOL')),pan=C.q(R.GetMediaTrackInfo_Value(tr,'D_PAN')),items=C.object()}
    local ref={track=tr,items={}};refs[id]=ref;out.tracks[id]=t;out.order[#out.order+1]=id
    assert(R.CountTrackMediaItems(tr)<=64,'Item limit exceeded')
    for j=0,R.CountTrackMediaItems(tr)-1 do
      local it=R.GetTrackMediaItem(tr,j);local tk=R.GetActiveTake(it)
      assert(R.GetMediaItemInfo_Value(it,'B_LOOPSRC')==0,'Disable Loop source on each MIDI item')
      assert(R.GetMediaItemTakeInfo_Value(tk,'D_PLAYRATE')==1 and R.GetMediaItemTakeInfo_Value(tk,'D_STARTOFFS')==0,'Playback rate/source offset unsupported')
      assert(R.TakeFX_GetCount(tk)==0,'Take FX unsupported')
      assert(R.GetMediaItemTakeInfo_Value(tk,'D_PITCH')==0 and R.GetMediaItemTakeInfo_Value(tk,'D_VOL')==1 and R.GetMediaItemTakeInfo_Value(tk,'D_PAN')==0,'Take pitch/volume/pan unsupported')
      local pos=R.TimeMap2_timeToQN(p,R.GetMediaItemInfo_Value(it,'D_POSITION'))
      local ending=R.TimeMap2_timeToQN(p,R.GetMediaItemInfo_Value(it,'D_POSITION')+R.GetMediaItemInfo_Value(it,'D_LENGTH'))
      local iid=ext(it,R.GetSetMediaItemInfo_String,'id');local tid=ext(tk,R.GetSetMediaItemTakeInfo_String,'id')
      local ns,selection,records=notes(tk,pos)
      t.items[iid]=C.object{id=iid,take=tid,position=C.q(pos),length=C.q(ending-pos),notes=ns}
      ref.items[iid]={item=it,take=tk,selection=selection,records=records}
    end
  end
  assert(#C.encode(out)<524288,'Project exceeds v0.1 size limit')
  return out,refs
end
function M.apply_track(p,before,after)
  local actual,refs=M.capture(p)
  assert(C.equal(actual.tracks[before.id],before),'Local divergence before apply; work preserved')
  local ref=assert(refs[before.id]);local tr=ref.track
  if before.name~=after.name then assert(R.GetSetMediaTrackInfo_String(tr,'P_NAME',after.name,true)) end
  if before.volume~=after.volume then assert(R.SetMediaTrackInfo_Value(tr,'D_VOL',after.volume/1e6)) end
  if before.pan~=after.pan then assert(R.SetMediaTrackInfo_Value(tr,'D_PAN',after.pan/1e6)) end
  for id,old in pairs(before.items) do if not after.items[id] then assert(R.DeleteTrackMediaItem(tr,ref.items[id].item)) end end
  for id,value in pairs(after.items) do
    local old=before.items[id]
    if not C.equal(old,value) then
      local ir=ref.items[id];local it,tk
      if ir then it=ir.item;tk=ir.take else
        it=assert(R.CreateNewMIDIItemInProj(tr,value.position/1e6,(value.position+value.length)/1e6,true))
        tk=assert(R.GetActiveTake(it));R.SetMediaItemInfo_Value(it,'B_LOOPSRC',0)
        ext(it,R.GetSetMediaItemInfo_String,'id',id);ext(it,R.GetSetMediaItemInfo_String,'birth',native(it))
        ext(tk,R.GetSetMediaItemTakeInfo_String,'id',value.take)
      end
      assert(R.SetMediaItemInfo_Value(it,'D_POSITION',R.TimeMap2_QNToTime(p,value.position/1e6)))
      local length=R.TimeMap2_QNToTime(p,(value.position+value.length)/1e6)-R.TimeMap2_QNToTime(p,value.position/1e6)
      assert(R.SetMediaItemInfo_Value(it,'D_LENGTH',length))
      if not old or not C.equal(old.notes,value.notes) then
        local _,count=R.MIDI_CountEvts(tk)
        for n=count-1,0,-1 do assert(R.MIDI_DeleteNote(tk,n)) end
        local matching=ir and C.match_notes(ir.records,value.notes) or {}
        for j,n in ipairs(value.notes) do
          local sel=ir and matching[j] and ir.records[matching[j]].selected or false
          assert(R.MIDI_InsertNote(tk,sel,n[6]==1,R.MIDI_GetPPQPosFromProjQN(tk,(value.position+n[1])/1e6),R.MIDI_GetPPQPosFromProjQN(tk,(value.position+n[1]+n[2])/1e6),n[5],n[3],n[4],true))
        end
        R.MIDI_Sort(tk)
      end
      R.UpdateItemInProject(it)
    end
  end
  local verified=M.capture(p)
  assert(C.equal(verified.tracks[before.id],after),'Apply verification failed; export recovery, do not publish partial state')
  R.UpdateArrange()
end
function M.export(p,root,accepted)
  local dump=C.object{accepted=accepted or C.object(),items=C.array(),tracks=C.array()}
  local ok,current=pcall(M.capture,p);if ok then dump.current=current else dump.error=tostring(current) end
  -- Live chunks preserve unsupported/unsaved data. Read only, never applied from network.
  for i=0,R.CountTracks(p)-1 do local tr=R.GetTrack(p,i);local got,chunk=R.GetTrackStateChunk(tr,'',false);assert(got);dump.tracks[#dump.tracks+1]=C.object{id=R.GetTrackGUID(tr),chunk=chunk} end
  local path=root..'/recovery/'..os.date('!%Y%m%dT%H%M%S')..'-'..C.id()..'.json'
  reaper.RecursiveCreateDirectory(root..'/recovery',0)
  C.write(path,dump);return path
end
return M
