-- Open a DISPOSABLE project and Save As before running.
local dir=debug.getinfo(1,'S').source:sub(2):match('^(.*[/\\])')
package.path=dir..'lib/?.lua;'..package.path
local C=require('common');local M=require('model')
local p,path=reaper.EnumProjects(-1)
local ok,err=xpcall(function()
  assert(path and path~='','Save this disposable project before preparing')
  local _,existing=reaper.GetProjExtState(p,'coreaperate','baseline');assert(existing=='','Already prepared; use a fresh disposable copy')
  -- Preflight can set IDs but never removes musical data. Save an unsaved-live backup first.
  local root=path:match('^(.*)[/\\]')
  M.export(p,root)
  reaper.SetProjExtState(p,'coreaperate','session',C.id())
  local model=M.capture(p)
  reaper.SetProjExtState(p,'coreaperate','baseline',C.encode(model))
  reaper.SetProjExtState(p,'coreaperate','accepted',C.encode(model))
  C.write(path..'.baseline.json',model)
  reaper.Main_SaveProject(p,false)
end,debug.traceback)
reaper.ShowMessageBox(ok and 'Prepared and saved. Close, then copy this baseline to TWO independent local .rpp files.\nBaseline JSON: '..path..'.baseline.json' or err,'Coreaperate preparation',0)
