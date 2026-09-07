-- Convenience action: creates a supported non-looped four-QN MIDI item on the selected track.
-- The bridge still observes/validates it normally; this does not publish or bypass ownership.
local p=reaper.EnumProjects(-1)
local tr=reaper.GetSelectedTrack(p,0)
assert(tr,'Select your owned track first')
local qn=reaper.TimeMap2_timeToQN(p,reaper.GetCursorPositionEx(p))
local it=assert(reaper.CreateNewMIDIItemInProj(tr,qn,qn+4,true))
reaper.SetMediaItemInfo_Value(it,'B_LOOPSRC',0)
reaper.UpdateItemInProject(it)
