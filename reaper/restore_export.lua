-- Explicit LOCAL recovery import. Never invoked by the companion or network.
local dir=debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])')
package.path=dir..'lib/?.lua;'..package.path
local C=require('common')
local p=reaper.EnumProjects(-1)
assert(reaper.CountTracks(p)==0,'Open an EMPTY disposable project for recovery import')
local ok,path=reaper.GetUserInputs('Import local recovery export',1,'Absolute JSON path:', '')
if not ok then return end
local f=assert(io.open(path,'rb'));local raw=f:read('*a');f:close()
-- Recovery files may exceed the network limit. Only this explicitly local importer allows that.
local dump,pos,err=require('dkjson').decode(raw)
assert(not err and type(dump)=='table' and type(dump.tracks)=='table','Invalid recovery file')
if reaper.ShowMessageBox('Import live track chunks from this LOCAL export into the empty project?\n'..path..'\nThis restores FX references but cannot supply missing plugins/samples. Keep this as a separate local branch.','Local recovery import',4)~=6 then return end
for i,t in ipairs(dump.tracks) do
  assert(type(t.chunk)=='string','Missing track chunk')
  reaper.InsertTrackInProject(p,i-1,0)
  assert(reaper.SetTrackStateChunk(reaper.GetTrack(p,i-1),t.chunk,false),'Recovery import failed; stop and preserve this project')
end
reaper.UpdateArrange()
reaper.ShowMessageBox('Imported as an offline branch. Save As a new local .rpp. Do not copy its edits into a live session without ownership and explicit reconciliation.','Recovery imported',0)
