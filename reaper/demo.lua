-- Only operates on a new empty disposable project. Save As, then run prepare.lua.
local p=reaper.EnumProjects(-1)
assert(reaper.CountTracks(p)==0,'Demo requires an empty disposable project')
reaper.SetCurrentBPM(p,120,true)
for i,name in ipairs({'Drums','Bass'}) do
  reaper.InsertTrackInProject(p,i-1,0)
  local tr=reaper.GetTrack(p,i-1)
  reaper.GetSetMediaTrackInfo_String(tr,'P_NAME',name,true)
  reaper.SetMediaTrackInfo_Value(tr,'D_VOL',.2)
  assert(reaper.TrackFX_AddByName(tr,'ReaSynth (Cockos)',false,-1)>=0,'Stock ReaSynth unavailable')
  local it=reaper.CreateNewMIDIItemInProj(tr,0,8,true)
  reaper.SetMediaItemInfo_Value(it,'B_LOOPSRC',0)
  local tk=reaper.GetActiveTake(it)
  for beat=0,7 do
    local pitch=i==1 and (beat%2==0 and 36 or 48) or (beat<4 and 40 or 43)
    local a=reaper.MIDI_GetPPQPosFromProjQN(tk,beat)
    local b=reaper.MIDI_GetPPQPosFromProjQN(tk,beat+(i==1 and .125 or .75))
    reaper.MIDI_InsertNote(tk,false,false,a,b,0,pitch,90,true)
  end
  reaper.MIDI_Sort(tk)
end
reaper.UpdateArrange()
