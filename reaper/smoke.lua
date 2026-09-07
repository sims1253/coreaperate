-- Actual REAPER test. Use an EMPTY disposable project. No fake adapter.
local dir=debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])')
package.path=dir..'lib/?.lua;'..package.path
local C=require('common');local M=require('model')
local report={};local function check(v,s)assert(v,s);report[#report+1]='PASS '..s end
local ok,err=xpcall(function()
  local p=reaper.EnumProjects(-1)
  check(reaper.CountTracks(p)==0,'empty disposable project')
  dofile(dir..'demo.lua')
  reaper.SetProjExtState(p,'coreaperate','session',C.id())
  local base,refs=M.capture(p)
  local id=base.order[1];local iid=next(base.tracks[id].items)
  local cursor=reaper.GetCursorPositionEx(p)
  local tk=refs[id].items[iid].take
  reaper.MIDI_SetNote(tk,0,true,nil,nil,nil,nil,nil,nil,true);reaper.MIDI_Sort(tk)
  check(C.equal(M.capture(p),base),'note selection excluded')
  local after=C.copy(base.tracks[id]);after.name='Drüms 🥁';after.pan=-123456
  after.items[iid].notes[#after.items[iid].notes+1]=C.array{9000000,500000,70,99,2,1,0}
  table.sort(after.items[iid].notes,C.note_less)
  after.items[iid].length=2000000
  M.apply_track(p,base.tracks[id],after)
  check(C.equal(M.capture(p).tracks[id],after),'targeted note add/mute/channel/hidden tail and trim')
  check(reaper.GetCursorPositionEx(p)==cursor,'cursor preserved')
  local _,sel=reaper.MIDI_GetNote(tk,0);check(sel,'unchanged note selection preserved')
  local moved=C.copy(after);moved.items[iid].position=4000000
  M.apply_track(p,after,moved);check(C.equal(M.capture(p).tracks[id],moved),'move keeps relative QN notes')
  local added=C.copy(moved);local ni=C.copy(added.items[iid]);ni.id=C.id();ni.take=C.id();ni.position=16000000;added.items[ni.id]=ni
  M.apply_track(p,moved,added);check(C.equal(M.capture(p).tracks[id],added),'create item with hidden notes')
  local deleted=C.copy(added);deleted.items[ni.id]=nil
  M.apply_track(p,added,deleted);check(C.equal(M.capture(p).tracks[id],deleted),'delete item')
  reaper.MIDI_InsertCC(tk,false,false,reaper.MIDI_GetPPQPosFromProjQN(tk,5),0xb0,0,1,64)
  check(not pcall(M.capture,p),'user CC rejected without removal')
  local _,_,ccs=reaper.MIDI_CountEvts(tk);check(ccs>0,'unsupported CC preserved')
  -- Remove only test-injected CC, restoring our disposable test baseline.
  for i=ccs-1,0,-1 do
    local found,_,_,_,_,_,cc=reaper.MIDI_GetCC(tk,i)
    if found and cc==1 then reaper.MIDI_DeleteCC(tk,i) end
  end
  M.apply_track(p,deleted,base.tracks[id])
  local restored=M.capture(p);check(C.equal(restored,base),'complete round trip')
  reaper.SetProjExtState(p,'coreaperate','baseline',C.encode(base))
  reaper.SetProjExtState(p,'coreaperate','accepted',C.encode(base))
  local output=dir..'../runtime/smoke-baseline.rpp'
  reaper.Main_SaveProjectEx(p,output,0)
  C.write(dir..'../runtime/smoke-baseline.json',base)
  report[#report+1]='REAPER '..reaper.GetAppVersion()
end,debug.traceback)
report[#report+1]=ok and 'SUCCESS' or ('FAIL '..tostring(err))
local f=assert(io.open(dir..'../runtime/smoke-result.txt','wb'));f:write(table.concat(report,'\n'));f:close()
